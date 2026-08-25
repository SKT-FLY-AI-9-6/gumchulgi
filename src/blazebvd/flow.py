from __future__ import annotations

from abc import ABC, abstractmethod

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from torch import Tensor, nn


def backward_warp(source: Tensor, target_to_source_flow: Tensor) -> Tensor:
    """Sample ``source`` at coordinates given for every target pixel.

    ``target_to_source_flow[:,0]`` is horizontal displacement in pixels and
    ``[:,1]`` is vertical displacement. This explicit convention avoids the
    common RAFT forward-flow / grid_sample backward-warp mismatch.
    """
    if source.ndim != 4 or target_to_source_flow.ndim != 4:
        raise ValueError("source and flow must be NCHW tensors")
    n, _, h, w = source.shape
    if target_to_source_flow.shape != (n, 2, h, w):
        raise ValueError("flow must have shape [N,2,H,W] matching source")
    y, x = torch.meshgrid(
        torch.arange(h, device=source.device, dtype=source.dtype),
        torch.arange(w, device=source.device, dtype=source.dtype),
        indexing="ij",
    )
    x = x[None] + target_to_source_flow[:, 0]
    y = y[None] + target_to_source_flow[:, 1]
    if w > 1:
        x = 2.0 * x / (w - 1) - 1.0
    else:
        x = torch.zeros_like(x)
    if h > 1:
        y = 2.0 * y / (h - 1) - 1.0
    else:
        y = torch.zeros_like(y)
    grid = torch.stack((x, y), dim=-1)
    return F.grid_sample(source, grid, mode="bilinear", padding_mode="border", align_corners=True)


def flow_valid_mask(flow: Tensor) -> Tensor:
    """Return 1 where target-to-source coordinates stay inside the image."""
    _, _, h, w = flow.shape
    y, x = torch.meshgrid(
        torch.arange(h, device=flow.device, dtype=flow.dtype),
        torch.arange(w, device=flow.device, dtype=flow.dtype),
        indexing="ij",
    )
    sx = x[None] + flow[:, 0]
    sy = y[None] + flow[:, 1]
    return ((sx >= 0) & (sx <= w - 1) & (sy >= 0) & (sy <= h - 1)).unsqueeze(1).to(flow)


class FlowEstimator(ABC, nn.Module):
    @abstractmethod
    def forward(self, target: Tensor, source: Tensor) -> Tensor:
        """Estimate target-to-source flow, shape [N,2,H,W]."""


class ZeroFlow(FlowEstimator):
    def forward(self, target: Tensor, source: Tensor) -> Tensor:
        del source
        return target.new_zeros(target.shape[0], 2, target.shape[-2], target.shape[-1])


class FarnebackFlow(FlowEstimator):
    """CPU fallback for smoke tests; not the RAFT model used by the paper."""

    @torch.no_grad()
    def forward(self, target: Tensor, source: Tensor) -> Tensor:
        device, dtype = target.device, target.dtype
        outputs: list[Tensor] = []
        for target_i, source_i in zip(target, source):
            t = target_i.detach().float().cpu().permute(1, 2, 0).numpy()
            s = source_i.detach().float().cpu().permute(1, 2, 0).numpy()
            t_gray = cv2.cvtColor(np.clip(t * 255, 0, 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
            s_gray = cv2.cvtColor(np.clip(s * 255, 0, 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
            flow = cv2.calcOpticalFlowFarneback(
                t_gray, s_gray, None, 0.5, 3, 15, 3, 5, 1.2, 0
            )
            outputs.append(torch.from_numpy(flow).permute(2, 0, 1))
        return torch.stack(outputs).to(device=device, dtype=dtype)


class TorchvisionRAFT(FlowEstimator):
    """RAFT-small/large adapter using torchvision's official pretrained weights."""

    def __init__(self, variant: str = "small", pretrained: bool = True):
        super().__init__()
        try:
            from torchvision.models.optical_flow import (
                Raft_Large_Weights,
                Raft_Small_Weights,
                raft_large,
                raft_small,
            )
        except ImportError as exc:
            raise RuntimeError("torchvision with optical-flow models is required for RAFT") from exc
        if variant == "small":
            weights = Raft_Small_Weights.DEFAULT if pretrained else None
            self.model = raft_small(weights=weights, progress=True)
        elif variant == "large":
            weights = Raft_Large_Weights.DEFAULT if pretrained else None
            self.model = raft_large(weights=weights, progress=True)
        else:
            raise ValueError(f"Unknown RAFT variant: {variant}")
        self.model.eval()
        for parameter in self.model.parameters():
            parameter.requires_grad_(False)

    @torch.no_grad()
    def forward(self, target: Tensor, source: Tensor) -> Tensor:
        original_size = target.shape[-2:]
        pad_h = (-original_size[0]) % 8
        pad_w = (-original_size[1]) % 8
        target_pad = F.pad(target, (0, pad_w, 0, pad_h), mode="replicate")
        source_pad = F.pad(source, (0, pad_w, 0, pad_h), mode="replicate")
        # Torchvision RAFT expects float images in [-1, 1].
        predictions = self.model(target_pad * 2 - 1, source_pad * 2 - 1)
        return predictions[-1][..., : original_size[0], : original_size[1]]


def build_flow_estimator(backend: str, pretrained: bool = True) -> FlowEstimator:
    if backend == "zero":
        return ZeroFlow()
    if backend == "farneback":
        return FarnebackFlow()
    if backend == "raft_small":
        return TorchvisionRAFT("small", pretrained=pretrained)
    if backend == "raft_large":
        return TorchvisionRAFT("large", pretrained=pretrained)
    raise ValueError(f"Unknown flow backend: {backend}")


@torch.no_grad()
def adjacent_flows(frames: Tensor, estimator: FlowEstimator) -> tuple[Tensor, Tensor]:
    """Compute current-to-previous and current-to-next flows for a video batch."""
    b, t, c, h, w = frames.shape
    if t < 2:
        empty = frames.new_empty(b, 0, 2, h, w)
        return empty, empty
    current = frames[:, 1:].reshape(-1, c, h, w)
    previous = frames[:, :-1].reshape(-1, c, h, w)
    to_prev = estimator(current, previous).reshape(b, t - 1, 2, h, w)
    to_next = estimator(previous, current).reshape(b, t - 1, 2, h, w)
    return to_prev, to_next
