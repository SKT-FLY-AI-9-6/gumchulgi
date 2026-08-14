from __future__ import annotations

from dataclasses import replace

import torch

from blazebvd.config import (
    AccessibilityCorrectionConfig,
    FlashCorrectionConfig,
    RedCorrectionConfig,
)
from blazebvd.correction import (
    apply_accessibility_corrections,
    attenuate_saturated_red,
    attenuate_saturated_red_stateful,
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


def _separation_config(**overrides) -> RedCorrectionConfig:
    base = RedCorrectionConfig(
        red_ratio_threshold=0.5,
        red_ratio_transition_width=0.05,
        minimum_saturation=0.2,
        saturation_transition_width=0.05,
        strength=1.0,
        reflected_strength=1.0,
        mask_blur_radius=0,
        illumination_size=1,
        emissive_value_threshold=0.8,
        emissive_transition_width=0.1,
    )
    return replace(base, **overrides)


def test_illumination_separation_preserves_region_chroma_contrast():
    # Two different reflectances under the same red light. Plain desaturation
    # collapses both regions to gray; illuminant division must keep them apart.
    frame = torch.zeros(1, 3, 4, 8)
    frame[0, :, :, :4] = torch.tensor([0.7, 0.20, 0.15]).reshape(3, 1, 1)
    frame[0, :, :, 4:] = torch.tensor([0.6, 0.10, 0.25]).reshape(3, 1, 1)
    config = _separation_config(emissive_value_threshold=0.95)

    old = attenuate_saturated_red(frame, replace(config, illumination_separation=False))
    new = attenuate_saturated_red(frame, replace(config, illumination_separation=True))

    def region_chroma_gap(frames: torch.Tensor) -> torch.Tensor:
        chroma = frames / frames.sum(dim=1, keepdim=True).clamp_min(1e-6)
        left = chroma[0, :, :, :4].mean(dim=(1, 2))
        right = chroma[0, :, :, 4:].mean(dim=(1, 2))
        return (left - right).abs().sum()

    assert region_chroma_gap(new) > region_chroma_gap(old) + 0.02
    torch.testing.assert_close(
        relative_luminance(new), relative_luminance(frame), atol=1e-4, rtol=0
    )


def test_emissive_source_keeps_desaturation_but_reflection_is_adapted():
    frame = torch.zeros(1, 3, 4, 8)
    # Left: the light source itself (near clipping). Right: a person lit by it.
    frame[0, :, :, :4] = torch.tensor([1.0, 0.05, 0.05]).reshape(3, 1, 1)
    frame[0, :, :, 4:] = torch.tensor([0.55, 0.16, 0.10]).reshape(3, 1, 1)
    config = _separation_config()

    old = attenuate_saturated_red(frame, replace(config, illumination_separation=False))
    new = attenuate_saturated_red(frame, replace(config, illumination_separation=True))

    torch.testing.assert_close(
        new[0, :, :, :4], old[0, :, :, :4], atol=1e-5, rtol=0
    )
    assert (new[0, :, :, 4:] - old[0, :, :, 4:]).abs().max() > 0.02


def test_temporal_gating_limits_attenuation_to_red_transitions():
    frames = torch.full((26, 3, 4, 4), 0.1)
    frames[5:] = torch.tensor([0.8, 0.05, 0.05]).reshape(1, 3, 1, 1)
    config = _separation_config(
        temporal_gating=True,
        gating_threshold=0.05,
        gating_transition_width=0.05,
        gating_decay=0.6,
    )

    corrected = attenuate_saturated_red(frames, config)
    ungated = attenuate_saturated_red(frames, replace(config, temporal_gating=False))

    torch.testing.assert_close(corrected[:5], frames[:5], atol=1e-4, rtol=0)
    assert (corrected[5] - frames[5]).abs().max() > 0.05
    # Long after the onset the red light is steady, so gating leaves it alone
    # while the ungated filter would still attenuate it.
    torch.testing.assert_close(corrected[25], frames[25], atol=1e-3, rtol=0)
    assert (ungated[25] - frames[25]).abs().max() > 0.05


def test_stateful_red_attenuation_matches_whole_video_call():
    torch.manual_seed(0)
    frames = torch.rand(10, 3, 8, 8) * 0.3
    frames[3:6] = torch.tensor([0.9, 0.08, 0.06]).reshape(1, 3, 1, 1)
    config = _separation_config(
        temporal_gating=True,
        gating_decay=0.6,
        mask_blur_radius=1,
        illumination_size=2,
    )

    full = attenuate_saturated_red(frames, config)
    state = None
    parts = []
    for start in range(0, frames.shape[0], 3):
        chunk, state = attenuate_saturated_red_stateful(
            frames[start : start + 3], config, state
        )
        parts.append(chunk)

    torch.testing.assert_close(torch.cat(parts), full)


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
