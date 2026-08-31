from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import Tensor

from .config import (
    AccessibilityCorrectionConfig,
    FlashCorrectionConfig,
    RedCorrectionConfig,
)


def _as_batch(frames: Tensor) -> tuple[Tensor, bool]:
    if frames.ndim == 4 and frames.shape[1] == 3:
        return frames.unsqueeze(0), True
    if frames.ndim == 5 and frames.shape[2] == 3:
        return frames, False
    raise ValueError("frames must have shape [T,3,H,W] or [B,T,3,H,W]")


def _srgb_to_linear(frames: Tensor) -> Tensor:
    return torch.where(
        frames <= 0.04045,
        frames / 12.92,
        ((frames + 0.055) / 1.055).pow(2.4),
    )


def _linear_to_srgb(frames: Tensor) -> Tensor:
    return torch.where(
        frames <= 0.0031308,
        frames * 12.92,
        1.055 * frames.clamp_min(0).pow(1.0 / 2.4) - 0.055,
    )


def relative_luminance(frames: Tensor) -> Tensor:
    """Return linear-light relative luminance with a retained channel axis."""
    batch, squeezed = _as_batch(frames)
    linear = _srgb_to_linear(batch.float().clamp(0, 1))
    luminance = (
        0.2126 * linear[:, :, 0:1]
        + 0.7152 * linear[:, :, 1:2]
        + 0.0722 * linear[:, :, 2:3]
    )
    return luminance[0] if squeezed else luminance


def flash_block_frame_count(fps: float, config: FlashCorrectionConfig) -> int:
    if fps <= 0:
        raise ValueError("fps must be positive")
    return max(
        config.minimum_block_frames,
        int(round(fps * config.block_duration_seconds)),
        1,
    )


def _analysis_luminance(luminance: Tensor, analysis_size: int) -> Tensor:
    b, t, _, height, width = luminance.shape
    scale = min(1.0, analysis_size / max(height, width))
    target_height = max(1, int(round(height * scale)))
    target_width = max(1, int(round(width * scale)))
    flat = luminance.reshape(b * t, 1, height, width)
    if (target_height, target_width) != (height, width):
        flat = F.interpolate(
            flat,
            size=(target_height, target_width),
            mode="area",
        )
    return flat.reshape(b, t, 1, target_height, target_width)


def _smooth_weight(
    difference: Tensor,
    threshold: float,
    transition_width: float,
) -> Tensor:
    if transition_width == 0:
        return (difference > threshold).to(difference.dtype)
    weight = ((difference - threshold) / transition_width).clamp(0.0, 1.0)
    return weight.square() * (3.0 - 2.0 * weight)


def _block_targets(
    luminance: Tensor,
    block_frames: int,
    scene_cut_threshold: float,
    frame_offset: int = 0,
) -> Tensor:
    """Consolidate each short block to its per-location median luminance.

    Scene cuts only reset block processing; they are not reported or used as a
    PSE pass/fail decision.
    """
    targets = luminance.clone()
    b, t = luminance.shape[:2]
    if frame_offset < 0:
        raise ValueError("frame_offset must be non-negative")
    first_block_frames = block_frames - (frame_offset % block_frames)
    for batch_index in range(b):
        block_start = 0
        while block_start < t:
            current_block_frames = (
                first_block_frames if block_start == 0 else block_frames
            )
            nominal_end = min(t, block_start + current_block_frames)
            block_end = nominal_end
            if scene_cut_threshold < 1.0:
                for index in range(block_start + 1, nominal_end):
                    change = (
                        luminance[batch_index, index]
                        - luminance[batch_index, index - 1]
                    ).abs().mean()
                    if float(change) >= scene_cut_threshold:
                        block_end = index
                        break
            if block_end == block_start:
                block_end += 1
            representative = luminance[
                batch_index, block_start:block_end
            ].median(dim=0).values
            targets[batch_index, block_start:block_end] = representative
            block_start = block_end
    return targets


