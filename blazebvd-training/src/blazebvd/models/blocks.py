from __future__ import annotations

import math

import torch
import torch.nn.functional as F
from torch import Tensor, nn


class ConvAct(nn.Sequential):
    def __init__(self, in_channels: int, out_channels: int, kernel_size: int = 3):
        super().__init__(
            nn.Conv2d(in_channels, out_channels, kernel_size, padding=kernel_size // 2),
            nn.LeakyReLU(0.1, inplace=True),
        )


class MemorySafeNonLocal2D(nn.Module):
    """Embedded-Gaussian non-local block with pooled keys and chunked queries."""

    def __init__(
        self,
        in_channels: int,
        out_channels: int | None = None,
        max_positions: int = 1024,
        query_chunk: int = 2048,
        residual: bool = True,
    ):
        super().__init__()
        out_channels = out_channels or in_channels
        inter = max(1, in_channels // 2)
        self.theta = nn.Conv2d(in_channels, inter, 1, bias=False)
        self.phi = nn.Conv2d(in_channels, inter, 1, bias=False)
        self.g = nn.Conv2d(in_channels, inter, 1, bias=False)
        self.project = nn.Conv2d(inter, out_channels, 1)
        self.max_positions = max_positions
        self.query_chunk = query_chunk
        self.use_residual = residual and in_channels == out_channels
        if self.use_residual:
            nn.init.zeros_(self.project.weight)
            nn.init.zeros_(self.project.bias)

    def forward(self, x: Tensor) -> Tensor:
        n, _, h, w = x.shape
        kv = x
        if h * w > self.max_positions:
            side = max(1, int(math.sqrt(self.max_positions)))
            kv = F.adaptive_avg_pool2d(x, (min(h, side), min(w, side)))
        q = self.theta(x).flatten(2).transpose(1, 2)
        k = self.phi(kv).flatten(2)
        v = self.g(kv).flatten(2).transpose(1, 2)
        scale = q.shape[-1] ** -0.5
        parts = []
        for start in range(0, q.shape[1], self.query_chunk):
            attention = torch.softmax((q[:, start : start + self.query_chunk] @ k) * scale, -1)
            parts.append(attention @ v)
        y = torch.cat(parts, dim=1).transpose(1, 2).reshape(n, -1, h, w)
        y = self.project(y)
        return x + y if self.use_residual else y


def _window_partition(x: Tensor, window: int) -> tuple[Tensor, tuple[int, int]]:
    n, c, h, w = x.shape
    pad_h, pad_w = (-h) % window, (-w) % window
    x = F.pad(x, (0, pad_w, 0, pad_h), mode="reflect")
    hp, wp = x.shape[-2:]
    x = x.reshape(n, c, hp // window, window, wp // window, window)
    x = x.permute(0, 2, 4, 3, 5, 1).reshape(-1, window * window, c)
    return x, (pad_h, pad_w)


def _window_reverse(
    tokens: Tensor,
    window: int,
    shape: tuple[int, int, int, int],
    pad: tuple[int, int],
) -> Tensor:
    n, c, h, w = shape
    pad_h, pad_w = pad
    hp, wp = h + pad_h, w + pad_w
    x = tokens.reshape(n, hp // window, wp // window, window, window, c)
    x = x.permute(0, 5, 1, 3, 2, 4).reshape(n, c, hp, wp)
    return x[..., :h, :w]


class WindowTransformerBlock(nn.Module):
    """A compact Swin-style spatial block used for the RTN-derived TCM."""

    def __init__(self, channels: int = 64, heads: int = 4, window_size: int = 8):
        super().__init__()
        self.window_size = window_size
        self.norm1 = nn.LayerNorm(channels)
        self.attn = nn.MultiheadAttention(channels, heads, batch_first=True)
        self.norm2 = nn.LayerNorm(channels)
        self.mlp = nn.Sequential(
            nn.Linear(channels, channels * 2),
            nn.GELU(),
            nn.Linear(channels * 2, channels),
        )
        self.local = nn.Conv2d(channels, channels, 3, padding=1, groups=channels)

    def forward(self, x: Tensor) -> Tensor:
        windows, pad = _window_partition(x, self.window_size)
        normalized = self.norm1(windows)
        attended, _ = self.attn(normalized, normalized, normalized, need_weights=False)
        windows = windows + attended
        windows = windows + self.mlp(self.norm2(windows))
        restored = _window_reverse(windows, self.window_size, x.shape, pad)
        return restored + self.local(restored)
