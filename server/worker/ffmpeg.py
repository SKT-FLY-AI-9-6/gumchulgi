import json
import subprocess


def _run(args):
    p = subprocess.run(["ffmpeg", "-y", "-v", "error", *args],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg 실패: {p.stderr.strip()[:300]}")


def normalize(src, dst):
    """H.264/AAC mp4 표준화. 가로 720 상한, 짝수 해상도, faststart."""
    _run(["-i", str(src),
          "-vf", "scale='min(720,iw)':-2",
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
          "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
          "-movflags", "+faststart", str(dst)])


def thumbnail(src, dst):
    try:
        _run(["-ss", "0.5", "-i", str(src), "-frames:v", "1",
              "-vf", "scale=360:-2", str(dst)])
    except RuntimeError:
        _run(["-i", str(src), "-frames:v", "1",
              "-vf", "scale=360:-2", str(dst)])


def probe(path) -> dict:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, encoding='utf-8', errors='ignore')
    if p.returncode != 0:
        err_msg = (p.stderr or "").strip()[:200]
        raise ValueError(f"ffprobe 실패: {err_msg}")
    info = json.loads(p.stdout)
    vstreams = [s for s in info.get("streams", [])
                if s.get("codec_type") == "video"]
    if not vstreams:
        return {"duration_s": 0.0, "width": 0, "height": 0, "has_video": False}
    v = vstreams[0]
    dur = float(info.get("format", {}).get("duration") or 0.0)
    return {"duration_s": dur, "width": int(v.get("width", 0)),
            "height": int(v.get("height", 0)), "has_video": True}