@torch.no_grad()
def consolidate_temporal_flashes(
    frames: Tensor,
    fps: float,
    config: FlashCorrectionConfig,
    frame_offset: int = 0,
) -> Tensor:
    """Merge short luminance states without copying pixels across frames.

    Each temporal block receives a low-resolution median luminance target. The
    target/current ratio becomes a smooth gain map applied to the current frame,
    so motion and texture always come from that current frame.
    """
    config.validate()
    batch, squeezed = _as_batch(frames)
    original_dtype = batch.dtype
    working = batch.float().clamp(0, 1)
    if not config.enabled or working.shape[1] <= 1 or config.strength == 0:
        return frames.clone()

    linear = _srgb_to_linear(working)
    luminance = (
        0.2126 * linear[:, :, 0:1]
        + 0.7152 * linear[:, :, 1:2]
        + 0.0722 * linear[:, :, 2:3]
    )
    analysis = _analysis_luminance(luminance, config.analysis_size)
    block_frames = flash_block_frame_count(fps, config)
    target = _block_targets(
        analysis,
        block_frames,
        config.scene_cut_threshold,
        frame_offset,
    )

    difference = (target - analysis).abs()
    correction_weight = _smooth_weight(
        difference,
        config.contrast_threshold,
        config.transition_width,
    ) * config.strength
    desired = torch.lerp(analysis, target, correction_weight)
    gain = desired / analysis.clamp_min(1e-6)
    gain = gain.clamp(config.minimum_gain, config.maximum_gain)

    b, t, _, height, width = working.shape
    gain = F.interpolate(
        gain.reshape(b * t, 1, *gain.shape[-2:]),
        size=(height, width),
        mode="bilinear",
        align_corners=False,
    ).reshape(b, t, 1, height, width)
    corrected = _linear_to_srgb((linear * gain).clamp(0, 1)).clamp(0, 1)
    corrected = corrected.to(original_dtype)
    return corrected[0] if squeezed else corrected


@torch.no_grad()
def attenuate_saturated_red(
    frames: Tensor,
    config: RedCorrectionConfig,
) -> Tensor:
    """Reduce saturated red chroma while preserving linear-light luminance."""
    config.validate()
    batch, squeezed = _as_batch(frames)
    original_dtype = batch.dtype
    working = batch.float().clamp(0, 1)
    if not config.enabled or config.strength == 0:
        return frames.clone()

    red_ratio = working[:, :, 0:1] / working.sum(dim=2, keepdim=True).clamp_min(1e-6)
    saturation = working.max(dim=2, keepdim=True).values - working.min(
        dim=2, keepdim=True
    ).values
    red_weight = _smooth_weight(
        red_ratio,
        config.red_ratio_threshold,
        config.red_ratio_transition_width,
    )
    saturation_weight = _smooth_weight(
        saturation,
        config.minimum_saturation,
        config.saturation_transition_width,
    )
    mask = red_weight * saturation_weight

    if config.mask_blur_radius > 0:
        radius = config.mask_blur_radius
        b, t, _, height, width = mask.shape
        flat_mask = mask.reshape(b * t, 1, height, width)
        flat_mask = F.pad(flat_mask, (radius, radius, radius, radius), mode="replicate")
        flat_mask = F.avg_pool2d(flat_mask, kernel_size=2 * radius + 1, stride=1)
        mask = flat_mask.reshape(b, t, 1, height, width)

    linear = _srgb_to_linear(working)
    luminance = (
        0.2126 * linear[:, :, 0:1]
        + 0.7152 * linear[:, :, 1:2]
        + 0.0722 * linear[:, :, 2:3]
    )
    neutral = luminance.expand_as(linear)
    corrected_linear = torch.lerp(linear, neutral, mask * config.strength)
    corrected = _linear_to_srgb(corrected_linear).clamp(0, 1).to(original_dtype)
    return corrected[0] if squeezed else corrected


@torch.no_grad()
def apply_accessibility_corrections(
    frames: Tensor,
    fps: float,
    config: AccessibilityCorrectionConfig,
) -> Tensor:
    """Apply the fixed order: flash consolidation, then red attenuation."""
    config.validate()
    corrected = consolidate_temporal_flashes(frames, fps, config.flash)
    return attenuate_saturated_red(corrected, config.red)
