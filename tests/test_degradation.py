import torch

from blazebvd.degradation import synthesize_flicker


def test_synthetic_flicker_shapes_and_equation():
    clean = torch.full((1, 8, 3, 16, 16), 0.5)
    degraded, artifact = synthesize_flicker(clean)
    assert degraded.shape == clean.shape
    assert artifact.shape == clean.shape
    torch.testing.assert_close(degraded, (clean + artifact).clamp(0, 1))

