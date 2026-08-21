import json
import subprocess


def _run(args):
    p = subprocess.run(["ffmpeg", "-y", "-v", "error", *args],
                       capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg 실패: {(p.stderr or '').strip()[:300]}")


GOP_S = 0.5      # 키프레임 간격(초). 구간 저장의 절단 단위이자 토글 전환 지연 상한


def kf_args(gop_s: float = GOP_S):
    """gop_s 마다 IDR 을 강제하는 인자.

    구간 저장(docs/구간저장-토글-설계.md)이 조각을 **무손실**(-c copy)로 잘라내려면
    절단면이 IDR 이어야 한다. 구간을 gop_s 격자로 정렬하므로 이 간격으로 키프레임을
    박아 두면 재인코딩 없이 잘린다.

    0.5 초인 이유는 용량이 아니라 **안전**이다 — 토글은 키프레임 경계에서만 갈아탈
    수 있어서, GOP 2 초면 사용자가 필터를 켜고도 최대 2 초를 더 노출한다.
    """
    return ["-force_key_frames", f"expr:gte(t,n_forced*{gop_s})"]


def normalize(src, dst, gop_s: float = GOP_S):
    """H.264/AAC mp4 표준화. 가로 720 상한, 짝수 해상도, faststart."""
    _run(["-i", str(src),
          "-vf", "scale='min(720,iw)':-2",
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
          *kf_args(gop_s),
          "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
          "-movflags", "+faststart", str(dst)])


def cut_copy(src, dst, a: float, b: float):
    """[a,b) 무손실 절단. 경계가 IDR 이라 재인코딩이 없다."""
    _run(["-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(src),
          "-c", "copy", "-avoid_negative_ts", "make_zero", str(dst)])


def concat_copy(parts, dst, workdir):
    """조각들을 무손실로 이어붙인다. parts 는 workdir 안의 Path 목록."""
    lst = workdir / "_concat.txt"
    lines = ["file " + repr(p.name) for p in parts]
    lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        _run(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(dst)])
    finally:
        lst.unlink(missing_ok=True)


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
