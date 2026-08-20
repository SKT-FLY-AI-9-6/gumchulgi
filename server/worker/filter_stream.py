import subprocess

import cv2
import numpy as np

from pselive3 import Cfg, LiveFilter3


def filter_video(src, dst, cfg: Cfg | None = None) -> int:
    """pselive3 STRONG 을 스트리밍으로 적용. 메모리 O(1).

    pselive3.run() 과 같은 알고리즘·같은 인코딩 인자이지만 프레임을
    버퍼링하지 않고 ffmpeg stdin 으로 바로 흘린다. 오디오는 src 에서 copy.
    """
    cfg = cfg or Cfg.strong()
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise RuntimeError(f"영상을 열 수 없습니다: {src}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    s = cfg.short_side / min(W, H) if min(W, H) > cfg.short_side else 1.0
    aw, ah = max(2, int(W * s)), max(2, int(H * s))
    live = LiveFilter3(fps, (ah, aw), cfg)

    p = subprocess.Popen(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
         "-r", str(fps), "-i", "-",
         "-i", str(src), "-map", "0:v:0", "-map", "1:a:0?",
         "-c:a", "copy", "-shortest",
         "-sws_flags", "bicubic+accurate_rnd+full_chroma_int",
         "-c:v", "libx264", "-preset", "medium", "-crf", "16",
         "-pix_fmt", "yuv420p", "-colorspace", "bt709",
         "-color_primaries", "bt709", "-color_trc", "bt709",
         "-movflags", "+faststart", str(dst)],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    n = 0
    try:
        while True:
            ok, f = cap.read()
            if not ok:
                break
            sm = (cv2.resize(f, (aw, ah), interpolation=cv2.INTER_AREA)
                  if s != 1.0 else f)
            g = live.push(f, sm)
            p.stdin.write(np.ascontiguousarray(g).tobytes())
            n += 1
    finally:
        cap.release()
        p.stdin.close()
        err = p.stderr.read().decode(errors="replace")
        if p.wait() != 0:
            raise RuntimeError(f"ffmpeg 인코딩 실패: {err[:300]}")
    if n == 0:
        raise RuntimeError("프레임을 하나도 읽지 못했습니다")
    return n
