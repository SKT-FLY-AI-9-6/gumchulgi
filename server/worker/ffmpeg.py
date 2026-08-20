import json
import subprocess


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
