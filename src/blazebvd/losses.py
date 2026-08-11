from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import Tensor, nn

from .flow import backward_warp, flow_valid_mask


class VGGPerceptualLoss(nn.Module):
    """VGG16 feature L1 loss; exact VGG layers were not disclosed by BlazeBVD."""

    def __init__(self, pretrained: bool = True):
        super().__init__()
        from torchvision.models import VGG16_Weights, vgg16

        weights = VGG16_Weights.IMAGENET1K_FEATURES if pretrained else None
        features = vgg16(weights=weights).features
        self.slices = nn.ModuleList(
            [features[:4].eval(), features[4:9].eval(), features[9:16].eval()]
        )
        for parameter in self.parameters():
            parameter.requires_grad_(False)
        self.register_buffer("mean", torch.tensor([0.485, 0.456, 0.406])[None, :, None, None])
        self.register_buffer("std", torch.tensor([0.229, 0.224, 0.225])[None, :, None, None])

    def forward(self, prediction: Tensor, target: Tensor) -> Tensor:
        prediction = (prediction - self.mean) / self.std
        target = (target - self.mean) / self.std
        loss = prediction.new_tensor(0.0)
        for block in self.slices:
            prediction = block(prediction)
            target = block(target)
            loss = loss + F.l1_loss(prediction, target)
        return loss


class TemporalPatchDiscriminator(nn.Module):
    """Compact 3D PatchGAN for the spatio-temporal adversarial term."""

    def __init__(self, base_channels: int = 32):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv3d(3, base_channels, 3, padding=1),
            nn.LeakyReLU(0.2, True),
            nn.Conv3d(base_channels, base_channels * 2, 4, stride=(1, 2, 2), padding=1),
            nn.LeakyReLU(0.2, True),
            nn.Conv3d(base_channels * 2, base_channels * 4, 4, stride=(2, 2, 2), padding=1),
            nn.LeakyReLU(0.2, True),
            nn.Conv3d(base_channels * 4, 1, 3, padding=1),
        )

    def forward(self, video: Tensor) -> Tensor:
        return self.net(video.transpose(1, 2))


def adaptive_warp_loss(
    output: Tensor,
    exposure_maps: Tensor,
    flow_to_previous: Tensor,
    flow_to_first: Tensor | None = None,
    exposure_weight: Tensor | None = None,
) -> Tensor:
    """Equation (10), including adjacent and optional first-frame terms."""
    _, t, _, _, _ = output.shape
    if t < 2:
        return output.new_tensor(0.0)
    total = output.new_tensor(0.0)
    pairs = 0
    for i in range(1, t):
        mask = exposure_maps[:, i] + 1.0
        if exposure_weight is not None:
            mask = mask * exposure_weight[:, i]
        flow = flow_to_previous[:, i - 1]
        valid = flow_valid_mask(flow)
        warped = backward_warp(output[:, i - 1], flow)
        total = total + (mask * valid * (output[:, i] - warped).abs()).mean()
        pairs += 1
        if flow_to_first is not None:
            flow0 = flow_to_first[:, i - 1]
            valid0 = flow_valid_mask(flow0)
            warped0 = backward_warp(output[:, 0], flow0)
            total = total + (mask * valid0 * (output[:, i] - warped0).abs()).mean()
            pairs += 1
    return total / max(pairs, 1)


def tcm_generator_loss(
    prediction: Tensor,
    target: Tensor,
    exposure_maps: Tensor,
    flow_to_previous: Tensor,
    perceptual: nn.Module | None = None,
    discriminator: nn.Module | None = None,
    flow_to_first: Tensor | None = None,
) -> tuple[Tensor, dict[str, Tensor]]:
    reconstruction = F.l1_loss(prediction, target)
    flat_prediction = prediction.flatten(0, 1)
    flat_target = target.flatten(0, 1)
    perceptual_loss = (
        perceptual(flat_prediction, flat_target) if perceptual is not None else prediction.new_tensor(0)
    )
    if discriminator is not None:
        logits = discriminator(prediction)
        adversarial = F.binary_cross_entropy_with_logits(logits, torch.ones_like(logits))
    else:
        adversarial = prediction.new_tensor(0)
    warp = adaptive_warp_loss(
        prediction, exposure_maps, flow_to_previous, flow_to_first=flow_to_first
    )
    total = reconstruction + perceptual_loss + 0.01 * adversarial + 0.1 * warp
    return total, {
        "reconstruction": reconstruction,
        "perceptual": perceptual_loss,
        "adversarial": adversarial,
        "warp": warp,
        "total": total,
    }
