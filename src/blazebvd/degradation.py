from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn.functional as F
from torch import Tensor


@dataclass
class FlickerSynthesisConfig:
    min_window: int = 2
    max_window: int = 12
    global_amplitude: float = 0.30
    color_amplitude: float = 0.12
    local_probability: float = 0.5
    local_amplitude: float = 0.45


def synthesize_flicker(
    clean: Tensor,
    config: FlickerSynthesisConfig | None = None,
    generator: torch.Generator | None = None,
) -> tuple[Tensor, Tensor]:
    """Create piecewise-constant additive artifacts F_t for X_t=G_t+F_t.

    The paper discloses only the additive equation and W~Uniform{2,...,12};
    the amplitude distribution and local masks below are explicit replacement
    assumptions intended for ablation, not claimed author settings.
    """
    cfg = config or FlickerSynthesisConfig()
    if clean.ndim != 5:
        raise ValueError("clean must be [B,T,3,H,W]")
    b, t, _, h, w = clean.shape
    artifact = torch.zeros_like(clean)
    for batch in range(b):
        index = 0
        while index < t:
            width = int(torch.randint(
                cfg.min_window, cfg.max_window + 1, (1,), generator=generator
            ).item())
            end = min(t, index + width)
            global_shift = (
                torch.rand(1, generator=generator).item() * 2 - 1
            ) * cfg.global_amplitude
            color = torch.randn(3, generator=generator)
            color = color / color.abs().amax().clamp_min(1e-6) * cfg.color_amplitude
            shift = clean.new_tensor(global_shift) + color.to(clean)[..., None, None]
            artifact[batch, index:end] = shift

            if torch.rand(1, generator=generator).item() < cfg.local_probability:
                low_h, low_w = max(2, h // 16), max(2, w // 16)
                mask = torch.rand(1, 1, low_h, low_w, generator=generator)
                mask = F.interpolate(mask, size=(h, w), mode="bicubic", align_corners=False)
                threshold = 0.55 + 0.25 * torch.rand(1, generator=generator).item()
                mask = ((mask - threshold) * 8).sigmoid().to(clean)
                local_sign = 1 if torch.rand(1, generator=generator).item() > 0.5 else -1
                artifact[batch, index:end] += local_sign * cfg.local_amplitude * mask
            index = end
    return (clean + artifact).clamp(0, 1), artifact

