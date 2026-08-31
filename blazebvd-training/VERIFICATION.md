# Verification report

Date: 2026-08-12

## Scope

The supplied `src`, `configs` and `tests` paths were retained. Training support
was added after the current deterministic STE implementation without replacing
the existing in-memory/streaming STE report paths.

## Automated checks

- Python syntax/AST parse: 28 Python files parsed successfully at the first check
- Ruff: `All checks passed`
- Pytest: `33 passed`
- Existing STE, correction, model and streaming-report tests remained green
- New tests cover:
  - reconstruction of the RGB STE reference
  - synthetic LFRM oracle masks
  - LFRM gradient flow with zero STE singular frames
  - temporal-excess and STE-rebound safety losses
  - automatic discovery of DAVIS official train/val lists

## End-to-end smoke training

Command:

```text
python scripts/run_training_pipeline.py \
  --data data/smoke \
  --output runs/smoke_pipeline \
  --smoke
```

All stages completed and wrote `best.pt`, `last.pt`, CSV/JSONL metrics and a
run manifest.

| Stage | Trainable parameters | Updates | Best validation loss |
|---|---:|---:|---:|
| GFRM | 4,703,939 | 2 | 0.1691648 |
| LFRM | 16,595 | 2 | 0.3928371 |
| TCM | 173,781 | 2 | 0.3695662 |

These losses come from randomly initialized models and a tiny generated
dataset. They demonstrate executable training only and are not performance
claims.

## Additional execution checks

- TCM resume loaded `last.pt`, started at epoch 2 and advanced global step 2 -> 3.
- TCM adversarial + long-warp run updated both generator and discriminator.
- VGG perceptual module (`pretrained=False`) completed forward and backward.
- Final TCM checkpoint completed full overlap-clip inference.
- Resulting test video: H.264, 64x64, 12 fps, 8 input/output frames.
- Inference report retained `ste_scope: full_video` and the supplied correction order.

## Not performed

The full 40/20/30-epoch DAVIS training was not run in this CPU-only verification
environment. The DAVIS downloader and official split discovery are included,
but the smoke checkpoints must not be used for real-video evaluation.
