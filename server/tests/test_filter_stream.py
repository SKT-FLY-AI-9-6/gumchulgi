import pytest

from worker import ffmpeg
from worker.filter_stream import filter_video


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
    filter_video(small_mp4, dst)
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
