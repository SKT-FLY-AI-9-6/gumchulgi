import pytest
from worker import ffmpeg


def test_normalize_and_thumbnail(small_mp4, tmp_path):
    out = tmp_path / "norm.mp4"
    ffmpeg.normalize(small_mp4, out)
    info = ffmpeg.probe(out)
    assert info["has_video"] and info["width"] <= 720
    assert abs(info["duration_s"] - 2.0) < 0.5

    th = tmp_path / "t.jpg"
    ffmpeg.thumbnail(out, th)
    assert th.stat().st_size > 100


def test_normalize_nonexistent_path(tmp_path):
    """normalize on nonexistent input path must raise RuntimeError."""
    nonexistent = tmp_path / "nonexistent.mp4"
    out = tmp_path / "output.mp4"
    with pytest.raises(RuntimeError):
        ffmpeg.normalize(nonexistent, out)
