# Implementation notes and uncertainty register

This file separates published BlazeBVD facts from reimplementation decisions.

## Directly specified by the paper or supplement

| Component | Published specification | Implementation |
|---|---|---|
| Illumination | `V_t = max(R,G,B)` | `ste.rgb_value` |
| STE | Gaussian-weighted temporal average of histogram quantile mappings | `ScaleTimeEqualization` |
| Singular frame | `KL(H_tilde || H_t)` above its local moving mean | `singular_frames` |
| Exposure map | `V_tilde < epsilon_1 or V_tilde > epsilon_2` | Published rule; see extension below |
| GFRM input | 6 channels | RGB + 1-channel filtered V repeated to RGB |
| GFRM | 6-32-64-128-256-512 U-Net, output 3 | `models/gfrm.py` |
| LFRM | 9-32, NonLocal, 1x1 32-32, NonLocal 32-3 | `models/lfrm.py` |
| Flow | RAFT | torchvision RAFT adapter |
| TCM | 3-16 branch; recurrent 16; 16-32-64; Transformer x8; 64-32-16; 32-16-16-3 | `models/tcm.py` |
| Loss weights | rec 1, perceptual 1, adversarial 0.01, warp 0.1 | `tcm_generator_loss` |
| Synthetic data | additive `X_t=G_t+F_t`, W sampled in [2,12] | `synthesize_flicker` |

## Corrections to paper ambiguities

1. Equation (9) repeats `X_t-1` in the third branch while pairing it with flow
   from `t+1`. This implementation uses the following frame `X_t+1`.
2. RAFT reports forward displacement, while `grid_sample` needs, for each
   target pixel, a coordinate in the source. The API therefore estimates
   **target-to-source** flow and names tensors accordingly.
3. A 6-channel GFRM input is required by the supplement, but the main paper
   describes RGB plus an illumination map. The map is repeated three times to
   form RGB(3)+V(3). This must be compared with a 4-channel variant in ablation.

## Accessibility-oriented STE extensions

The following behavior is intentionally not claimed as part of the published
BlazeBVD method:

1. Every original `V > bright_threshold` pixel is subject to a continuous
   highlight ceiling, regardless of its frame-area ratio.
2. A centered per-pixel temporal median identifies local V-channel outliers.
   Their deviation is limited by `max_temporal_deviation`, independently of the
   fraction of the frame that changes.
3. `exposure_maps` are derived from the original value map so successfully
   compressed highlights remain visible to downstream restoration/reporting.
4. Inside STE, short luminance blocks are consolidated after brightness
   correction to a low-resolution temporal median. Only a gain map is
   transferred to the current RGB frame; neighboring RGB content is never
   copied. The resulting V map replaces the `filtered_value` prior before GFRM.
5. Saturated-red attenuation runs after GFRM/LFRM/TCM. It uses a soft red/saturation mask and
   interpolates toward a neutral color with the same linear-light luminance.
6. These stages do not implement a PSE pass/fail verdict or count flashes in a
   one-second standards window. Input selection and output validation remain the
   responsibility of the external detector.

## Values and behavior not disclosed by the authors

- STE radius `l`, Gaussian scale `s`, and singular moving radius `n`
- Exposure thresholds `epsilon_1`, `epsilon_2`
- Actual distribution, amplitude, and spatial form of synthetic artifact `F_t`
- Activations, normalization, U-Net output parameterization, and exact upsampling
- Non-local block internal dimension, pooling, and memory strategy
- Exact Swin/Transformer block definition used in the reduced TCM
- Exact exposure weight `W_t`, occlusion mask `M_t,s`, and VGG feature layers
- Optimizer, learning rate, schedule, batch/crop size, epochs, and freeze order
- Full-video versus clip strategy during training/inference

These values are configuration or isolated module choices. Do not report the
paper's PSNR/SSIM/Ewarp as reproduced until the ablations resolve them and the
official evaluation protocol is matched.

## Recommended validation order

1. Unit-test STE with constant, single-pulse, monotonic, and color-preservation videos.
2. Train GFRM and compare 4-channel vs 6-channel inputs.
3. Validate flow direction on synthetic translations before training LFRM.
4. Compare LFRM with no non-local, standard non-local, and pooled non-local blocks.
5. Train TCM first without GAN, then add perceptual and adversarial losses.
6. Report PSNR, SSIM, Ewarp, runtime, memory, and post-filter PSE detector results.
