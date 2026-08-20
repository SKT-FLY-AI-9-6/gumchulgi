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
