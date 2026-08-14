from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch

from .config import BlazeBVDConfig
from .correction import attenuate_saturated_red
from .flow import build_flow_estimator
from .models.pipeline import BlazeBVD
from .ste import ScaleTimeEqualization
from .video import infer_clips, read_video, save_report, ste_correct_video, write_video


def _device(name: str) -> torch.device:
    if name == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BlazeBVD paper reimplementation")
    subparsers = parser.add_subparsers(dest="command", required=True)
    correct = subparsers.add_parser("correct", help="Correct a video")
    correct.add_argument("input", type=Path)
    correct.add_argument("-o", "--output", type=Path, required=True)
    correct.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    correct.add_argument("--checkpoint", type=Path)
    correct.add_argument("--stage", choices=("ste", "stage2", "full"), default="full")
    correct.add_argument("--flow", choices=("raft_small", "raft_large", "farneback", "zero"))
    correct.add_argument("--device")
    correct.add_argument("--clip-length", type=int)
    correct.add_argument("--overlap", type=int)
    correct.add_argument("--report", type=Path)
    correct.add_argument(
        "--allow-untrained",
        action="store_true",
        help="Allow randomly initialized neural modules (debugging only)",
    )
    return parser


def run_correct(args: argparse.Namespace) -> int:
    cfg = BlazeBVDConfig.from_yaml(args.config)
    if args.flow:
        cfg.flow.backend = args.flow
    if args.device:
        cfg.inference.device = args.device
    if args.clip_length:
        cfg.inference.clip_length = args.clip_length
    if args.overlap is not None:
        cfg.inference.overlap = args.overlap

    if args.stage == "ste":
        report, fps = ste_correct_video(
            args.input,
            args.output,
            ScaleTimeEqualization(cfg.ste),
            audio_source=args.input,
            correction=cfg.correction,
        )
    else:
        device = _device(cfg.inference.device)
        frames, fps = read_video(args.input)
        if args.checkpoint is None and not args.allow_untrained:
            raise RuntimeError(
                "Neural stages require trained weights. Pass --checkpoint, or use "
                "--stage ste. --allow-untrained is only for shape/debug tests."
            )
        flow = build_flow_estimator(cfg.flow.backend, cfg.flow.pretrained)
        model = BlazeBVD(cfg, flow_estimator=flow)
        if args.checkpoint is not None:
            model.load_checkpoint(str(args.checkpoint))
        model = model.to(device).eval()
        output, report = infer_clips(
            model,
            frames,
            device,
            cfg.inference.clip_length,
            cfg.inference.overlap,
            run_tcm=args.stage == "full",
            fps=fps,
        )
        # Temporal flash consolidation is already part of the STE prior used
        # by GFRM. Only saturated-red attenuation remains as a final RGB stage.
        output = attenuate_saturated_red(output, cfg.correction.red)
        report["correction_order"] = [
            "ste_brightness",
            "ste_temporal_flash_consolidation",
            "gfrm",
            "lfrm",
            *(["tcm"] if args.stage == "full" else []),
            "saturated_red_attenuation",
        ]
        write_video(output, args.output, fps, audio_source=args.input)
    report.update({"stage": args.stage, "fps": fps, "input": str(args.input)})
    if args.report:
        save_report(report, args.report)
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "correct":
            raise SystemExit(run_correct(args))
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    main(sys.argv[1:])
