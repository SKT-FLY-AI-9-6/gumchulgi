from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run GFRM -> LFRM -> TCM training with checkpoint inheritance"
    )
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--val-data", type=Path)
    parser.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    parser.add_argument(
        "--training-config", type=Path, default=Path("configs/train.yaml")
    )
    parser.add_argument("--output", type=Path, default=Path("runs/davis_blazebvd"))
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--flow", default="raft_small")
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--clip-length", type=int, default=12)
    parser.add_argument("--crop-size", type=int, default=256)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--train-samples", type=int, default=0)
    parser.add_argument("--val-samples", type=int, default=0)
    parser.add_argument("--gfrm-epochs", type=int, default=40)
    parser.add_argument("--lfrm-epochs", type=int, default=20)
    parser.add_argument("--tcm-epochs", type=int, default=30)
    parser.add_argument("--start-stage", choices=("gfrm", "lfrm", "tcm"), default="gfrm")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--amp", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--perceptual", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--adversarial", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--long-warp", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument("--tensorboard", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    return parser


def _run_logged(command: list[str], log_path: Path, env: dict[str, str]) -> None:
    print(" ".join(command), flush=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write("\n$ " + " ".join(command) + "\n")
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)
        return_code = process.wait()
    if return_code != 0:
        raise subprocess.CalledProcessError(return_code, command)


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    project_root = Path(__file__).resolve().parents[1]
    if not args.config.is_absolute():
        args.config = project_root / args.config
    if not args.training_config.is_absolute():
        args.training_config = project_root / args.training_config
    args.output.mkdir(parents=True, exist_ok=True)
    log_path = args.output / "pipeline.log"
    env = os.environ.copy()
    source_root = str(project_root / "src")
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        source_root + os.pathsep + existing_pythonpath
        if existing_pythonpath
        else source_root
    )

    if args.smoke:
        args.config = project_root / "configs" / "smoke.yaml"
        args.device = "cpu"
        args.flow = "zero"
        args.batch_size = 1
        args.clip_length = 3
        args.crop_size = 32
        args.workers = 0
        args.train_samples = 2
        args.val_samples = 1
        args.gfrm_epochs = args.lfrm_epochs = args.tcm_epochs = 1
        args.amp = args.perceptual = args.adversarial = args.long_warp = False

    stages = (
        ("gfrm", args.gfrm_epochs, None),
        ("lfrm", args.lfrm_epochs, args.output / "gfrm" / "best.pt"),
        ("tcm", args.tcm_epochs, args.output / "lfrm" / "best.pt"),
    )
    start_index = {name: index for index, (name, _, _) in enumerate(stages)}[
        args.start_stage
    ]

    for index, (stage, epochs, init_checkpoint) in enumerate(stages):
        if index < start_index:
            continue
        stage_output = args.output / stage
        command = [
            sys.executable,
            "-m",
            "blazebvd.train",
            "--data",
            str(args.data),
            "--config",
            str(args.config),
            "--training-config",
            str(args.training_config),
            "--stage",
            stage,
            "--output",
            str(stage_output),
            "--epochs",
            str(epochs),
            "--batch-size",
            str(args.batch_size),
            "--clip-length",
            str(args.clip_length),
            "--crop-size",
            str(args.crop_size),
            "--workers",
            str(args.workers),
            "--train-samples",
            str(args.train_samples),
            "--val-samples",
            str(args.val_samples),
            "--device",
            args.device,
            "--flow",
            args.flow,
        ]
        if args.val_data is not None:
            command.extend(("--val-data", str(args.val_data)))
        resume_path = stage_output / "last.pt"
        if args.resume and resume_path.is_file():
            command.extend(("--resume", str(resume_path)))
        elif init_checkpoint is not None:
            if not init_checkpoint.is_file():
                raise FileNotFoundError(
                    f"Required preceding-stage checkpoint not found: {init_checkpoint}"
                )
            command.extend(("--init-checkpoint", str(init_checkpoint)))
        if args.amp:
            command.append("--amp")
        if args.tensorboard:
            command.append("--tensorboard")
        if stage == "tcm":
            if args.perceptual:
                command.append("--perceptual")
            if args.adversarial:
                command.append("--adversarial")
            if args.long_warp:
                command.append("--long-warp")
        _run_logged(command, log_path, env)

        best = stage_output / "best.pt"
        if not best.is_file():
            raise RuntimeError(f"Stage completed without a best checkpoint: {best}")


if __name__ == "__main__":
    main()
