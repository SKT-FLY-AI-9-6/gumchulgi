from __future__ import annotations

import torch
from torch import Tensor, nn

from ..flow import backward_warp
from .blocks import ConvAct, MemorySafeNonLocal2D


class LocalFlickerRemovalModule(nn.Module):
    """9->32 fusion network with two non-local blocks (paper supplement)."""

    def __init__(self, max_positions: int = 1024):
        super().__init__()
        self.conv1 = ConvAct(9, 32)
        self.conv2 = ConvAct(32, 32)
        self.nonlocal1 = MemorySafeNonLocal2D(32, 32, max_positions=max_positions)
        self.projection = nn.Sequential(nn.Conv2d(32, 32, 1), nn.LeakyReLU(0.1, True))
        self.nonlocal2 = MemorySafeNonLocal2D(
            32, 3, max_positions=max_positions, residual=False
        )

    def forward(self, previous: Tensor, current: Tensor, following: Tensor) -> Tensor:
        x = torch.cat((previous, current, following), dim=1)
        x = self.nonlocal1(self.conv2(self.conv1(x)))
        residual = self.nonlocal2(self.projection(x))
        return (current + residual).clamp(0, 1)

    def refine_sequence(
        self,
        corrected: Tensor,
        exposure_maps: Tensor,
        singular_frames: Tensor,
        flow_to_previous: Tensor,
        flow_to_next: Tensor,
        active_frames: Tensor | None = None,
        force_all: bool = False,
    ) -> Tensor:
        """Refine selected interior frames.

        Inference uses ``singular_frames`` from STE.  Synthetic training may
        pass ground-truth ``active_frames`` or ``force_all=True`` so a batch in
        which STE detects no singular frame still exercises LFRM and produces
        a valid gradient.  Boundary frames remain unchanged because LFRM needs
        both a previous and following frame.
        """
        b, t, _, h, w = corrected.shape
        if exposure_maps.shape != (b, t, 1, h, w):
            raise ValueError("exposure_maps must have shape [B,T,1,H,W]")
        if singular_frames.shape != (b, t):
            raise ValueError("singular_frames must have shape [B,T]")
        if active_frames is not None and active_frames.shape != (b, t):
            raise ValueError("active_frames must have shape [B,T]")
        selected_frames = active_frames if active_frames is not None else singular_frames
        selected_frames = selected_frames.bool()
        if force_all:
            selected_frames = torch.ones_like(selected_frames)

        outputs = [corrected[:, i] for i in range(t)]
        for i in range(1, t - 1):
            active = selected_frames[:, i]
            if not bool(active.any()):
                continue
            mask = exposure_maps[:, i]
            warped_previous = backward_warp(corrected[:, i - 1], flow_to_previous[:, i - 1])
            warped_following = backward_warp(corrected[:, i + 1], flow_to_next[:, i])
            previous_branch = mask * warped_previous + (1 - mask) * corrected[:, i]
            following_branch = mask * warped_following + (1 - mask) * corrected[:, i]
            refined = self(previous_branch, corrected[:, i], following_branch)
            active_map = active[:, None, None, None]
            outputs[i] = torch.where(active_map, refined, corrected[:, i])
        return torch.stack(outputs, dim=1)
