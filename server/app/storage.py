from pathlib import Path

from app.config import settings


def video_dir(vid: int) -> Path:
    d = settings.DATA_DIR / "media" / str(vid)
    d.mkdir(parents=True, exist_ok=True)
    return d


def upload_path(vid: int, suffix: str) -> Path:
    return video_dir(vid) / f"upload{suffix}"


def original_path(vid: int) -> Path:
    return video_dir(vid) / "original.mp4"


def filtered_path(vid: int) -> Path:
    return video_dir(vid) / "filtered.mp4"


def thumb_path(vid: int) -> Path:
    return video_dir(vid) / "thumb.jpg"


def report_path(vid: int) -> Path:
    return video_dir(vid) / "report.json"
