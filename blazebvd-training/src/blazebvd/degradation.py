from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F
import yaml
from torch import Tensor


@dataclass
class FlickerSynthesisConfig:
    """Configuration for synthetic training degradations.

    BlazeBVD discloses the additive model ``X_t = G_t + F_t`` and samples a
    shared temporal window from 2 to 12 frames.  The exact amplitude and mask
    distributions were not published.  The additional fast/global/local/red
    patterns below are explicit replacement assumptions for accessibility
    training; they are not claimed to be the authors' original generator.
    """

    min_window: int = 2
    max_window: int = 12
    global_amplitude: float = 0.30
    color_amplitude: float = 0.12
    local_probability: float = 0.50
    local_amplitude: float = 0.45
    alternating_probability: float = 0.65
    alternating_min_period: int = 1
    alternating_max_period: int = 3
    alternating_amplitude: float = 0.40
    impulse_probability: float = 0.35
    impulse_amplitude: float = 0.50
    red_flash_probability: float = 0.35
    red_flash_amplitude: float = 0.45

    def validate(self) -> None:
        if self.min_window < 1 or self.max_window < self.min_window:
            raise ValueError("Expected 1 <= min_window <= max_window")
        if (
            self.alternating_min_period < 1
            or self.alternating_max_period < self.alternating_min_period
        ):
            raise ValueError(
                "Expected 1 <= alternating_min_period <= alternating_max_period"
            )
        for name in (
            "local_probability",
            "alternating_probability",
            "impulse_probability",
            "red_flash_probability",
        ):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        for name in (
            "global_amplitude",
            "color_amplitude",
            "local_amplitude",
            "alternating_amplitude",
            "impulse_amplitude",
            "red_flash_amplitude",
        ):
            if float(getattr(self, name)) < 0:
                raise ValueError(f"{name} must be non-negative")

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> FlickerSynthesisConfig:
        raw = raw or {}
        known = {field.name for field in fields(cls)}
        unknown = sorted(set(raw) - known)
        if unknown:
            raise ValueError(f"Unknown degradation settings: {', '.join(unknown)}")
        config = cls(**raw)
        config.validate()
        return config


def load_flicker_config(path: str | Path | None) -> FlickerSynthesisConfig:
    if path is None:
        config = FlickerSynthesisConfig()
        config.validate()
        return config
    with Path(path).open("r", encoding="utf-8") as stream:
        raw = yaml.safe_load(stream) or {}
    if "degradation" in raw:
        raw = raw["degradation"] or {}
    if not isinstance(raw, dict):
        raise ValueError("Degradation config must be a YAML mapping")
    return FlickerSynthesisConfig.from_mapping(raw)


def _random_scalar(generator: torch.Generator | None) -> float:
    return float(torch.rand(1, generator=generator).item())


def _random_sign(generator: torch.Generator | None) -> float:
    return 1.0 if _random_scalar(generator) >= 0.5 else -1.0


