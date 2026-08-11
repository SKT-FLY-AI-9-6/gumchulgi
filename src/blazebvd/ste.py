from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn.functional as F
from torch import Tensor

from .config import FlashCorrectionConfig, STEConfig
from .correction import consolidate_temporal_flashes


@dataclass
class DeflickerPriors:
    """Outputs of BlazeBVD Stage 1.

    Shapes are ``[B,T,...]``. ``singular_frames`` is boolean and exposure maps
    contain 0/1 values. All intensity-domain values are normalized to [0, 1].
    """

    filtered_value: Tensor
    original_histograms: Tensor
    filtered_histograms: Tensor
    exposure_maps: Tensor
    singular_frames: Tensor
    kl_divergence: Tensor
    singular_threshold: Tensor


def rgb_value(frames: Tensor) -> Tensor:
    if frames.ndim != 5 or frames.shape[2] != 3:
        raise ValueError("frames must have shape [B,T,3,H,W]")
    return frames.max(dim=2, keepdim=True).values


def normalized_histograms(values: Tensor, bins: int = 256) -> Tensor:
    """Compute a normalized hard histogram for every ``[B,T]`` map."""
    if values.ndim == 5:
        values = values[:, :, 0]
    if values.ndim != 4:
        raise ValueError("values must be [B,T,1,H,W] or [B,T,H,W]")
    indices = (values.clamp(0, 1) * (bins - 1)).round().long()
    b, t, _, _ = indices.shape
    flat = indices.reshape(b * t, -1)
    hist = torch.zeros(b * t, bins, device=values.device, dtype=values.dtype)
    hist.scatter_add_(1, flat, torch.ones_like(flat, dtype=values.dtype))
    hist /= flat.shape[1]
    return hist.reshape(b, t, bins)


def _quantile_mapping(source_hist: Tensor, target_hist: Tensor) -> Tensor:
    """Return Q(lambda; source, target) for all discrete intensity bins."""
    source_cdf = source_hist.cumsum(dim=-1)
    target_cdf = target_hist.cumsum(dim=-1).contiguous()
    # searchsorted supports batched sorted sequences with matching leading dims.
    mapping = torch.searchsorted(target_cdf, source_cdf, right=False)
    return mapping.clamp_max(source_hist.shape[-1] - 1)


def scale_time_mapping(
    source_histogram: Tensor,
    neighboring_histograms: Tensor,
    offsets: Tensor,
    gaussian_scale: float,
) -> Tensor:
    """Compute one frame's Gaussian-weighted STE quantile mapping.

    ``source_histogram`` has shape ``[B,bins]`` and
    ``neighboring_histograms`` has shape ``[B,N,bins]``. Keeping this operation
    independent from pixel tensors lets long videos load only a small temporal
    histogram window while frames themselves are streamed from disk.
    """
    if source_histogram.ndim != 2 or neighboring_histograms.ndim != 3:
        raise ValueError("Expected source [B,bins] and neighbors [B,N,bins]")
    if offsets.ndim != 1 or offsets.shape[0] != neighboring_histograms.shape[1]:
        raise ValueError("offsets must contain one value per neighboring histogram")
    if source_histogram.shape[0] != neighboring_histograms.shape[0]:
        raise ValueError("source and neighboring histograms must have the same batch size")
    if source_histogram.shape[-1] != neighboring_histograms.shape[-1]:
        raise ValueError("source and neighboring histograms must use the same bins")

    offsets = offsets.to(device=source_histogram.device, dtype=source_histogram.dtype)
    weights = torch.exp(-(offsets.square()) / (4.0 * gaussian_scale))
    weights /= weights.sum()
    source = source_histogram[:, None].expand(-1, neighboring_histograms.shape[1], -1)
    mappings = _quantile_mapping(source, neighboring_histograms).to(source_histogram.dtype)
    return (mappings * weights[None, :, None]).sum(dim=1)


def compress_bright_values(
    original_value: Tensor,
    filtered_value: Tensor,
    bright_threshold: float,
    compression_ratio: float,
) -> Tensor:
    """Force every over-threshold pixel through continuous highlight compression.

    This is a pixel-wise rule: it does not depend on how much of the frame is
    bright. At the threshold the ceiling is continuous, and at V=1 the ceiling
    is ``threshold + ratio * (1 - threshold)``. A negative ratio makes the
    ceiling decrease as the source becomes brighter. The ceiling is clamped to
    the valid value range, and the STE result is kept whenever it is already
    darker than that ceiling.
    """
    if original_value.shape != filtered_value.shape:
        raise ValueError("original_value and filtered_value must have the same shape")
    ceiling = (
        bright_threshold
        + compression_ratio * (original_value - bright_threshold)
    ).clamp(0.0, 1.0)
    compressed = torch.minimum(filtered_value, ceiling)
    return torch.where(original_value > bright_threshold, compressed, filtered_value)


def temporal_median(values: Tensor, radius: int) -> Tensor:
    """Return a per-pixel centered temporal median with replicated boundaries."""
    if values.ndim != 5 or values.shape[2] != 1:
        raise ValueError("values must have shape [B,T,1,H,W]")
    if radius < 0:
        raise ValueError("radius must be non-negative")
    if radius == 0 or values.shape[1] == 1:
        return values.clone()

    # F.pad applies temporal padding to [B,C,T,H,W] when given six values.
    channel_first = values.permute(0, 2, 1, 3, 4)
    padded = F.pad(
        channel_first,
        (0, 0, 0, 0, radius, radius),
        mode="replicate",
    )
    windows = padded.unfold(2, 2 * radius + 1, 1)
    reference = windows.median(dim=-1).values
    return reference.permute(0, 2, 1, 3, 4)


