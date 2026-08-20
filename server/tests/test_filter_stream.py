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
