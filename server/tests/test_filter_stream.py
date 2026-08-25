import subprocess

import pytest

from worker import ffmpeg
from worker.filter_stream import filter_video


def _cuda_available():
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        return False


@pytest.fixture(scope="session")
def short_audio_mp4(tmp_path_factory):
    """영상 2초 + 오디오 1초 (오디오가 더 짧은 실사 유형).

    -shortest 시절 회귀: ffmpeg 가 오디오 종료 시점에 조기 종료해
    출력이 1초로 잘리거나 BrokenPipe 가 났다 (REGRESS_0820.md 7절)."""
    p = tmp_path_factory.mktemp("clips") / "short_audio.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "color=c=gray:s=360x640:d=2:r=30",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         str(p)], check=True)
    return p


def test_short_audio_clip_keeps_full_video(short_audio_mp4, tmp_path):
    dst = tmp_path / "flt.mp4"
    n = filter_video(short_audio_mp4, dst, use_gpu=False)
    assert n >= 55                        # 2초×30fps 전체가 살아야 한다
    info = ffmpeg.probe(dst)
    assert abs(info["duration_s"] - 2.0) < 0.5


@pytest.mark.skipif(not _cuda_available(), reason="CUDA 없음 — CPU 환경")
def test_gpu_filter_flash_clip(testclips, tmp_path):
    src = tmp_path / "src.mp4"
    ffmpeg.normalize(testclips / "01_flash_5hz.mkv", src)
    dst = tmp_path / "flt_gpu.mp4"
    n = filter_video(src, dst, use_gpu=True)
    assert n > 0
    info = ffmpeg.probe(dst)
    assert info["has_video"]
    assert abs(info["duration_s"] - ffmpeg.probe(src)["duration_s"]) < 0.5


def test_filter_flash_clip(testclips, tmp_path):
    src = tmp_path / "src.mp4"
    ffmpeg.normalize(testclips / "01_flash_5hz.mkv", src)
    dst = tmp_path / "flt.mp4"
    n = filter_video(src, dst)
    assert n > 0
    info = ffmpeg.probe(dst)
    assert info["has_video"]
    assert abs(info["duration_s"] - ffmpeg.probe(src)["duration_s"]) < 0.5


def test_audio_is_kept(small_mp4, tmp_path):
    dst = tmp_path / "flt.mp4"
    filter_video(small_mp4, dst, use_gpu=False)
    import json, subprocess
    p = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json",
                        "-show_streams", str(dst)],
                       capture_output=True, text=True, check=True)
    kinds = {s["codec_type"] for s in json.loads(p.stdout)["streams"]}
    assert "audio" in kinds


def test_ffmpeg_failure_raises_runtime_error(small_mp4, tmp_path):
    """출력 경로가 없어 ffmpeg 가 실패하는 경우, 멈추지 않고 RuntimeError 로
    끝나야 한다 (stderr 파이프 drain 미비로 인한 데드락 회귀 방지)."""
    dst = tmp_path / "no_such_dir" / "flt.mp4"
    with pytest.raises(RuntimeError):
        filter_video(small_mp4, dst)
