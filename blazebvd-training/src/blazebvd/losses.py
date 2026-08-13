from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import Tensor, nn

from .flow import backward_warp, flow_valid_mask


def video_value(video: Tensor) -> Tensor:
    """Return HSV-style V (maximum RGB channel) for ``[B,T,3,H,W]``."""
    if video.ndim != 5 or video.shape[2] != 3:
        raise ValueError("video must have shape [B,T,3,H,W]")
    return video.amax(dim=2, keepdim=True)


def artifact_weighted_l1(
    prediction: Tensor,
    target: Tensor,
    artifact_mask: Tensor,
    artifact_boost: float = 4.0,
) -> Tensor:
    """L1 reconstruction with extra weight on synthetically changed pixels."""
    if prediction.shape != target.shape:
        raise ValueError("prediction and target must have the same shape")
    if artifact_mask.shape != prediction.shape[:2] + (1,) + prediction.shape[-2:]:
        raise ValueError("artifact_mask must have shape [B,T,1,H,W]")
    weight = 1.0 + artifact_mask.to(prediction) * float(artifact_boost)
    error = (prediction - target).abs()
    return (error * weight).sum() / (weight.sum() * prediction.shape[2]).clamp_min(1.0)


def temporal_excess_loss(
    prediction: Tensor,
    target: Tensor,
    ste_reference: Tensor,
    margin: float = 0.02,
) -> Tensor:
    """Penalize temporal contrast created beyond clean and STE references.

    Clean-frame changes are retained as legitimate motion.  The neural output
    is penalized only when its per-pixel V-channel change exceeds *both* the
    clean target and the deterministic STE result by more than ``margin``.
    """
    if prediction.shape != target.shape or prediction.shape != ste_reference.shape:
        raise ValueError("prediction, target and ste_reference must share a shape")
    if prediction.shape[1] < 2:
        return prediction.sum() * 0.0
    predicted_delta = torch.diff(video_value(prediction), dim=1).abs()
    target_delta = torch.diff(video_value(target), dim=1).abs()
    ste_delta = torch.diff(video_value(ste_reference), dim=1).abs()
    allowed = torch.maximum(target_delta, ste_delta) + float(margin)
    return F.relu(predicted_delta - allowed).mean()


def ste_rebound_loss(
    prediction: Tensor,
    degraded: Tensor,
    target: Tensor,
    ste_reference: Tensor,
    margin: float = 0.02,
) -> Tensor:
    """Discourage restoring brightness specifically removed by STE.

    The clean target is included in the safe ceiling so real scene luminance
    is not suppressed merely because histogram equalization lowered it.  The
    weight is non-zero only where STE reduced the degraded input.
    """
    if not (
        prediction.shape == degraded.shape == target.shape == ste_reference.shape
    ):
        raise ValueError("all videos must share a shape")
    predicted_value = video_value(prediction)
    degraded_value = video_value(degraded)
    target_value = video_value(target)
    ste_value = video_value(ste_reference)
    removed = F.relu(degraded_value - ste_value).detach()
    normalizer = removed.amax(dim=(-3, -2, -1), keepdim=True).clamp_min(1e-6)
    weight = removed / normalizer
    safe_ceiling = torch.maximum(ste_value, target_value) + float(margin)
    penalty = F.relu(predicted_value - safe_ceiling)
    return (penalty * weight).sum() / weight.sum().clamp_min(1.0)


def safety_regularization(
    prediction: Tensor,
    degraded: Tensor,
    target: Tensor,
    ste_reference: Tensor,
    temporal_weight: float = 0.10,
    rebound_weight: float = 0.10,
    temporal_margin: float = 0.02,
    rebound_margin: float = 0.02,
) -> tuple[Tensor, dict[str, Tensor]]:
    """Return optional anti-reintroduction losses for neural stages."""
    temporal = temporal_excess_loss(
        prediction,
        target,
        ste_reference,
        margin=temporal_margin,
    )
    rebound = ste_rebound_loss(
        prediction,
        degraded,
        target,
        ste_reference,
        margin=rebound_margin,
    )
    total = float(temporal_weight) * temporal + float(rebound_weight) * rebound
    return total, {
        "temporal_excess": temporal,
        "rebound": rebound,
        "safety_total": total,
    }


def psnr(prediction: Tensor, target: Tensor) -> Tensor:
    mse = F.mse_loss(prediction, target).clamp_min(1e-12)
    return -10.0 * torch.log10(mse)


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
    reconstruction_weight: float = 1.0,
    perceptual_weight: float = 1.0,
    adversarial_weight: float = 0.01,
    warp_weight: float = 0.10,
) -> tuple[Tensor, dict[str, Tensor]]:
    reconstruction = F.l1_loss(prediction, target)
    flat_prediction = prediction.flatten(0, 1)
    flat_target = target.flatten(0, 1)
    perceptual_loss = (
        perceptual(flat_prediction, flat_target)
        if perceptual is not None
        else prediction.new_tensor(0)
    )
    if discriminator is not None:
        logits = discriminator(prediction)
        adversarial = F.binary_cross_entropy_with_logits(logits, torch.ones_like(logits))
    else:
        adversarial = prediction.new_tensor(0)
    warp = adaptive_warp_loss(
        prediction, exposure_maps, flow_to_previous, flow_to_first=flow_to_first
    )
    total = (
        float(reconstruction_weight) * reconstruction
        + float(perceptual_weight) * perceptual_loss
        + float(adversarial_weight) * adversarial
        + float(warp_weight) * warp
    )
    return total, {
        "reconstruction": reconstruction,
        "perceptual": perceptual_loss,
        "adversarial": adversarial,
        "warp": warp,
        "total": total,
    }
