from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import Tensor, nn

from ..config import BlazeBVDConfig
from ..flow import FlowEstimator, adjacent_flows, build_flow_estimator
from ..ste import DeflickerPriors, ScaleTimeEqualization
from .gfrm import GlobalFlickerRemovalModule
from .lfrm import LocalFlickerRemovalModule
from .tcm import TemporalConsistencyModel


@dataclass
class BlazeBVDOutput:
    output: Tensor
    stage2_global: Tensor
    stage2_local: Tensor
    priors: DeflickerPriors
    flow_to_previous: Tensor
    flow_to_next: Tensor


class BlazeBVD(nn.Module):
    """Complete Stage 1 -> GFRM -> LFRM -> TCM pipeline."""

    def __init__(
        self,
        config: BlazeBVDConfig | None = None,
        flow_estimator: FlowEstimator | None = None,
    ):
        super().__init__()
        self.config = config or BlazeBVDConfig()
        self.ste = ScaleTimeEqualization(self.config.ste)
        self.gfrm = GlobalFlickerRemovalModule(self.config.model.gfrm_output_mode)
        self.lfrm = LocalFlickerRemovalModule(self.config.model.nonlocal_max_positions)
        self.tcm = TemporalConsistencyModel(
            self.config.model.tcm_transformer_blocks,
            self.config.model.tcm_heads,
            self.config.model.tcm_window_size,
        )
        self.flow_estimator = flow_estimator or build_flow_estimator(
            self.config.flow.backend, self.config.flow.pretrained
        )

    def global_stage(self, frames: Tensor, priors: DeflickerPriors) -> Tensor:
        b, t, c, h, w = frames.shape
        corrected = self.gfrm(
            frames.reshape(b * t, c, h, w),
            priors.filtered_value.reshape(b * t, 1, h, w),
        )
        return corrected.reshape(b, t, c, h, w)

    def forward(
        self,
        frames: Tensor,
        run_tcm: bool = True,
        fps: float = 30.0,
        frame_offset: int = 0,
        priors: DeflickerPriors | None = None,
    ) -> BlazeBVDOutput:
        """Run the pipeline.

        ``priors`` may be precomputed over a longer video and sliced to exactly
        this clip's time range; STE is then skipped so clip windows never
        truncate the temporal histogram context.
        """
        if frames.ndim != 5 or frames.shape[2] != 3:
            raise ValueError("frames must be [B,T,3,H,W]")
        frames = frames.float().clamp(0, 1)
        if priors is None:
            priors = self.ste(
                frames,
                fps=fps,
                flash_config=self.config.correction.flash,
                frame_offset=frame_offset,
            )
        elif priors.filtered_value.shape[:2] != frames.shape[:2]:
            raise ValueError("priors must cover exactly the frames' batch/time range")
        global_corrected = self.global_stage(frames, priors)
        flow_to_previous, flow_to_next = adjacent_flows(frames, self.flow_estimator)
        local_corrected = self.lfrm.refine_sequence(
            global_corrected,
            priors.exposure_maps,
            priors.singular_frames,
            flow_to_previous,
            flow_to_next,
        )
        output = (
            self.tcm(local_corrected, flow_to_previous, flow_to_next)
            if run_tcm and frames.shape[1] > 1
            else local_corrected
        )
        return BlazeBVDOutput(
            output=output,
            stage2_global=global_corrected,
            stage2_local=local_corrected,
            priors=priors,
            flow_to_previous=flow_to_previous,
            flow_to_next=flow_to_next,
        )

    def load_checkpoint(self, path: str, strict: bool = True) -> dict:
        checkpoint = torch.load(path, map_location="cpu", weights_only=False)
        state_dict = checkpoint.get("model", checkpoint.get("state_dict", checkpoint))
        self.load_state_dict(state_dict, strict=strict)
        return checkpoint
