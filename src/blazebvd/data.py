from __future__ import annotations

import random
from pathlib import Path

import cv2
import torch
import torch.nn.functional as F
from torch import Tensor
from torch.utils.data import Dataset

from .degradation import FlickerSynthesisConfig, synthesize_flicker

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def _read_rgb(path: Path) -> Tensor:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Could not read image: {path}")
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    return torch.from_numpy(image.copy()).permute(2, 0, 1).float().div(255)


class CleanVideoFolderDataset(Dataset):
    """DAVIS-style root/sequence/frame.jpg dataset with on-the-fly flicker."""

    def __init__(
        self,
        root: str | Path,
        clip_length: int = 12,
        crop_size: int = 256,
        degradation: FlickerSynthesisConfig | None = None,
    ):
        self.root = Path(root)
        self.clip_length = clip_length
        self.crop_size = crop_size
        self.degradation = degradation or FlickerSynthesisConfig()
        self.sequences: list[list[Path]] = []
        for sequence_dir in sorted(path for path in self.root.iterdir() if path.is_dir()):
            frames = sorted(
                p for p in sequence_dir.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS
            )
            if len(frames) >= clip_length:
                self.sequences.append(frames)
        if not self.sequences:
            raise ValueError(
                f"No sequence with >= {clip_length} images found under {self.root}"
            )

    def __len__(self) -> int:
        return len(self.sequences)

    def __getitem__(self, index: int) -> dict[str, Tensor]:
        paths = self.sequences[index]
        start = random.randint(0, len(paths) - self.clip_length)
        clean = torch.stack([_read_rgb(p) for p in paths[start : start + self.clip_length]])
        _, _, h, w = clean.shape
        scale = max(self.crop_size / h, self.crop_size / w)
        if scale > 1:
            clean = F.interpolate(
                clean, scale_factor=scale, mode="bilinear", align_corners=False
            )
            _, _, h, w = clean.shape
        top = random.randint(0, h - self.crop_size)
        left = random.randint(0, w - self.crop_size)
        clean = clean[:, :, top : top + self.crop_size, left : left + self.crop_size]
        if random.random() < 0.5:
            clean = clean.flip(-1)
        degraded, artifact = synthesize_flicker(clean.unsqueeze(0), self.degradation)
        return {"degraded": degraded[0], "clean": clean, "artifact": artifact[0]}
