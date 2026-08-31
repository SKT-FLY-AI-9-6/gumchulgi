from pathlib import Path

import torch

from blazebvd.config import BlazeBVDConfig
from blazebvd.flow import ZeroFlow
from blazebvd.losses import safety_regularization
from blazebvd.models.lfrm import LocalFlickerRemovalModule
from blazebvd.models.pipeline import BlazeBVD
from blazebvd.training import ste_rgb_reference, synthetic_lfrm_masks


def test_ste_rgb_reference_uses_filtered_value():
    cfg = BlazeBVDConfig()
    cfg.ste.bins = 32
    cfg.ste.window_radius = 0
    cfg.ste.bright_threshold = 0.8
    cfg.ste.bright_compression_ratio = 0.0
    model = BlazeBVD(cfg, flow_estimator=ZeroFlow())
    frames = torch.ones(1, 3, 3, 8, 8)
    priors = model.ste(frames)

    reference = ste_rgb_reference(frames, priors)

    torch.testing.assert_close(reference.amax(dim=2, keepdim=True), priors.filtered_value)


def test_synthetic_masks_activate_lfrm_when_ste_does_not():
    cfg = BlazeBVDConfig()
    cfg.ste.bins = 32
    cfg.ste.window_radius = 0
    model = BlazeBVD(cfg, flow_estimator=ZeroFlow())
    frames = torch.full((1, 3, 3, 8, 8), 0.5)
    priors = model.ste(frames)
    artifact = torch.zeros_like(frames)
    artifact[:, 1, :, 2:6, 2:6] = 0.2

    exposure, active = synthetic_lfrm_masks(artifact, priors, threshold=0.03)

    assert bool(active[0, 1])
    assert bool(exposure[0, 1, 0, 3, 3])


def test_lfrm_force_all_keeps_gradient_with_no_singular_frames():
    module = LocalFlickerRemovalModule(max_positions=64)
    corrected = torch.rand(1, 3, 3, 16, 16)
    exposure = torch.ones(1, 3, 1, 16, 16)
    singular = torch.zeros(1, 3, dtype=torch.bool)
    flows = torch.zeros(1, 2, 2, 16, 16)

    prediction = module.refine_sequence(
        corrected,
        exposure,
        singular,
        flows,
        flows,
        force_all=True,
    )
    prediction.mean().backward()

    assert any(
        parameter.grad is not None and bool(parameter.grad.abs().sum() > 0)
        for parameter in module.parameters()
    )


def test_safety_regularization_penalizes_new_flash_and_rebound():
    target = torch.full((1, 3, 3, 4, 4), 0.2)
    degraded = target.clone()
    degraded[:, 1] = 1.0
    ste = target.clone()
    safe_prediction = target.clone()
    unsafe_prediction = target.clone()
    unsafe_prediction[:, 1] = 0.9

    safe, _ = safety_regularization(safe_prediction, degraded, target, ste)
    unsafe, parts = safety_regularization(unsafe_prediction, degraded, target, ste)

    assert safe == 0
    assert unsafe > 0
    assert parts["temporal_excess"] > 0
    assert parts["rebound"] > 0


def test_official_davis_split_is_found_from_frame_root(tmp_path: Path):
    from blazebvd.data import resolve_sequence_splits

    root = tmp_path / "DAVIS"
    frames = root / "JPEGImages" / "480p"
    for name in ("train-a", "val-a"):
        (frames / name).mkdir(parents=True)
    split_root = root / "ImageSets" / "2017"
    split_root.mkdir(parents=True)
    (split_root / "train.txt").write_text("train-a\n", encoding="utf-8")
    (split_root / "val.txt").write_text("val-a\n", encoding="utf-8")

    train, val, source = resolve_sequence_splits(frames)

    assert train == ["train-a"]
    assert val == ["val-a"]
    assert source == "davis_2017_official"
