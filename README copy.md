# BlazeBVD reimplementation

An executable, paper-faithful reimplementation scaffold of **BlazeBVD: Make
Scale-Time Equalization Great Again for Blind Video Deflickering** (ECCV 2024).

> The paper authors have not released official BlazeBVD source code or trained
> weights. This repository implements the published equations and supplementary
> architecture table. Undisclosed choices are isolated in configuration and are
> documented in `IMPLEMENTATION_NOTES.md`. It is not an official implementation
> and cannot reproduce the paper's reported numbers before training and ablation.

## Implemented

- Stage 1: illumination-space STE, filtered value maps, KL singular-frame set,
  and over/under-exposure maps (equations 3-6)
- GFRM: 6-channel 2D U-Net with the supplementary channel schedule
- LFRM: RAFT warping, masked neighbor texture transfer, 9-channel fusion, and
  two memory-safe non-local blocks
- TCM: 16-channel bidirectional recurrent propagation, eight window-transformer
  blocks, and residual RGB reconstruction based on the RTN-derived supplement
- Losses: reconstruction, VGG perceptual, 3D PatchGAN adversarial, and adaptive
  exposure-weighted warp loss with optional long-term first-frame term
- DAVIS-style clean video dataset loader and configurable synthetic flicker
- Video correction CLI, audio remuxing, reports, staged trainer, and tests

## Installation

Python 3.10+ and a matching PyTorch/CUDA installation are required. Install
PyTorch first using the command for your CUDA version from the official PyTorch
site, then install this project:

```powershell
cd blazebvd-reimplementation
python -m pip install -e ".[dev]"
```

Verify the installation:

```powershell
python -m pytest -q
blazebvd --help
```

`ffmpeg` is optional but required to preserve the source video's audio. OpenCV
still writes a silent MP4 when it is unavailable.

## Use before training: STE baseline

The deterministic Stage 1 baseline needs no neural checkpoint:

```powershell
blazebvd correct "input.mp4" `
  -o "outputs/ste.mp4" `
  --stage ste `
  --report "outputs/ste-report.json"
```

This runs the configured deterministic correction chain in the following fixed
order:

```text
STE/highlight brightness correction
→ temporal flash consolidation (inside the STE stage)
→ saturated-red attenuation
```

No PSE pass/fail detector or one-second flash-count decision is included in this
chain. It is intended for videos already selected by an external detector. The
CLI still uses two video passes: the first stores only 256-bin frame histograms
in a temporary on-disk array, and the second corrects and writes small temporal
blocks. It therefore does not load the complete video into CPU memory.

In addition to temporal histogram equalization, every source pixel whose HSV
value exceeds `ste.bright_threshold` is forced through continuous highlight
compression. This rule is pixel-wise and never uses the bright-area percentage
to decide whether correction runs. The ratio accepts values from `-1.0` to
`1.0`; a negative value lowers brighter source pixels farther below the
threshold. With the default threshold `0.80` and
`bright_compression_ratio: -0.25`, an input value of `1.00` is capped at `0.75`.
The `exposed_pixel_ratio` report field is diagnostic only and does not gate the
correction.

The legacy optional temporal flash limiter computes a
centered per-pixel median over `2 * temporal_radius + 1` value maps. Pixels that
differ from that reference by at least `flash_contrast_threshold` are limited
to `max_temporal_deviation` from the reference, then blended according to
`flash_suppression_strength`. This decision is also independent of changed-area
percentage. The streaming CLI retains only the small temporal frame window
needed by this limiter instead of loading the full video. It is disabled by
default so `correction.flash` is the single temporal-flash stage; enable it only
when the earlier pixel-wise limiter is intentionally required.

These highlight and temporal limiters are accessibility-oriented extensions to
the published BlazeBVD STE equations. They reduce local temporal contrast but
do not by themselves certify compliance with a photosensitive-epilepsy safety
standard; validate the final pipeline output with the target PSE detector.

### Temporal flash consolidation

`correction.flash` processes every short time block inside STE when enabled. It
downsamples only the luminance analysis map, replaces each block's local
luminance targets with their temporal median, and converts the result back into
the `filtered_value` prior consumed by GFRM. It never copies RGB pixels from
neighboring frames. With a three-frame block, this gives the intended state
consolidation:

```text
low → high → low   becomes   low → low → low
high → low → high  becomes   high → high → high
```

The most useful controls are:

- `block_duration_seconds` and `minimum_block_frames`: consolidated block size
- `strength`: blend toward the block representative state
- `contrast_threshold` and `transition_width`: minimum correction and soft onset
- `minimum_gain` and `maximum_gain`: darkening/brightening limits
- `analysis_size`: spatial detail of the local gain map
- `scene_cut_threshold`: optionally break a block at a large discontinuity;
  `1.0` disables it and is the default because a full-frame flash can resemble
  a scene cut

### Saturated-red attenuation

`correction.red` runs after flash consolidation. In `--stage full`, it runs after
GFRM, LFRM, and TCM; in `--stage ste`, it runs directly after the STE flash
stage. A soft mask combines red-channel dominance and saturation, then moves
only those pixels toward a neutral color in linear RGB. The neutral target has
the same relative luminance, so the stage primarily reduces red chroma instead
of simply darkening red regions.

The main controls are `red_ratio_threshold`, `minimum_saturation`, `strength`,
and `mask_blur_radius`. Set either correction stage's `enabled` field to `false`
to bypass it without changing the fixed stage order.

## Dataset layout

Extract clean DAVIS clips into one directory per sequence:

```text
data/DAVIS/JPEGImages/480p/
├── bear/
│   ├── 00000.jpg
│   ├── 00001.jpg
│   └── ...
├── blackswan/
│   └── ...
└── ...
```

The loader samples a clean clip and generates piecewise-constant synthetic
flicker online. The paper specifies `X_t = G_t + F_t` and artifact window length
`W in [2,12]`, but does not specify the distribution of `F_t`; adjust
`FlickerSynthesisConfig` during ablation.

## Staged training

### 1. GFRM

```powershell
blazebvd-train `
  --stage gfrm `
  --data "data/DAVIS/JPEGImages/480p" `
  --epochs 40 `
  --batch-size 4 `
  --crop-size 256 `
  --amp
