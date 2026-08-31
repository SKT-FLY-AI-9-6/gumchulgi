from __future__ import annotations

import torch

from blazebvd.config import (
    AccessibilityCorrectionConfig,
    FlashCorrectionConfig,
    RedCorrectionConfig,
)
from blazebvd.correction import (
    apply_accessibility_corrections,
    attenuate_saturated_red,
    consolidate_temporal_flashes,
    relative_luminance,
)


def _uniform_video(levels: list[float], height: int = 4, width: int = 4) -> torch.Tensor:
    return torch.tensor(levels).reshape(-1, 1, 1, 1).expand(-1, 3, height, width).clone()


def test_flash_blocks_consolidate_alternating_states():
    frames = _uniform_video([0.2, 0.8, 0.2, 0.8, 0.2, 0.8, 0.2])
    config = FlashCorrectionConfig(
        block_duration_seconds=0.3,
        minimum_block_frames=1,
        analysis_size=1,
        contrast_threshold=0.0,
        transition_width=0.0,
        strength=1.0,
        minimum_gain=0.01,
        maximum_gain=100.0,
        scene_cut_threshold=1.0,
    )

    corrected = consolidate_temporal_flashes(frames, fps=10.0, config=config)
    expected = _uniform_video([0.2, 0.2, 0.2, 0.8, 0.8, 0.8, 0.2])

    torch.testing.assert_close(corrected, expected, atol=2e-5, rtol=0)


def test_flash_correction_uses_current_frame_texture():
    texture = torch.tensor(
        [
            [[0.2, 0.4], [0.6, 0.8]],
            [[0.1, 0.2], [0.3, 0.4]],
            [[0.05, 0.1], [0.15, 0.2]],
        ]
    )
    frames = torch.stack([texture * 0.4, texture, texture * 0.4])
    config = FlashCorrectionConfig(
        block_duration_seconds=0.3,
        minimum_block_frames=1,
        analysis_size=1,
        contrast_threshold=0.0,
        transition_width=0.0,
        minimum_gain=0.01,
        maximum_gain=100.0,
        scene_cut_threshold=1.0,
    )

    corrected = consolidate_temporal_flashes(frames, fps=10.0, config=config)

    # A scalar gain changes brightness but retains the current frame's spatial
    # ordering; no pixel pattern from a neighboring frame is copied.
    assert torch.equal(
        torch.argsort(corrected[1].flatten()),
        torch.argsort(frames[1].flatten()),
    )


def test_red_attenuation_reduces_red_ratio_and_preserves_luminance():
    frames = torch.tensor([1.0, 0.05, 0.05]).reshape(1, 3, 1, 1)
    config = RedCorrectionConfig(
        red_ratio_threshold=0.5,
        red_ratio_transition_width=0.0,
        minimum_saturation=0.0,
        saturation_transition_width=0.0,
        strength=1.0,
        mask_blur_radius=0,
    )

    before_luminance = relative_luminance(frames)
    corrected = attenuate_saturated_red(frames, config)
    after_luminance = relative_luminance(corrected)
    before_ratio = frames[:, 0] / frames.sum(dim=1)
    after_ratio = corrected[:, 0] / corrected.sum(dim=1)

    assert torch.all(after_ratio < before_ratio)
    torch.testing.assert_close(after_luminance, before_luminance, atol=1e-6, rtol=0)


def test_non_red_frames_are_unchanged():
    frames = torch.rand(4, 3, 4, 4)
    frames[:, 0] = 0.0
    corrected = attenuate_saturated_red(frames, RedCorrectionConfig())
    torch.testing.assert_close(corrected, frames)


def test_pipeline_order_is_flash_then_red():
    frames = torch.zeros(3, 3, 2, 2)
    frames[0] = torch.tensor([0.2, 0.01, 0.01]).reshape(3, 1, 1)
    frames[1] = torch.tensor([1.0, 0.02, 0.02]).reshape(3, 1, 1)
    frames[2] = frames[0]
    config = AccessibilityCorrectionConfig(
        flash=FlashCorrectionConfig(
            block_duration_seconds=0.3,
            minimum_block_frames=1,
            contrast_threshold=0.0,
            transition_width=0.0,
            minimum_gain=0.01,
            maximum_gain=100.0,
            scene_cut_threshold=1.0,
        ),
        red=RedCorrectionConfig(mask_blur_radius=0),
    )

    actual = apply_accessibility_corrections(frames, fps=10.0, config=config)
    expected = attenuate_saturated_red(
        consolidate_temporal_flashes(frames, fps=10.0, config=config.flash),
        config.red,
    )

    torch.testing.assert_close(actual, expected)
