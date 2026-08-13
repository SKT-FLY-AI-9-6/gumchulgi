from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create tiny clean clips for smoke tests")
    parser.add_argument("--output", type=Path, default=Path("data/smoke"))
    parser.add_argument("--sequences", type=int, default=4)
    parser.add_argument("--frames", type=int, default=8)
    parser.add_argument("--size", type=int, default=64)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.sequences < 2 or args.frames < 3 or args.size < 32:
        raise ValueError("Expected sequences>=2, frames>=3 and size>=32")
    args.output.mkdir(parents=True, exist_ok=True)
    yy, xx = np.mgrid[: args.size, : args.size]
    for sequence_index in range(args.sequences):
        sequence = args.output / f"sequence-{sequence_index:02d}"
        sequence.mkdir(parents=True, exist_ok=True)
        for frame_index in range(args.frames):
            base = np.zeros((args.size, args.size, 3), dtype=np.uint8)
            base[..., 0] = np.clip(35 + xx * 2 + sequence_index * 7, 0, 255)
            base[..., 1] = np.clip(45 + yy * 2 + frame_index * 2, 0, 255)
            base[..., 2] = np.clip(70 + (xx + yy) + sequence_index * 5, 0, 255)
            center_x = int((frame_index + 1) * args.size / (args.frames + 1))
            center_y = args.size // 2 + (sequence_index - args.sequences // 2) * 2
            cv2.circle(
                base,
                (center_x, center_y),
                max(3, args.size // 10),
                (220, 180, 80),
                thickness=-1,
            )
            path = sequence / f"{frame_index:05d}.jpg"
            if not cv2.imwrite(str(path), base):
                raise RuntimeError(f"Could not write {path}")
    print(args.output.resolve())


if __name__ == "__main__":
    main()
