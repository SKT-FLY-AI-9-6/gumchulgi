from __future__ import annotations

import torch
from torch import Tensor, nn

from ..flow import backward_warp
from .blocks import ConvAct, WindowTransformerBlock


class GatedAggregation(nn.Module):
    """Fuse a propagated 16-channel state with a current 16-channel feature."""

    def __init__(self):
        super().__init__()
        # Supplement: conv x3, 32 -> 8 -> 4 -> 1.
        self.gate = nn.Sequential(
            ConvAct(32, 8),
            ConvAct(8, 4),
            nn.Conv2d(4, 1, 3, padding=1),
            nn.Sigmoid(),
        )

    def forward(self, state: Tensor, current: Tensor, is_head: bool = False) -> Tensor:
        if is_head:
            return current
        gate = self.gate(torch.cat((state, current), dim=1))
        return gate * state + (1 - gate) * current


class SpatialRestorer(nn.Module):
    """16->64, eight transformer blocks, then 64->16 (supplement Table 1)."""

    def __init__(self, blocks: int = 8, heads: int = 4, window_size: int = 8):
        super().__init__()
        self.in_conv = nn.Sequential(ConvAct(16, 32), ConvAct(32, 64))
        self.transformers = nn.Sequential(
            *[WindowTransformerBlock(64, heads, window_size) for _ in range(blocks)]
        )
        self.out_conv = nn.Sequential(ConvAct(64, 32), ConvAct(32, 16))

    def forward(self, x: Tensor) -> Tensor:
        return self.out_conv(self.transformers(self.in_conv(x)))


class TemporalConsistencyModel(nn.Module):
    """RTN-derived bidirectional recurrent transformer used in Stage 3."""

    def __init__(self, blocks: int = 8, heads: int = 4, window_size: int = 8):
        super().__init__()
        self.frame_projection = nn.Conv2d(3, 16, 3, padding=1)
        self.forward_gate = GatedAggregation()
        self.backward_gate = GatedAggregation()
        self.forward_restorer = SpatialRestorer(blocks, heads, window_size)
        self.backward_restorer = SpatialRestorer(blocks, heads, window_size)
        # Supplement: conv x3, 32 -> 16 -> 16 -> 3.
        self.reconstruction = nn.Sequential(
            ConvAct(32, 16),
            ConvAct(16, 16),
            nn.Conv2d(16, 3, 3, padding=1),
        )

    def forward(
        self,
        frames: Tensor,
        flow_to_previous: Tensor,
        flow_to_next: Tensor,
    ) -> Tensor:
        b, t, _, h, w = frames.shape
        projected = [self.frame_projection(frames[:, i]) for i in range(t)]

        backward_states: list[Tensor] = [projected[0]] * t
        state = frames.new_zeros(b, 16, h, w)
        for i in range(t - 1, -1, -1):
            if i < t - 1:
                state = backward_warp(state, flow_to_next[:, i])
            state = self.backward_gate(state, projected[i], is_head=i == t - 1)
            state = self.backward_restorer(state)
            backward_states[i] = state

        outputs: list[Tensor] = []
        state = frames.new_zeros(b, 16, h, w)
        for i in range(t):
            if i > 0:
                state = backward_warp(state, flow_to_previous[:, i - 1])
            state = self.forward_gate(state, projected[i], is_head=i == 0)
            state = self.forward_restorer(state)
            residual = self.reconstruction(torch.cat((backward_states[i], state), dim=1))
            outputs.append((frames[:, i] + residual).clamp(0, 1))
        return torch.stack(outputs, dim=1)

