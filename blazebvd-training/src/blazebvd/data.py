from __future__ import annotations

import random
from collections.abc import Iterable
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from torch import Tensor
from torch.utils.data import Dataset

from .degradation import FlickerSynthesisConfig, synthesize_flicker

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def _read_rgb(path: Path) -> Tensor:
    # imdecode/fromfile is reliable for Korean and other non-ASCII Windows paths.
    encoded = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Could not read image: {path}")
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    return torch.from_numpy(image.copy()).permute(2, 0, 1).float().div(255)


def read_sequence_list(path: str | Path) -> list[str]:
    names = [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines()]
    return [name for name in names if name and not name.startswith("#")]


def discover_sequence_names(root: str | Path) -> list[str]:
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(f"Video frame root does not exist: {root}")
    return sorted(path.name for path in root.iterdir() if path.is_dir())


def _official_davis_lists(root: Path) -> tuple[Path, Path] | None:
    # Handles both data/DAVIS and data/DAVIS/JPEGImages/480p as --data.
    candidates = [root, *root.parents]
    for candidate in candidates:
        split_root = candidate / "ImageSets" / "2017"
        train = split_root / "train.txt"
        val = split_root / "val.txt"
        if train.is_file() and val.is_file():
            return train, val
    return None


def resolve_sequence_splits(
    root: str | Path,
    train_list: str | Path | None = None,
    val_list: str | Path | None = None,
    val_fraction: float = 0.20,
    seed: int = 1337,
) -> tuple[list[str], list[str], str]:
    """Resolve explicit, official DAVIS, or deterministic fallback splits."""
    root = Path(root)
    available = set(discover_sequence_names(root))
    if (train_list is None) != (val_list is None):
        raise ValueError("Pass both --train-list and --val-list, or neither")

    source: str
    if train_list is not None and val_list is not None:
        train_names = read_sequence_list(train_list)
        val_names = read_sequence_list(val_list)
        source = "explicit_lists"
    else:
        official = _official_davis_lists(root)
        if official is not None:
            train_names = read_sequence_list(official[0])
            val_names = read_sequence_list(official[1])
            source = "davis_2017_official"
        else:
            names = sorted(available)
            if len(names) < 2:
                raise ValueError(
                    "At least two sequences are required for an automatic train/val "
                    "split; pass a separate --val-data root instead"
                )
            if not 0.0 < val_fraction < 1.0:
                raise ValueError("val_fraction must be in (0, 1)")
            random.Random(seed).shuffle(names)
            val_count = min(len(names) - 1, max(1, round(len(names) * val_fraction)))
            val_names = sorted(names[:val_count])
            train_names = sorted(names[val_count:])
            source = "deterministic_random"

    missing = sorted((set(train_names) | set(val_names)) - available)
    if missing:
        raise ValueError(
            "Split lists reference missing sequence directories: " + ", ".join(missing)
        )
    overlap = sorted(set(train_names) & set(val_names))
    if overlap:
        raise ValueError("Train/validation sequence overlap: " + ", ".join(overlap))
    if not train_names or not val_names:
        raise ValueError("Both train and validation splits must contain sequences")
    return train_names, val_names, source


class CleanVideoFolderDataset(Dataset):
    """DAVIS-style ``root/sequence/frame.jpg`` data with on-the-fly flicker.

    ``samples_per_epoch`` deliberately decouples optimization steps from the
    number of sequences.  A dataset with 60 DAVIS train videos can therefore
    produce hundreds or thousands of independently cropped clips per epoch.
    """

    def __init__(
        self,
        root: str | Path,
        clip_length: int = 12,
        crop_size: int = 256,
        degradation: FlickerSynthesisConfig | None = None,
        sequence_names: Iterable[str] | None = None,
        samples_per_epoch: int | None = None,
        seed: int = 1337,
        training: bool = True,
    ):
        self.root = Path(root)
        self.clip_length = int(clip_length)
        self.crop_size = int(crop_size)
        self.degradation = degradation or FlickerSynthesisConfig()
        self.degradation.validate()
        self.seed = int(seed)
        self.training = bool(training)
        self.epoch = 0
        if self.clip_length < 1:
            raise ValueError("clip_length must be >= 1")
        if self.crop_size < 16:
            raise ValueError("crop_size must be >= 16")

        selected = (
            sorted(set(sequence_names))
            if sequence_names is not None
            else discover_sequence_names(self.root)
        )
        self.sequences: list[tuple[str, list[Path]]] = []
        too_short: list[str] = []
        for name in selected:
            sequence_dir = self.root / name
            frames = sorted(
                path
                for path in sequence_dir.iterdir()
                if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
            )
            if len(frames) >= self.clip_length:
                self.sequences.append((name, frames))
            else:
                too_short.append(name)
        if not self.sequences:
            detail = f"; too short: {', '.join(too_short)}" if too_short else ""
            raise ValueError(
                f"No sequence with >= {self.clip_length} images found under "
                f"{self.root}{detail}"
            )

        default_samples = len(self.sequences)
        self.samples_per_epoch = int(samples_per_epoch or default_samples)
        if self.samples_per_epoch < 1:
            raise ValueError("samples_per_epoch must be >= 1")

    def set_epoch(self, epoch: int) -> None:
        self.epoch = int(epoch)

    def __len__(self) -> int:
        return self.samples_per_epoch

    def _sample_seed(self, index: int) -> int:
        # Large coprime multipliers keep epoch/index streams separated while
        # remaining deterministic across DataLoader worker counts.
        return self.seed + self.epoch * 1_000_003 + int(index) * 9_973

    def __getitem__(self, index: int) -> dict[str, Tensor | str]:
        sample_seed = self._sample_seed(index)
        rng = random.Random(sample_seed)
        generator = torch.Generator().manual_seed(sample_seed)
        sequence_index = rng.randrange(len(self.sequences))
        sequence_name, paths = self.sequences[sequence_index]
        start = rng.randint(0, len(paths) - self.clip_length)
        selected_paths = paths[start : start + self.clip_length]
        clean = torch.stack([_read_rgb(path) for path in selected_paths])

        _, _, height, width = clean.shape
        scale = max(self.crop_size / height, self.crop_size / width)
        if scale > 1:
            target_height = max(self.crop_size, round(height * scale))
            target_width = max(self.crop_size, round(width * scale))
            clean = F.interpolate(
                clean,
                size=(target_height, target_width),
                mode="bilinear",
                align_corners=False,
            )
            _, _, height, width = clean.shape

        if self.training:
            top = rng.randint(0, height - self.crop_size)
            left = rng.randint(0, width - self.crop_size)
        else:
            # Deterministic center crops make validation stable across epochs.
            top = (height - self.crop_size) // 2
            left = (width - self.crop_size) // 2
        clean = clean[
            :,
            :,
            top : top + self.crop_size,
            left : left + self.crop_size,
        ]
        if self.training and rng.random() < 0.5:
            clean = clean.flip(-1)

        degraded, artifact = synthesize_flicker(
            clean.unsqueeze(0),
            self.degradation,
            generator=generator,
        )
        return {
            "degraded": degraded[0],
            "clean": clean,
            "artifact": artifact[0],
            "sequence": sequence_name,
        }


def seed_data_worker(worker_id: int) -> None:
    """Seed third-party RNGs used by a DataLoader worker."""
    del worker_id
    worker_seed = torch.initial_seed() % (2**32)
    random.seed(worker_seed)
    np.random.seed(worker_seed)