```

The paper also pretrains GFRM with all 118,287 COCO train images. This initial
version provides the video-clip trainer; COCO images can be exposed as repeated
pseudo-clips or added through a separate image loader.

### 2. LFRM

```powershell
blazebvd-train `
  --stage lfrm `
  --data "data/DAVIS/JPEGImages/480p" `
  --init-checkpoint "checkpoints/gfrm_epoch_040.pt" `
  --epochs 20 `
  --batch-size 1 `
  --amp
```

The default config uses torchvision's pretrained RAFT-small. Its weights are
downloaded on first use. Use `flow.backend: farneback` only as a CPU/debug
fallback; it is not paper-faithful.

### 3. TCM

```powershell
blazebvd-train `
  --stage tcm `
  --data "data/DAVIS/JPEGImages/480p" `
  --init-checkpoint "checkpoints/lfrm_epoch_020.pt" `
  --epochs 30 `
  --batch-size 1 `
  --perceptual `
  --adversarial `
  --long-warp `
  --amp
```

The resulting generator objective is the published weighting:

```text
L_TCM = 1.0 L_rec + 1.0 L_per + 0.01 L_adv + 0.1 L_warp
```

Fine-tuning all neural stages together is also available with `--stage joint`.

## Full inference

```powershell
blazebvd correct "input.mp4" `
  -o "outputs/corrected.mp4" `
  --checkpoint "checkpoints/tcm_epoch_030.pt" `
  --stage full `
  --report "outputs/report.json"
```

Use `--stage stage2` to stop after GFRM+LFRM. Long videos are processed as
overlapping clips. The overlap is blended, but Stage 1 is recomputed per clip in
this initial implementation; evaluate boundary frames separately when matching
paper metrics.

For `--stage full`, the effective order is:

```text
STE/highlight brightness correction
→ temporal flash consolidation in the STE filtered-value prior
→ GFRM → LFRM → TCM
→ saturated-red attenuation
```

## Important project constraint

BlazeBVD is a perceptual deflickering method, not a photosensitive-epilepsy
compliance algorithm. For the wider PSE mitigation project, always run the
existing flash/red-pattern detector again after BlazeBVD and apply a deterministic
safety limiter if any violation remains.

## References

- Xinmin Qiu et al., BlazeBVD, ECCV 2024: https://arxiv.org/abs/2403.06243
- ECCV paper: https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/02526.pdf
- Supplement: https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/02526-supp.pdf
- RAFT: https://github.com/princeton-vl/RAFT
- RTN: https://github.com/raywzy/Bringing-Old-Films-Back-to-Life
