from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import torch
import yaml
from torch import Tensor

from .degradation import FlickerSynthesisConfig
from .ste import DeflickerPriors, rgb_value


@dataclass
class TrainingLossConfig:
    temporal_excess_weight: float = 0.10
    rebound_weight: float = 0.10
    temporal_margin: float = 0.02
    rebound_margin: float = 0.02
    lfrm_artifact_threshold: float = 0.03
    lfrm_artifact_boost: float = 4.0
    reconstruction_weight: float = 1.0
    perceptual_weight: float = 1.0
    adversarial_weight: float = 0.01
    warp_weight: float = 0.10

    def validate(self) -> None:
        for field in fields(self):
            value = float(getattr(self, field.name))
            if value < 0:
                raise ValueError(f"loss.{field.name} must be non-negative")

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> TrainingLossConfig:
        raw = raw or {}
        known = {field.name for field in fields(cls)}
        unknown = sorted(set(raw) - known)
        if unknown:
            raise ValueError(f"Unknown loss settings: {', '.join(unknown)}")
        config = cls(**raw)
        config.validate()
        return config


@dataclass
class TrainingRecipe:
    degradation: FlickerSynthesisConfig
    loss: TrainingLossConfig

    @classmethod
    def from_yaml(cls, path: str | Path | None) -> TrainingRecipe:
        if path is None:
            return cls(FlickerSynthesisConfig(), TrainingLossConfig())
        with Path(path).open("r", encoding="utf-8") as stream:
            raw = yaml.safe_load(stream) or {}
        if not isinstance(raw, dict):
            raise ValueError("Training recipe must be a YAML mapping")
        known_sections = {"degradation", "loss"}
        unknown = sorted(set(raw) - known_sections)
        if unknown:
            raise ValueError(f"Unknown training recipe sections: {', '.join(unknown)}")
        return cls(
            degradation=FlickerSynthesisConfig.from_mapping(raw.get("degradation")),
            loss=TrainingLossConfig.from_mapping(raw.get("loss")),
        )


def ste_rgb_reference(frames: Tensor, priors: DeflickerPriors) -> Tensor:
    """Reconstruct the RGB image implied by STE's filtered V prior."""
    if frames.ndim != 5 or frames.shape[2] != 3:
        raise ValueError("frames must have shape [B,T,3,H,W]")
    if priors.filtered_value.shape != frames.shape[:2] + (1,) + frames.shape[-2:]:
        raise ValueError("STE filtered_value shape does not match frames")
    value = rgb_value(frames)
    scale = priors.filtered_value / value.clamp_min(1e-6)
    return (frames * scale).clamp(0, 1)


def synthetic_lfrm_masks(
    artifact: Tensor,
    priors: DeflickerPriors,
    threshold: float = 0.03,
) -> tuple[Tensor, Tensor]:
    """Build oracle training masks from known synthetic corruption.

    These masks are used only while learning LFRM.  Inference continues to use
    STE's exposure and singular-frame decisions.
    """
    if artifact.ndim != 5 or artifact.shape[2] != 3:
        raise ValueError("artifact must have shape [B,T,3,H,W]")
    spatial = artifact.abs().amax(dim=2, keepdim=True) > float(threshold)
    if spatial.shape != priors.exposure_maps.shape:
        raise ValueError("artifact and STE priors must share batch/time/spatial shapes")
    exposure = torch.maximum(
        priors.exposure_maps,
        spatial.to(priors.exposure_maps),
    )
    active = spatial.flatten(2).any(dim=2)
    return exposure, active
