from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import Tensor, nn

from .blocks import ConvAct


class GlobalFlickerRemovalModule(nn.Module):
    """The 6-channel 2D U-Net from the BlazeBVD supplementary table."""

    def __init__(self, output_mode: str = "residual"):
        super().__init__()
        if output_mode not in {"residual", "sigmoid"}:
            raise ValueError("output_mode must be 'residual' or 'sigmoid'")
        self.output_mode = output_mode
        self.enc1 = ConvAct(6, 32)
        self.enc2 = ConvAct(32, 64)
        self.enc3 = ConvAct(64, 128)
        self.enc4 = ConvAct(128, 256)
        self.pool = nn.MaxPool2d(2)
        self.bottleneck = ConvAct(256, 512)
        self.up4 = ConvAct(512, 256)
        self.dec4 = ConvAct(512, 256)
        self.up3 = ConvAct(256, 128)
        self.dec3 = ConvAct(256, 128)
        self.up2 = ConvAct(128, 64)
        self.dec2 = ConvAct(128, 64)
        self.up1 = ConvAct(64, 32)
        self.dec1 = ConvAct(64, 32)
        self.out = nn.Conv2d(32, 3, 1)

    @staticmethod
    def _up(x: Tensor, skip: Tensor, projection: nn.Module) -> Tensor:
        x = F.interpolate(x, size=skip.shape[-2:], mode="bilinear", align_corners=False)
        return projection(x)

    def forward(self, frame: Tensor, filtered_value: Tensor) -> Tensor:
        if filtered_value.shape[1] == 1:
            filtered_value = filtered_value.expand(-1, 3, -1, -1)
        if filtered_value.shape[1] != 3:
            raise ValueError("filtered_value must contain 1 or 3 channels")
        x = torch.cat((frame, filtered_value), dim=1)
        e1 = self.enc1(x)
        e2 = self.enc2(self.pool(e1))
        e3 = self.enc3(self.pool(e2))
        e4 = self.enc4(self.pool(e3))
        b = self.bottleneck(self.pool(e4))
        d4 = self.dec4(torch.cat((self._up(b, e4, self.up4), e4), dim=1))
        d3 = self.dec3(torch.cat((self._up(d4, e3, self.up3), e3), dim=1))
        d2 = self.dec2(torch.cat((self._up(d3, e2, self.up2), e2), dim=1))
        d1 = self.dec1(torch.cat((self._up(d2, e1, self.up1), e1), dim=1))
        prediction = self.out(d1)
        if self.output_mode == "sigmoid":
            return prediction.sigmoid()
        return (frame + prediction).clamp(0, 1)