def _soft_spatial_mask(
    height: int,
    width: int,
    generator: torch.Generator | None,
    reference: Tensor,
) -> Tensor:
    low_h, low_w = max(2, height // 16), max(2, width // 16)
    mask = torch.rand(1, 1, low_h, low_w, generator=generator)
    mask = F.interpolate(mask, size=(height, width), mode="bicubic", align_corners=False)
    threshold = 0.45 + 0.30 * _random_scalar(generator)
    return ((mask - threshold) * 8.0).sigmoid().to(reference)


def synthesize_flicker(
    clean: Tensor,
    config: FlickerSynthesisConfig | None = None,
    generator: torch.Generator | None = None,
) -> tuple[Tensor, Tensor]:
    """Create repeatable global, local, rapid and red additive flicker.

    Args:
        clean: Clean clips with shape ``[B,T,3,H,W]`` in ``[0,1]``.
        config: Synthetic degradation parameters.
        generator: Optional CPU generator used for deterministic samples.

    Returns:
        ``(degraded, actual_artifact)``.  ``actual_artifact`` is measured after
        clipping, so ``degraded == clean + actual_artifact`` up to floating
        point precision and can be used as a reliable training mask.
    """
    cfg = config or FlickerSynthesisConfig()
    cfg.validate()
    if clean.ndim != 5 or clean.shape[2] != 3:
        raise ValueError("clean must be [B,T,3,H,W]")
    b, t, _, h, w = clean.shape
    artifact = torch.zeros_like(clean)

    for batch in range(b):
        # Paper-compatible piecewise-constant additive component.
        index = 0
        while index < t:
            width = int(
                torch.randint(
                    cfg.min_window,
                    cfg.max_window + 1,
                    (1,),
                    generator=generator,
                ).item()
            )
            end = min(t, index + width)
            global_shift = _random_sign(generator) * _random_scalar(
                generator
            ) * cfg.global_amplitude
            color = torch.randn(3, generator=generator)
            color = color / color.abs().amax().clamp_min(1e-6)
            color = color * (_random_scalar(generator) * cfg.color_amplitude)
            shift = clean.new_tensor(global_shift) + color.to(clean)[..., None, None]
            artifact[batch, index:end] += shift

            if _random_scalar(generator) < cfg.local_probability:
                mask = _soft_spatial_mask(h, w, generator, clean)
                local_amplitude = (
                    _random_sign(generator)
                    * _random_scalar(generator)
                    * cfg.local_amplitude
                )
                artifact[batch, index:end] += local_amplitude * mask
            index = end

        # Fast alternating flashes cover 1--3-frame states by default.  This
        # supplements the paper's slower shared-window process with patterns
        # relevant to photosensitivity mitigation.
        if t > 1 and _random_scalar(generator) < cfg.alternating_probability:
            period = int(
                torch.randint(
                    cfg.alternating_min_period,
                    cfg.alternating_max_period + 1,
                    (1,),
                    generator=generator,
                ).item()
            )
            phase = int(torch.randint(0, max(period * 2, 1), (1,), generator=generator))
            amplitude = (0.5 + 0.5 * _random_scalar(generator)) * cfg.alternating_amplitude
            states = torch.arange(t)
            states = (((states + phase) // period) % 2).float()
            # A small negative low state increases contrast without forcing
            # every sample into clipping.
            states = states * amplitude - (1.0 - states) * (0.20 * amplitude)
            flash = states.to(clean)[:, None, None, None]
            if _random_scalar(generator) < cfg.local_probability:
                flash = flash * _soft_spatial_mask(h, w, generator, clean)
            artifact[batch] += flash

        # One- or two-frame impulses exercise STE highlight and temporal-limit
        # behaviour even when the random windows happen to be long.
        if _random_scalar(generator) < cfg.impulse_probability:
            start = int(torch.randint(0, t, (1,), generator=generator).item())
            duration = min(t - start, 1 + int(_random_scalar(generator) > 0.7))
            amplitude = _random_sign(generator) * (
                0.5 + 0.5 * _random_scalar(generator)
            ) * cfg.impulse_amplitude
            impulse = clean.new_tensor(amplitude)
            if _random_scalar(generator) < cfg.local_probability:
                impulse = impulse * _soft_spatial_mask(h, w, generator, clean)
            artifact[batch, start : start + duration] += impulse

        # Saturated-red temporal changes are explicitly represented because a
        # grayscale-only generator does not teach the neural stages to retain
        # texture under red concert/stage lighting.
        if t > 1 and _random_scalar(generator) < cfg.red_flash_probability:
            period = int(
                torch.randint(
                    cfg.alternating_min_period,
                    cfg.alternating_max_period + 1,
                    (1,),
                    generator=generator,
                ).item()
            )
            red_states = ((torch.arange(t) // period) % 2).to(clean)
            red_amplitude = (
                0.5 + 0.5 * _random_scalar(generator)
            ) * cfg.red_flash_amplitude
            red_flash = clean.new_zeros(t, 3, 1, 1)
            red_flash[:, 0] = red_states[:, None, None] * red_amplitude
            red_flash[:, 1:] = -red_states[:, None, None, None] * (0.10 * red_amplitude)
            if _random_scalar(generator) < cfg.local_probability:
                red_flash = red_flash * _soft_spatial_mask(h, w, generator, clean)
            artifact[batch] += red_flash

    degraded = (clean + artifact).clamp(0, 1)
    return degraded, degraded - clean
