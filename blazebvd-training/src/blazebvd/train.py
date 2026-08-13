from __future__ import annotations

import argparse
import csv
import json
import math
import random
from collections.abc import Iterator
from contextlib import nullcontext
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F
from torch import Tensor, nn
from torch.utils.data import DataLoader
from tqdm import tqdm

from .config import BlazeBVDConfig
from .data import (
    CleanVideoFolderDataset,
    discover_sequence_names,
    resolve_sequence_splits,
    seed_data_worker,
)
from .flow import ZeroFlow, adjacent_flows, build_flow_estimator
from .losses import (
    TemporalPatchDiscriminator,
    VGGPerceptualLoss,
    artifact_weighted_l1,
    psnr,
    safety_regularization,
    tcm_generator_loss,
)
from .models.pipeline import BlazeBVD
from .ste import DeflickerPriors
from .training import TrainingRecipe, ste_rgb_reference, synthetic_lfrm_masks

STAGES = ("gfrm", "lfrm", "tcm", "joint")
METRIC_COLUMNS = (
    "epoch",
    "global_step",
    "split",
    "stage",
    "learning_rate",
    "loss",
    "mse",
    "l1",
    "reconstruction",
    "perceptual",
    "adversarial",
    "warp",
    "temporal_excess",
    "rebound",
    "safety_total",
    "psnr",
    "discriminator",
    "ste_singular_recall",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train BlazeBVD neural stages after deterministic STE"
    )
    parser.add_argument("--data", type=Path, required=True, help="root/sequence/frame.jpg")
    parser.add_argument(
        "--val-data",
        type=Path,
        help="optional separate validation root; otherwise official/fallback split is used",
    )
    parser.add_argument("--train-list", type=Path)
    parser.add_argument("--val-list", type=Path)
    parser.add_argument("--val-fraction", type=float, default=0.20)
    parser.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    parser.add_argument(
        "--training-config",
        type=Path,
        default=Path("configs/train.yaml"),
        help="synthetic degradation and safety-loss recipe",
    )
    parser.add_argument("--stage", choices=STAGES, required=True)
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--init-checkpoint",
        type=Path,
        help="inherit model weights from the preceding stage",
    )
    source.add_argument(
        "--resume",
        type=Path,
        help="resume the same stage including optimizer/scaler/global step",
    )
    parser.add_argument("--allow-random-init", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("checkpoints"))
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--clip-length", type=int, default=12)
    parser.add_argument("--crop-size", type=int, default=256)
    parser.add_argument(
        "--train-samples",
        type=int,
        default=0,
        help="clips per epoch; 0 means 16 per train sequence",
    )
    parser.add_argument(
        "--val-samples",
        type=int,
        default=0,
        help="validation clips; 0 means 2 per validation sequence",
    )
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--minimum-lr-ratio", type=float, default=0.01)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--warmup-steps", type=int, default=100)
    parser.add_argument("--grad-clip", type=float, default=1.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument(
        "--flow",
        choices=("raft_small", "raft_large", "farneback", "zero"),
        help="override config flow backend",
    )
    parser.add_argument("--device", default="auto")
    parser.add_argument("--perceptual", action="store_true")
    parser.add_argument("--adversarial", action="store_true")
    parser.add_argument("--long-warp", action="store_true", help="include O_t vs O_1 term")
    parser.add_argument("--amp", action="store_true")
    parser.add_argument("--tensorboard", action="store_true")
    parser.add_argument(
        "--lfrm-force-all",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="exercise all interior frames while training LFRM/joint",
    )
    parser.add_argument("--save-every", type=int, default=0)
    parser.add_argument("--max-train-batches", type=int, default=0)
    parser.add_argument("--max-val-batches", type=int, default=0)
    parser.add_argument("--deterministic", action="store_true")
    return parser


def _select_device(name: str) -> torch.device:
    if name == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    device = torch.device(name)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but torch.cuda.is_available() is false")
    return device


def _seed_everything(seed: int, deterministic: bool) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    if deterministic:
        torch.use_deterministic_algorithms(True, warn_only=True)
        if hasattr(torch.backends, "cudnn"):
            torch.backends.cudnn.benchmark = False


def _validate_args(args: argparse.Namespace) -> None:
    if args.epochs < 1:
        raise ValueError("epochs must be >= 1")
    if args.batch_size < 1 or args.workers < 0:
        raise ValueError("batch-size must be >= 1 and workers must be >= 0")
    if args.clip_length < 3 and args.stage in {"lfrm", "tcm", "joint"}:
        raise ValueError("lfrm/tcm/joint require clip-length >= 3")
    if args.fps <= 0:
        raise ValueError("fps must be positive")
    if args.learning_rate <= 0 or args.weight_decay < 0:
        raise ValueError("learning-rate must be positive and weight-decay non-negative")
    if not 0 < args.minimum_lr_ratio <= 1:
        raise ValueError("minimum-lr-ratio must be in (0, 1]")
    if args.warmup_steps < 0 or args.grad_clip < 0:
        raise ValueError("warmup-steps and grad-clip must be non-negative")
    if args.adversarial and args.stage not in {"tcm", "joint"}:
        raise ValueError("--adversarial is supported only for tcm or joint")
    if (
        args.stage in {"lfrm", "tcm"}
        and args.init_checkpoint is None
        and args.resume is None
        and not args.allow_random_init
    ):
        raise ValueError(
            f"{args.stage} requires --init-checkpoint from the preceding stage; "
            "use --allow-random-init only for smoke/debug runs"
        )
    for name in ("train_samples", "val_samples", "save_every"):
        if getattr(args, name) < 0:
            raise ValueError(f"{name.replace('_', '-')} must be non-negative")


def _set_trainable(model: BlazeBVD, stage: str) -> list[nn.Parameter]:
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    if stage == "gfrm":
        modules: list[nn.Module] = [model.gfrm]
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
    return [parameter for parameter in model.parameters() if parameter.requires_grad]


def _autocast(device: torch.device, enabled: bool):
    if not enabled:
        return nullcontext()
    return torch.autocast(device_type=device.type, dtype=torch.float16)


def _build_scaler(enabled: bool):
    try:
        return torch.amp.GradScaler("cuda", enabled=enabled)
    except (AttributeError, TypeError):
        return torch.cuda.amp.GradScaler(enabled=enabled)


def _build_datasets(
    args: argparse.Namespace,
    recipe: TrainingRecipe,
) -> tuple[CleanVideoFolderDataset, CleanVideoFolderDataset, dict[str, Any]]:
    if args.val_data is not None:
        if args.train_list is not None or args.val_list is not None:
            raise ValueError("Do not combine --val-data with --train-list/--val-list")
        train_names = discover_sequence_names(args.data)
        val_names = discover_sequence_names(args.val_data)
        val_root = args.val_data
        split_source = "separate_roots"
    else:
        train_names, val_names, split_source = resolve_sequence_splits(
            args.data,
            args.train_list,
            args.val_list,
            args.val_fraction,
            args.seed,
        )
        val_root = args.data
    train_samples = args.train_samples or len(train_names) * 16
    val_samples = args.val_samples or len(val_names) * 2
    train_dataset = CleanVideoFolderDataset(
        args.data,
        clip_length=args.clip_length,
        crop_size=args.crop_size,
        degradation=recipe.degradation,
        sequence_names=train_names,
        samples_per_epoch=train_samples,
        seed=args.seed,
        training=True,
    )
    val_dataset = CleanVideoFolderDataset(
        val_root,
        clip_length=args.clip_length,
        crop_size=args.crop_size,
        degradation=recipe.degradation,
        sequence_names=val_names,
        samples_per_epoch=val_samples,
        seed=args.seed + 100_000,
        training=False,
    )
    split_info = {
        "source": split_source,
        "train_root": str(args.data),
        "val_root": str(val_root),
        "train_sequences": train_names,
        "val_sequences": val_names,
        "train_samples_per_epoch": train_samples,
        "val_samples": val_samples,
    }
    return train_dataset, val_dataset, split_info


def _build_loaders(
    args: argparse.Namespace,
    device: torch.device,
    train_dataset: CleanVideoFolderDataset,
    val_dataset: CleanVideoFolderDataset,
) -> tuple[DataLoader, DataLoader]:
    common = {
        "batch_size": args.batch_size,
        "num_workers": args.workers,
        "pin_memory": device.type == "cuda",
        "worker_init_fn": seed_data_worker,
    }
    train_generator = torch.Generator().manual_seed(args.seed)
    val_generator = torch.Generator().manual_seed(args.seed + 1)
    train_loader = DataLoader(
        train_dataset,
        shuffle=True,
        generator=train_generator,
        **common,
    )
    val_loader = DataLoader(
        val_dataset,
        shuffle=False,
        generator=val_generator,
        **common,
    )
    return train_loader, val_loader


def _ste_and_flows(
    model: BlazeBVD,
    degraded: Tensor,
    stage: str,
    fps: float,
) -> tuple[DeflickerPriors, Tensor, Tensor, Tensor]:
    # STE and optical flow are deterministic/frozen.  Keep them in float32
    # even when mixed precision is enabled for trainable neural modules.
    with torch.no_grad(), torch.autocast(device_type=degraded.device.type, enabled=False):
        frames = degraded.float()
        priors = model.ste(
            frames,
            fps=fps,
            flash_config=model.config.correction.flash,
        )
        ste_reference = ste_rgb_reference(frames, priors)
        if stage == "gfrm":
            b, t, _, h, w = frames.shape
            empty = frames.new_empty(b, max(t - 1, 0), 2, h, w)
            to_previous, to_next = empty, empty
        else:
            to_previous, to_next = adjacent_flows(frames, model.flow_estimator)
    return priors, ste_reference, to_previous, to_next


def _forward_stage(
    model: BlazeBVD,
    stage: str,
    degraded: Tensor,
    artifact: Tensor,
    fps: float,
    device: torch.device,
    amp_enabled: bool,
    artifact_threshold: float,
    lfrm_force_all: bool,
) -> tuple[Tensor, DeflickerPriors, Tensor, Tensor, Tensor, Tensor]:
    priors, ste_reference, to_previous, to_next = _ste_and_flows(
        model,
        degraded,
        stage,
        fps,
    )
    artifact_mask = artifact.abs().amax(dim=2, keepdim=True) > artifact_threshold
    exposure_for_loss = priors.exposure_maps

    with _autocast(device, amp_enabled):
        if stage == "gfrm":
            prediction = model.global_stage(degraded, priors)
            return (
                prediction,
                priors,
                ste_reference,
                to_previous,
                exposure_for_loss,
                artifact_mask,
            )

        if stage == "joint":
            global_corrected = model.global_stage(degraded, priors)
        else:
            with torch.no_grad():
                global_corrected = model.global_stage(degraded, priors)

        if stage in {"lfrm", "joint"}:
            training_exposure, active_frames = synthetic_lfrm_masks(
                artifact,
                priors,
                threshold=artifact_threshold,
            )
            exposure_for_loss = training_exposure
            local_corrected = model.lfrm.refine_sequence(
                global_corrected,
                training_exposure,
                priors.singular_frames,
                to_previous,
                to_next,
                active_frames=active_frames,
                force_all=lfrm_force_all,
            )
        else:
            # TCM learns on the same Stage-2 gating used during inference.
            with torch.no_grad():
                local_corrected = model.lfrm.refine_sequence(
                    global_corrected,
                    priors.exposure_maps,
                    priors.singular_frames,
                    to_previous,
                    to_next,
                )

        if stage == "lfrm":
            prediction = local_corrected
        else:
            prediction = model.tcm(local_corrected, to_previous, to_next)

    return (
        prediction,
        priors,
        ste_reference,
        to_previous,
        exposure_for_loss,
        artifact_mask,
    )


@torch.no_grad()
def _flows_to_first(model: BlazeBVD, frames: Tensor) -> Tensor:
    b, t, c, h, w = frames.shape
    if t < 2:
        return frames.new_empty(b, 0, 2, h, w)
    current = frames[:, 1:].reshape(-1, c, h, w)
    first = frames[:, :1].expand(-1, t - 1, -1, -1, -1)
    first = first.reshape(-1, c, h, w)
    return model.flow_estimator(current, first).reshape(b, t - 1, 2, h, w)


def _generator_loss(
    stage: str,
    prediction: Tensor,
    clean: Tensor,
    degraded: Tensor,
    artifact_mask: Tensor,
    priors: DeflickerPriors,
    ste_reference: Tensor,
    flow_to_previous: Tensor,
    exposure_for_loss: Tensor,
    recipe: TrainingRecipe,
    perceptual: nn.Module | None,
    discriminator: nn.Module | None,
    flow_to_first: Tensor | None,
) -> tuple[Tensor, dict[str, Tensor]]:
    # Compute loss reductions in float32 even when network activations use AMP.
    prediction = prediction.float()
    clean = clean.float()
    degraded = degraded.float()
    ste_reference = ste_reference.float()
    loss_cfg = recipe.loss
    if stage == "gfrm":
        base = F.mse_loss(prediction, clean)
        parts: dict[str, Tensor] = {"mse": base}
    elif stage == "lfrm":
        base = artifact_weighted_l1(
            prediction,
            clean,
            artifact_mask,
            artifact_boost=loss_cfg.lfrm_artifact_boost,
        )
        parts = {"l1": base}
    else:
        base, parts = tcm_generator_loss(
            prediction,
            clean,
            exposure_for_loss.float(),
            flow_to_previous.float(),
            perceptual=perceptual,
            discriminator=discriminator,
            flow_to_first=flow_to_first,
            reconstruction_weight=loss_cfg.reconstruction_weight,
            perceptual_weight=loss_cfg.perceptual_weight,
            adversarial_weight=loss_cfg.adversarial_weight,
            warp_weight=loss_cfg.warp_weight,
        )
    safety, safety_parts = safety_regularization(
        prediction,
        degraded,
        clean,
        ste_reference,
        temporal_weight=loss_cfg.temporal_excess_weight,
        rebound_weight=loss_cfg.rebound_weight,
        temporal_margin=loss_cfg.temporal_margin,
        rebound_margin=loss_cfg.rebound_margin,
    )
    total = base + safety
    parts.update(safety_parts)
    parts["loss"] = total
    parts["psnr"] = psnr(prediction.detach(), clean)

    synthetic_active = artifact_mask.flatten(2).any(dim=2)
    true_positive = (synthetic_active & priors.singular_frames).sum().float()
    positive = synthetic_active.sum().float()
    parts["ste_singular_recall"] = true_positive / positive.clamp_min(1.0)
    return total, parts


class MetricAccumulator:
    def __init__(self) -> None:
        self.sums: dict[str, float] = {}
        self.weight = 0

    def update(self, metrics: dict[str, Tensor | float], weight: int) -> None:
        self.weight += int(weight)
        for name, value in metrics.items():
            number = float(value.detach()) if isinstance(value, Tensor) else float(value)
            self.sums[name] = self.sums.get(name, 0.0) + number * weight

    def means(self) -> dict[str, float]:
        if self.weight == 0:
            raise RuntimeError("No batches were processed")
        return {name: value / self.weight for name, value in self.sums.items()}


def _limited_batches(loader: DataLoader, limit: int) -> Iterator[tuple[int, Any]]:
    for index, batch in enumerate(loader):
        if limit and index >= limit:
            break
        yield index, batch


def _effective_batches(loader: DataLoader, limit: int) -> int:
    return min(len(loader), limit) if limit else len(loader)


def _learning_rate(
    base_lr: float,
    step: int,
    total_steps: int,
    warmup_steps: int,
    minimum_ratio: float,
) -> float:
    if warmup_steps > 0 and step < warmup_steps:
        return base_lr * float(step + 1) / warmup_steps
    decay_steps = max(total_steps - warmup_steps, 1)
    progress = min(max((step - warmup_steps) / decay_steps, 0.0), 1.0)
    cosine = 0.5 * (1.0 + math.cos(math.pi * progress))
    return base_lr * (minimum_ratio + (1.0 - minimum_ratio) * cosine)


def _set_optimizer_lr(optimizer: torch.optim.Optimizer, learning_rate: float) -> None:
    for group in optimizer.param_groups:
        group["lr"] = learning_rate


def _set_requires_grad(module: nn.Module | None, enabled: bool) -> None:
    if module is None:
        return
    for parameter in module.parameters():
        parameter.requires_grad_(enabled)


def _run_epoch(
    *,
    model: BlazeBVD,
    stage: str,
    loader: DataLoader,
    device: torch.device,
    recipe: TrainingRecipe,
    args: argparse.Namespace,
    epoch: int,
    training: bool,
    optimizer: torch.optim.Optimizer,
    scaler: Any,
    perceptual: nn.Module | None,
    discriminator: TemporalPatchDiscriminator | None,
    disc_optimizer: torch.optim.Optimizer | None,
    global_step: int,
    total_steps: int,
) -> tuple[dict[str, float], int, float]:
    if training:
        _set_trainable(model, stage)
        if discriminator is not None:
            discriminator.train()
    else:
        model.eval()
        if discriminator is not None:
            discriminator.eval()

    limit = args.max_train_batches if training else args.max_val_batches
    batch_count = _effective_batches(loader, limit)
    split = "train" if training else "val"
    progress = tqdm(
        _limited_batches(loader, limit),
        total=batch_count,
        desc=f"{stage} {split} epoch {epoch}/{args.epochs}",
    )
    accumulator = MetricAccumulator()
    last_lr = optimizer.param_groups[0]["lr"]
    grad_context = nullcontext() if training else torch.no_grad()

    with grad_context:
        for _, batch in progress:
            degraded = batch["degraded"].to(device, non_blocking=True)
            clean = batch["clean"].to(device, non_blocking=True)
            artifact = batch["artifact"].to(device, non_blocking=True)
            if training:
                last_lr = _learning_rate(
                    args.learning_rate,
                    global_step,
                    total_steps,
                    args.warmup_steps,
                    args.minimum_lr_ratio,
                )
                _set_optimizer_lr(optimizer, last_lr)
                optimizer.zero_grad(set_to_none=True)
                _set_requires_grad(discriminator, False)

            (
                prediction,
                priors,
                ste_reference,
                to_previous,
                exposure_for_loss,
                artifact_mask,
            ) = _forward_stage(
                model,
                stage,
                degraded,
                artifact,
                args.fps,
                device,
                args.amp and device.type == "cuda",
                recipe.loss.lfrm_artifact_threshold,
                args.lfrm_force_all and training,
            )
            first_flows = (
                _flows_to_first(model, degraded).float()
                if args.long_warp and stage in {"tcm", "joint"}
                else None
            )
            loss, parts = _generator_loss(
                stage,
                prediction,
                clean,
                degraded,
                artifact_mask,
                priors,
                ste_reference,
                to_previous,
                exposure_for_loss,
                recipe,
                perceptual,
                discriminator,
                first_flows,
            )

            if training:
                scaler.scale(loss).backward()
                if args.grad_clip > 0:
                    scaler.unscale_(optimizer)
                    nn.utils.clip_grad_norm_(
                        [
                            parameter
                            for parameter in model.parameters()
                            if parameter.requires_grad
                        ],
                        args.grad_clip,
                    )
                scaler.step(optimizer)
                scaler.update()
                global_step += 1

                if discriminator is not None and disc_optimizer is not None:
                    _set_requires_grad(discriminator, True)
                    disc_optimizer.zero_grad(set_to_none=True)
                    real_logits = discriminator(clean.float())
                    fake_logits = discriminator(prediction.detach().float())
                    disc_loss = 0.5 * (
                        F.binary_cross_entropy_with_logits(
                            real_logits,
                            torch.ones_like(real_logits),
                        )
                        + F.binary_cross_entropy_with_logits(
                            fake_logits,
                            torch.zeros_like(fake_logits),
                        )
                    )
                    disc_loss.backward()
                    disc_optimizer.step()
                    parts["discriminator"] = disc_loss.detach()

            accumulator.update(parts, degraded.shape[0])
            means = accumulator.means()
            progress.set_postfix(
                loss=f"{means['loss']:.4f}",
                psnr=f"{means['psnr']:.2f}",
                lr=f"{last_lr:.2e}",
            )
    return accumulator.means(), global_step, last_lr


def _jsonable_args(args: argparse.Namespace) -> dict[str, Any]:
    return {
        key: str(value) if isinstance(value, Path) else value
        for key, value in vars(args).items()
    }


def _append_record(output: Path, record: dict[str, Any]) -> None:
    csv_path = output / "metrics.csv"
    write_header = not csv_path.exists()
    with csv_path.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=METRIC_COLUMNS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow({name: record.get(name, "") for name in METRIC_COLUMNS})
    with (output / "metrics.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")


def _checkpoint(
    *,
    model: BlazeBVD,
    optimizer: torch.optim.Optimizer,
    scaler: Any,
    discriminator: TemporalPatchDiscriminator | None,
    disc_optimizer: torch.optim.Optimizer | None,
    cfg: BlazeBVDConfig,
    recipe: TrainingRecipe,
    args: argparse.Namespace,
    epoch: int,
    global_step: int,
    best_val_loss: float,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "format_version": 2,
        "epoch": epoch,
        "global_step": global_step,
        "best_val_loss": best_val_loss,
        "stage": args.stage,
        "model": model.state_dict(),
        "optimizer": optimizer.state_dict(),
        "scaler": scaler.state_dict(),
        "config": cfg.to_dict(),
        "training_recipe": asdict(recipe),
        "train_args": _jsonable_args(args),
    }
    if discriminator is not None and disc_optimizer is not None:
        payload["discriminator"] = discriminator.state_dict()
        payload["discriminator_optimizer"] = disc_optimizer.state_dict()
    return payload


def _load_resume(
    path: Path,
    model: BlazeBVD,
    optimizer: torch.optim.Optimizer,
    scaler: Any,
    discriminator: TemporalPatchDiscriminator | None,
    disc_optimizer: torch.optim.Optimizer | None,
    expected_stage: str,
) -> tuple[int, int, float]:
    checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    checkpoint_stage = checkpoint.get("stage")
    if checkpoint_stage != expected_stage:
        raise ValueError(
            f"Resume checkpoint stage is {checkpoint_stage!r}, expected {expected_stage!r}"
        )
    model.load_state_dict(checkpoint["model"], strict=False)
    optimizer.load_state_dict(checkpoint["optimizer"])
    if "scaler" in checkpoint:
        scaler.load_state_dict(checkpoint["scaler"])
    if discriminator is not None and "discriminator" in checkpoint:
        discriminator.load_state_dict(checkpoint["discriminator"])
    if disc_optimizer is not None and "discriminator_optimizer" in checkpoint:
        disc_optimizer.load_state_dict(checkpoint["discriminator_optimizer"])
    return (
        int(checkpoint.get("epoch", 0)) + 1,
        int(checkpoint.get("global_step", 0)),
        float(checkpoint.get("best_val_loss", math.inf)),
    )


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    _validate_args(args)
    _seed_everything(args.seed, args.deterministic)
    cfg = BlazeBVDConfig.from_yaml(args.config)
    recipe = TrainingRecipe.from_yaml(args.training_config)
    if args.flow:
        cfg.flow.backend = args.flow
    device = _select_device(args.device)

    train_dataset, val_dataset, split_info = _build_datasets(args, recipe)
    train_loader, val_loader = _build_loaders(
        args,
        device,
        train_dataset,
        val_dataset,
    )
    flow = (
        ZeroFlow()
        if args.stage == "gfrm"
        else build_flow_estimator(cfg.flow.backend, cfg.flow.pretrained)
    )
    model = BlazeBVD(cfg, flow_estimator=flow).to(device)
    if args.init_checkpoint is not None:
        model.load_checkpoint(str(args.init_checkpoint), strict=False)

    trainable = _set_trainable(model, args.stage)
    if not trainable:
        raise RuntimeError(f"No trainable parameters selected for stage {args.stage}")
    optimizer = torch.optim.AdamW(
        trainable,
        lr=args.learning_rate,
        betas=(0.9, 0.99),
        weight_decay=args.weight_decay,
    )
    scaler = _build_scaler(args.amp and device.type == "cuda")
    perceptual = (
        VGGPerceptualLoss().to(device).eval()
        if args.perceptual and args.stage in {"tcm", "joint"}
        else None
    )
    discriminator = (
        TemporalPatchDiscriminator().to(device)
        if args.adversarial and args.stage in {"tcm", "joint"}
        else None
    )
    disc_optimizer = (
        torch.optim.AdamW(
            discriminator.parameters(),
            lr=args.learning_rate,
            betas=(0.5, 0.999),
            weight_decay=args.weight_decay,
        )
        if discriminator is not None
        else None
    )

    args.output.mkdir(parents=True, exist_ok=True)
    run_manifest = {
        "stage": args.stage,
        "device": str(device),
        "trainable_parameters": sum(parameter.numel() for parameter in trainable),
        "config": cfg.to_dict(),
        "training_recipe": asdict(recipe),
        "arguments": _jsonable_args(args),
        "split": split_info,
    }
    (args.output / "run_config.json").write_text(
        json.dumps(run_manifest, indent=2),
        encoding="utf-8",
    )

    writer = None
    if args.tensorboard:
        try:
            from torch.utils.tensorboard import SummaryWriter
        except ImportError as exc:
            raise RuntimeError(
                "--tensorboard requires the tensorboard package"
            ) from exc
        writer = SummaryWriter(log_dir=str(args.output / "tensorboard"))

    start_epoch, global_step, best_val_loss = 1, 0, math.inf
    if args.resume is not None:
        start_epoch, global_step, best_val_loss = _load_resume(
            args.resume,
            model,
            optimizer,
            scaler,
            discriminator,
            disc_optimizer,
            args.stage,
        )
    if start_epoch > args.epochs:
        raise ValueError(
            f"Resume starts at epoch {start_epoch}, but --epochs is {args.epochs}"
        )

    train_batches = _effective_batches(train_loader, args.max_train_batches)
    total_steps = args.epochs * train_batches
    print(
        json.dumps(
            {
                "stage": args.stage,
                "device": str(device),
                "trainable_parameters": run_manifest["trainable_parameters"],
                "split_source": split_info["source"],
                "train_sequences": len(split_info["train_sequences"]),
                "val_sequences": len(split_info["val_sequences"]),
                "train_batches_per_epoch": train_batches,
                "start_epoch": start_epoch,
            },
            indent=2,
        ),
        flush=True,
    )

    try:
        for epoch in range(start_epoch, args.epochs + 1):
            train_dataset.set_epoch(epoch)
            val_dataset.set_epoch(0)
            train_metrics, global_step, learning_rate = _run_epoch(
                model=model,
                stage=args.stage,
                loader=train_loader,
                device=device,
                recipe=recipe,
                args=args,
                epoch=epoch,
                training=True,
                optimizer=optimizer,
                scaler=scaler,
                perceptual=perceptual,
                discriminator=discriminator,
                disc_optimizer=disc_optimizer,
                global_step=global_step,
                total_steps=total_steps,
            )
            val_metrics, _, _ = _run_epoch(
                model=model,
                stage=args.stage,
                loader=val_loader,
                device=device,
                recipe=recipe,
                args=args,
                epoch=epoch,
                training=False,
                optimizer=optimizer,
                scaler=scaler,
                perceptual=perceptual,
                discriminator=discriminator,
                disc_optimizer=disc_optimizer,
                global_step=global_step,
                total_steps=total_steps,
            )

            for split, metrics in (("train", train_metrics), ("val", val_metrics)):
                record = {
                    "epoch": epoch,
                    "global_step": global_step,
                    "split": split,
                    "stage": args.stage,
                    "learning_rate": learning_rate,
                    **metrics,
                }
                _append_record(args.output, record)
                if writer is not None:
                    for name, value in metrics.items():
                        writer.add_scalar(f"{split}/{name}", value, epoch)
                    writer.add_scalar(f"{split}/learning_rate", learning_rate, epoch)

            improved = val_metrics["loss"] < best_val_loss
            if improved:
                best_val_loss = val_metrics["loss"]
            checkpoint = _checkpoint(
                model=model,
                optimizer=optimizer,
                scaler=scaler,
                discriminator=discriminator,
                disc_optimizer=disc_optimizer,
                cfg=cfg,
                recipe=recipe,
                args=args,
                epoch=epoch,
                global_step=global_step,
                best_val_loss=best_val_loss,
            )
            torch.save(checkpoint, args.output / "last.pt")
            if improved:
                torch.save(checkpoint, args.output / "best.pt")
            if args.save_every and epoch % args.save_every == 0:
                torch.save(checkpoint, args.output / f"epoch_{epoch:03d}.pt")

            summary = {
                "epoch": epoch,
                "global_step": global_step,
                "best_val_loss": best_val_loss,
                "train": train_metrics,
                "val": val_metrics,
            }
            (args.output / "last_metrics.json").write_text(
                json.dumps(summary, indent=2),
                encoding="utf-8",
            )
            print(json.dumps(summary, indent=2), flush=True)
    finally:
        if writer is not None:
            writer.close()


if __name__ == "__main__":
    main()
