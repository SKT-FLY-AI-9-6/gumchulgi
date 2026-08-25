from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
import torch.nn.functional as F
from torch import nn
from torch.utils.data import DataLoader
from tqdm import tqdm

from .config import BlazeBVDConfig
from .data import CleanVideoFolderDataset
from .flow import ZeroFlow, adjacent_flows, build_flow_estimator
from .losses import (
    TemporalPatchDiscriminator,
    VGGPerceptualLoss,
    tcm_generator_loss,
)
from .models.pipeline import BlazeBVD


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train BlazeBVD stages on clean video clips")
    parser.add_argument("--data", type=Path, required=True, help="root/sequence/frame.jpg")
    parser.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    parser.add_argument("--stage", choices=("gfrm", "lfrm", "tcm", "joint"), required=True)
    parser.add_argument("--init-checkpoint", type=Path)
    parser.add_argument("--output", type=Path, default=Path("checkpoints"))
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--clip-length", type=int, default=12)
    parser.add_argument("--crop-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--perceptual", action="store_true")
    parser.add_argument("--adversarial", action="store_true")
    parser.add_argument("--long-warp", action="store_true", help="Include O_t vs O_1 term")
    parser.add_argument("--amp", action="store_true")
    return parser


def _select_device(name: str) -> torch.device:
    if name == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(name)


def _set_trainable(model: BlazeBVD, stage: str) -> None:
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    modules: list[nn.Module]
    if stage == "gfrm":
        modules = [model.gfrm]
    elif stage == "lfrm":
        modules = [model.lfrm]
    elif stage == "tcm":
        modules = [model.tcm]
    else:
        modules = [model.gfrm, model.lfrm, model.tcm]
    for module in modules:
        module.train()
        for parameter in module.parameters():
            parameter.requires_grad_(True)


@torch.no_grad()
def _stage2(model: BlazeBVD, degraded: torch.Tensor):
    priors = model.ste(degraded)
    global_corrected = model.global_stage(degraded, priors)
    to_previous, to_next = adjacent_flows(degraded, model.flow_estimator)
    local_corrected = model.lfrm.refine_sequence(
        global_corrected,
        priors.exposure_maps,
        priors.singular_frames,
        to_previous,
        to_next,
    )
    return priors, global_corrected, local_corrected, to_previous, to_next


@torch.no_grad()
def _flows_to_first(model: BlazeBVD, frames: torch.Tensor) -> torch.Tensor:
    b, t, c, h, w = frames.shape
    if t < 2:
        return frames.new_empty(b, 0, 2, h, w)
    current = frames[:, 1:].reshape(-1, c, h, w)
    first = frames[:, :1].expand(-1, t - 1, -1, -1, -1).reshape(-1, c, h, w)
    return model.flow_estimator(current, first).reshape(b, t - 1, 2, h, w)


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    cfg = BlazeBVDConfig.from_yaml(args.config)
    device = _select_device(args.device)
    dataset = CleanVideoFolderDataset(
        args.data, clip_length=args.clip_length, crop_size=args.crop_size
    )
    loader = DataLoader(
        dataset,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=args.workers,
        pin_memory=device.type == "cuda",
    )
    flow = (
        ZeroFlow()
        if args.stage == "gfrm"
        else build_flow_estimator(cfg.flow.backend, cfg.flow.pretrained)
    )
    model = BlazeBVD(cfg, flow_estimator=flow).to(device)
    if args.init_checkpoint:
        model.load_checkpoint(str(args.init_checkpoint), strict=False)
    _set_trainable(model, args.stage)
    trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
    optimizer = torch.optim.AdamW(trainable, lr=args.learning_rate, betas=(0.9, 0.99))
    scaler = torch.amp.GradScaler("cuda", enabled=args.amp and device.type == "cuda")
    perceptual = VGGPerceptualLoss().to(device).eval() if args.perceptual else None
    discriminator = TemporalPatchDiscriminator().to(device) if args.adversarial else None
    disc_optimizer = (
        torch.optim.AdamW(discriminator.parameters(), lr=args.learning_rate, betas=(0.5, 0.999))
        if discriminator is not None
        else None
    )
    args.output.mkdir(parents=True, exist_ok=True)

    for epoch in range(1, args.epochs + 1):
        progress = tqdm(loader, desc=f"{args.stage} epoch {epoch}/{args.epochs}")
        running = 0.0
        for batch in progress:
            degraded = batch["degraded"].to(device, non_blocking=True)
            clean = batch["clean"].to(device, non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            with torch.amp.autocast(device_type=device.type, enabled=args.amp):
                if args.stage == "gfrm":
                    priors = model.ste(degraded)
                    prediction = model.global_stage(degraded, priors)
                    loss = F.mse_loss(prediction, clean)
                    parts = {"mse": loss}
                elif args.stage == "lfrm":
                    priors, global_corrected, _, to_previous, to_next = _stage2(model, degraded)
                    prediction = model.lfrm.refine_sequence(
                        global_corrected,
                        priors.exposure_maps,
                        priors.singular_frames,
                        to_previous,
                        to_next,
                    )
                    loss = F.l1_loss(prediction, clean)
                    parts = {"l1": loss}
                else:
                    if args.stage == "tcm":
                        priors, _, stage2, to_previous, to_next = _stage2(model, degraded)
                        prediction = model.tcm(stage2, to_previous, to_next)
                    else:
                        result = model(degraded)
                        priors = result.priors
                        to_previous = result.flow_to_previous
                        prediction = result.output
                    first_flows = _flows_to_first(model, degraded) if args.long_warp else None
                    loss, parts = tcm_generator_loss(
                        prediction,
                        clean,
                        priors.exposure_maps,
                        to_previous,
                        perceptual=perceptual,
                        discriminator=discriminator,
                        flow_to_first=first_flows,
                    )
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()

            if discriminator is not None and disc_optimizer is not None:
                disc_optimizer.zero_grad(set_to_none=True)
                real_logits = discriminator(clean)
                fake_logits = discriminator(prediction.detach())
                disc_loss = 0.5 * (
                    F.binary_cross_entropy_with_logits(real_logits, torch.ones_like(real_logits))
                    + F.binary_cross_entropy_with_logits(fake_logits, torch.zeros_like(fake_logits))
                )
                disc_loss.backward()
                disc_optimizer.step()
                parts["discriminator"] = disc_loss.detach()

            running += float(loss.detach())
            progress.set_postfix(
                loss=f"{running / max(1, progress.n + 1):.4f}",
                **{key: f"{float(value.detach()):.3f}" for key, value in parts.items()},
            )

        checkpoint = {
            "epoch": epoch,
            "stage": args.stage,
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "config": cfg.to_dict(),
            "train_args": vars(args),
        }
        if discriminator is not None:
            checkpoint["discriminator"] = discriminator.state_dict()
        torch.save(checkpoint, args.output / f"{args.stage}_epoch_{epoch:03d}.pt")
        (args.output / "last_metrics.json").write_text(
            json.dumps({"epoch": epoch, "loss": running / len(loader)}, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()

