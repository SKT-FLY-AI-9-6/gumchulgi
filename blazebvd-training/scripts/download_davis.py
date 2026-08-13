from __future__ import annotations

import argparse
import shutil
import urllib.request
import zipfile
from pathlib import Path

DAVIS_TRAINVAL_480P = (
    "https://data.vision.ee.ethz.ch/csergi/share/davis/"
    "DAVIS-2017-trainval-480p.zip"
)
DAVIS_DOWNLOAD_PAGE = "https://davischallenge.org/davis2017/code.html"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download the official DAVIS 2017 TrainVal 480p archive"
    )
    parser.add_argument("--output", type=Path, default=Path("data"))
    parser.add_argument("--keep-archive", action="store_true")
    return parser


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    destination = destination.resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        if destination not in target.parents and target != destination:
            raise RuntimeError(f"Unsafe path in DAVIS archive: {member.filename}")
    archive.extractall(destination)


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    frame_root = args.output / "DAVIS" / "JPEGImages" / "480p"
    split_root = args.output / "DAVIS" / "ImageSets" / "2017"
    if frame_root.is_dir() and (split_root / "train.txt").is_file():
        print(f"DAVIS is already available at {frame_root.resolve()}")
        return

    args.output.mkdir(parents=True, exist_ok=True)
    archive_path = args.output / "DAVIS-2017-trainval-480p.zip"
    print(f"Official source: {DAVIS_DOWNLOAD_PAGE}")
    print(f"Downloading to: {archive_path.resolve()}")
    with urllib.request.urlopen(DAVIS_TRAINVAL_480P) as response:
        with archive_path.open("wb") as stream:
            shutil.copyfileobj(response, stream, length=1024 * 1024)
    with zipfile.ZipFile(archive_path) as archive:
        _safe_extract(archive, args.output)
    if not frame_root.is_dir() or not (split_root / "train.txt").is_file():
        raise RuntimeError("DAVIS archive extracted but expected frame/split paths are absent")
    if not args.keep_archive:
        archive_path.unlink()
    print(frame_root.resolve())


if __name__ == "__main__":
    main()