def limit_temporal_deviation(
    filtered_value: Tensor,
    reference: Tensor,
    contrast_threshold: float,
    max_temporal_deviation: float,
    blend_strength: float,
) -> Tensor:
    """Pull temporal outliers toward a reference without changing other pixels."""
    if filtered_value.shape != reference.shape:
        raise ValueError("filtered_value and reference must have the same shape")

    deviation = filtered_value - reference
    transient_mask = deviation.abs() >= contrast_threshold
    limited = reference + deviation.clamp(
        min=-max_temporal_deviation,
        max=max_temporal_deviation,
    )
    strength = transient_mask.to(filtered_value.dtype) * blend_strength
    return filtered_value * (1.0 - strength) + limited * strength


def suppress_temporal_flashes(
    filtered_value: Tensor,
    temporal_radius: int = 2,
    contrast_threshold: float = 0.10,
    max_temporal_deviation: float = 0.10,
    blend_strength: float = 1.0,
) -> Tensor:
    """Suppress local V-channel impulses relative to a temporal median.

    The decision is pixel-wise and does not use the fraction of the frame that
    changes. A one-pixel flash and a full-frame flash therefore follow the same
    contrast/deviation rule.
    """
    reference = temporal_median(filtered_value, temporal_radius)
    return limit_temporal_deviation(
        filtered_value,
        reference,
        contrast_threshold,
        max_temporal_deviation,
        blend_strength,
    )


def moving_average(values: Tensor, radius: int) -> Tensor:
    """Centered moving average with truncated boundary windows."""
    if values.ndim != 2:
        raise ValueError("values must have shape [B,T]")
    output = torch.empty_like(values)
    for center in range(values.shape[1]):
        lo = max(0, center - radius)
        hi = min(values.shape[1], center + radius + 1)
        output[:, center] = values[:, lo:hi].mean(dim=1)
    return output


class ScaleTimeEqualization:
    """Equation (3)-(6) in BlazeBVD, applied only in HSV illumination space."""

    def __init__(self, config: STEConfig | None = None):
        self.config = config or STEConfig()
        self.config.validate()

    @torch.no_grad()
    def __call__(
        self,
        frames: Tensor,
        fps: float = 30.0,
        flash_config: FlashCorrectionConfig | None = None,
        frame_offset: int = 0,
    ) -> DeflickerPriors:
        cfg = self.config
        working_frames = frames.float().clamp(0, 1)
        value = rgb_value(working_frames)
        hist = normalized_histograms(value, cfg.bins)
        b, t, _ = hist.shape
        mappings = torch.empty(b, t, cfg.bins, device=frames.device, dtype=frames.dtype)

        for center in range(t):
            lo = max(0, center - cfg.window_radius)
            hi = min(t, center + cfg.window_radius + 1)
            offsets = torch.arange(lo, hi, device=frames.device, dtype=frames.dtype) - center
            mappings[:, center] = scale_time_mapping(
                hist[:, center], hist[:, lo:hi], offsets, cfg.gaussian_scale
            )

        value_bins = (value[:, :, 0] * (cfg.bins - 1)).round().long()
        filtered = torch.gather(
            mappings.reshape(b * t, cfg.bins),
            1,
            value_bins.reshape(b * t, -1),
        ).reshape_as(value_bins)
        filtered = filtered.to(frames.dtype).div(cfg.bins - 1).unsqueeze(2)
        filtered = compress_bright_values(
            value,
            filtered,
            cfg.bright_threshold,
            cfg.bright_compression_ratio,
        )
        if cfg.temporal_flash_suppression:
            filtered = suppress_temporal_flashes(
                filtered,
                temporal_radius=cfg.temporal_radius,
                contrast_threshold=cfg.flash_contrast_threshold,
                max_temporal_deviation=cfg.max_temporal_deviation,
                blend_strength=cfg.flash_suppression_strength,
            )

        # Flash consolidation belongs to the STE brightness stage. Reconstruct
        # an RGB view of the STE result, merge short luminance states, and feed
        # its resulting V channel to GFRM as the updated STE prior. No pixels
        # from neighboring frames are copied.
        if flash_config is not None:
            flash_config.validate()
            if flash_config.enabled:
                ste_scale = filtered / value.clamp_min(1e-6)
                ste_rgb = (working_frames * ste_scale).clamp(0, 1)
                flash_corrected = consolidate_temporal_flashes(
                    ste_rgb,
                    fps,
                    flash_config,
                    frame_offset=frame_offset,
                )
                filtered = rgb_value(flash_corrected).to(frames.dtype)
        filtered_hist = normalized_histograms(filtered, cfg.bins)

        eps = torch.finfo(hist.dtype).eps
        kl = (filtered_hist.clamp_min(eps) * (
            filtered_hist.clamp_min(eps).log() - hist.clamp_min(eps).log()
        )).sum(dim=-1)
        threshold = moving_average(kl, cfg.moving_average_radius)
        singular = kl > threshold
        # Mark exposure from the original pixels. Otherwise a successfully
        # compressed highlight would disappear from the downstream LFRM mask.
        exposure = (
            (value < cfg.dark_threshold) | (value > cfg.bright_threshold)
        ).to(frames.dtype)

        return DeflickerPriors(
            filtered_value=filtered,
            original_histograms=hist,
            filtered_histograms=filtered_hist,
            exposure_maps=exposure,
            singular_frames=singular,
            kl_divergence=kl,
            singular_threshold=threshold,
        )
