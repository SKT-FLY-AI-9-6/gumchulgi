# Training integration changes

- Replaced sequence-count epochs with configurable clip samples per epoch.
- Added official DAVIS train/val split discovery and deterministic fallback splitting.
- Added deterministic per-sample/epoch seeding compatible with multiple workers.
- Expanded synthetic data with rapid, impulse, local, color and saturated-red flicker.
- Made LFRM accept training-only active masks and `force_all` to prevent no-gradient batches.
- Added artifact-weighted LFRM loss.
- Added temporal-excess and STE-rebound regularizers to all neural stages.
- Made training STE invocation use the same flash configuration as inference.
- Added GFRM -> LFRM -> TCM checkpoint inheritance.
- Added validation, best/last checkpoints, resume, warmup+cosine LR, AMP and gradient clipping.
- Added CSV, JSONL, TensorBoard and run-manifest logging.
- Added optional perceptual, GAN, adjacent/long adaptive-warp TCM losses.
- Added one-command smoke/full training scripts and official DAVIS download helper.
- Added non-ASCII-safe image loading for Windows training paths.
