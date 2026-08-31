# BlazeBVD STE + staged neural training

This package preserves the supplied deterministic STE/video/report paths and
adds a complete training path for the neural modules that follow STE:

```text
STE (fixed) -> GFRM -> LFRM -> TCM -> saturated-red post-correction
```

The BlazeBVD authors did not publish official code or weights. Architecture and
published loss terms are reimplemented from the paper/supplement; undisclosed
synthetic-degradation distributions are clearly isolated in `configs/train.yaml`.

## Quick verification

```powershell
python -m venv .blazebvd4
.\.blazebvd4\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,train]"

python scripts/make_smoke_dataset.py --output data/smoke
python scripts/run_training_pipeline.py `
  --data data/smoke `
  --output runs/smoke `
  --smoke
```

The smoke run executes GFRM, LFRM and TCM for one short epoch each. It verifies
gradient flow, inherited checkpoints and log creation; its weights must not be
used to judge video quality.

## DAVIS training

Download the official DAVIS 2017 TrainVal 480p release:

```powershell
python scripts/download_davis.py --output data
```

Official source: <https://davischallenge.org/davis2017/code.html>

Then run all three stages:

```powershell
python scripts/run_training_pipeline.py `
  --data data/DAVIS/JPEGImages/480p `
  --config configs/default.yaml `
  --training-config configs/train.yaml `
  --output runs/davis_blazebvd `
  --device cuda `
  --flow raft_small `
  --batch-size 1 `
  --clip-length 12 `
  --crop-size 256 `
  --workers 4 `
  --amp `
  --perceptual `
  --adversarial `
  --long-warp `
  --tensorboard
```

The default schedule is GFRM 40 epochs, LFRM 20 epochs and TCM 30 epochs.
Each stage loads the preceding stage's `best.pt` automatically. See
[`TRAINING.md`](TRAINING.md) for stage-specific commands, resume behaviour,
loss definitions and output files.

## Inference with the trained TCM checkpoint

```powershell
blazebvd correct input.mp4 `
  -o outputs/corrected.mp4 `
  --stage full `
  --checkpoint runs/davis_blazebvd/tcm/best.pt `
  --report outputs/corrected-report.json
```

The temporal-excess and rebound terms are training regularizers, not a
standards-compliant photosensitive-epilepsy detector. Final outputs still need
to be rechecked by the project's PSE detector; visual quality and safety must
be evaluated separately.
