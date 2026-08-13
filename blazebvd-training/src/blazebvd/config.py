from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class STEConfig:
    bins: int = 256
    window_radius: int = 5
    gaussian_scale: float = 3.0
    moving_average_radius: int = 3
    dark_threshold: float = 0.05
    bright_threshold: float = 0.80
    bright_compression_ratio: float = -0.25
    temporal_flash_suppression: bool = False
    temporal_radius: int = 3
    flash_contrast_threshold: float = 0.10
    max_temporal_deviation: float = 0.10
    flash_suppression_strength: float = 1.0

    def validate(self) -> None:
        if self.bins < 2:
            raise ValueError("ste.bins must be >= 2")
        if (
            self.window_radius < 0
            or self.moving_average_radius < 0
            or self.temporal_radius < 0
        ):
            raise ValueError("STE radii must be non-negative")
        if self.gaussian_scale <= 0:
            raise ValueError("ste.gaussian_scale must be positive")
        if not 0 <= self.dark_threshold < self.bright_threshold <= 1:
            raise ValueError("Expected 0 <= dark_threshold < bright_threshold <= 1")
        if not -1 <= self.bright_compression_ratio <= 1:
            raise ValueError("ste.bright_compression_ratio must be in [-1, 1]")
        if not 0 <= self.flash_contrast_threshold <= 1:
            raise ValueError("ste.flash_contrast_threshold must be in [0, 1]")
        if not 0 <= self.max_temporal_deviation <= 1:
            raise ValueError("ste.max_temporal_deviation must be in [0, 1]")
        if not 0 <= self.flash_suppression_strength <= 1:
            raise ValueError("ste.flash_suppression_strength must be in [0, 1]")


@dataclass
class FlashCorrectionConfig:
    """Parameters for deterministic temporal flash consolidation.

    This stage does not decide whether a video passes a PSE standard. It always
    processes consecutive temporal blocks when enabled.
    """

    enabled: bool = True
    block_duration_seconds: float = 0.10
    minimum_block_frames: int = 3
    analysis_size: int = 64
    contrast_threshold: float = 0.05
    transition_width: float = 0.05
    strength: float = 1.0
    minimum_gain: float = 0.25
    maximum_gain: float = 3.0
    scene_cut_threshold: float = 1.0

    def validate(self) -> None:
        if self.block_duration_seconds <= 0:
            raise ValueError("correction.flash.block_duration_seconds must be positive")
        if self.minimum_block_frames < 1:
            raise ValueError("correction.flash.minimum_block_frames must be >= 1")
        if self.analysis_size < 1:
            raise ValueError("correction.flash.analysis_size must be >= 1")
        if not 0 <= self.contrast_threshold <= 1:
            raise ValueError("correction.flash.contrast_threshold must be in [0, 1]")
        if not 0 <= self.transition_width <= 1:
            raise ValueError("correction.flash.transition_width must be in [0, 1]")
        if not 0 <= self.strength <= 1:
            raise ValueError("correction.flash.strength must be in [0, 1]")
        if not 0 < self.minimum_gain <= 1:
            raise ValueError("correction.flash.minimum_gain must be in (0, 1]")
        if self.maximum_gain < 1:
            raise ValueError("correction.flash.maximum_gain must be >= 1")
        if not 0 <= self.scene_cut_threshold <= 1:
            raise ValueError("correction.flash.scene_cut_threshold must be in [0, 1]")


@dataclass
class RedCorrectionConfig:
    """Parameters for luminance-preserving saturated-red attenuation."""

    enabled: bool = True
    red_ratio_threshold: float = 0.75
    red_ratio_transition_width: float = 0.10
    minimum_saturation: float = 0.35
    saturation_transition_width: float = 0.10
    strength: float = 0.75
    mask_blur_radius: int = 3

    def validate(self) -> None:
        for name, value in (
            ("red_ratio_threshold", self.red_ratio_threshold),
            ("red_ratio_transition_width", self.red_ratio_transition_width),
            ("minimum_saturation", self.minimum_saturation),
            ("saturation_transition_width", self.saturation_transition_width),
            ("strength", self.strength),
        ):
            if not 0 <= value <= 1:
                raise ValueError(f"correction.red.{name} must be in [0, 1]")
        if self.mask_blur_radius < 0:
            raise ValueError("correction.red.mask_blur_radius must be non-negative")


@dataclass
class AccessibilityCorrectionConfig:
    """STE flash consolidation plus final saturated-red attenuation."""

    flash: FlashCorrectionConfig = field(default_factory=FlashCorrectionConfig)
    red: RedCorrectionConfig = field(default_factory=RedCorrectionConfig)

    def validate(self) -> None:
        self.flash.validate()
        self.red.validate()


@dataclass
class ModelConfig:
    gfrm_output_mode: str = "residual"
    nonlocal_max_positions: int = 1024
    tcm_transformer_blocks: int = 8
    tcm_window_size: int = 8
    tcm_heads: int = 4


@dataclass
class FlowConfig:
    backend: str = "raft_small"
    pretrained: bool = True


@dataclass
class InferenceConfig:
    clip_length: int = 16
    overlap: int = 4
    device: str = "auto"


@dataclass
class BlazeBVDConfig:
    ste: STEConfig = field(default_factory=STEConfig)
    correction: AccessibilityCorrectionConfig = field(
        default_factory=AccessibilityCorrectionConfig
    )
    model: ModelConfig = field(default_factory=ModelConfig)
    flow: FlowConfig = field(default_factory=FlowConfig)
    inference: InferenceConfig = field(default_factory=InferenceConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> BlazeBVDConfig:
        with Path(path).open("r", encoding="utf-8") as stream:
            raw = yaml.safe_load(stream) or {}
        correction_raw = raw.get("correction") or {}
        cfg = cls(
            ste=STEConfig(**raw.get("ste", {})),
            correction=AccessibilityCorrectionConfig(
                flash=FlashCorrectionConfig(**(correction_raw.get("flash") or {})),
                red=RedCorrectionConfig(**(correction_raw.get("red") or {})),
            ),
            model=ModelConfig(**raw.get("model", {})),
            flow=FlowConfig(**raw.get("flow", {})),
            inference=InferenceConfig(**raw.get("inference", {})),
        )
        cfg.ste.validate()
        cfg.correction.validate()
        return cfg

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
