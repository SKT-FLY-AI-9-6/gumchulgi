import os
import subprocess
import threading
from pathlib import Path

import cv2
import numpy as np

from pselive3 import Cfg, LiveFilter3


def gpu_available() -> bool:
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        return False


_TN_MODEL = None
_TN_LAST = (None, None)          # (경로 str, 결과) — 사다리의 strong/base 2회 호출 캐시


def tn_cut_frames(src, tol: int = 2):
    """TransNetV2 사전 패스 — 샷 경계(새 샷 시작) ±tol 프레임 집합.

    필터 컷 리셋의 **거부권 게이트**용 (pselive3.Cfg.cut_frames 주석 참고).
    승격 근거: 합성 27 + 실사 209 관문 — 동일 235·개선 1·퇴보 0·악화 0.
    torch/transnetv2-pytorch 미설치 등 어떤 이유로든 실패하면 None 을 돌려
    필터는 기존 NCC+불응기 그대로 동작한다 (GPU 자동 감지와 같은 관례).
    롤백 스위치: 환경변수 TN_CUT_GATE=0.
    """
    if os.environ.get("TN_CUT_GATE", "1") != "1":
        return None
    global _TN_MODEL, _TN_LAST
    key = str(src)
    if _TN_LAST[0] == key:
        return _TN_LAST[1]
    frames = None
    try:
        import torch
        from transnetv2_pytorch import TransNetV2
        if _TN_MODEL is None:
            _TN_MODEL = TransNetV2()
            _TN_MODEL.eval()
        with torch.no_grad():
            scenes = _TN_MODEL.detect_scenes(key, threshold=0.5)
        starts = {int(s["start_frame"]) for s in scenes[1:]}
        frames = {b + d for b in starts for d in range(-tol, tol + 1)}
    except Exception:
        frames = None
    _TN_LAST = (key, frames)
    return frames


def filter_video(src, dst, cfg: Cfg | None = None,
                 use_gpu: bool | None = None) -> int:
    """cfg 로 보정본을 만든다. CUDA 가 있으면 psegpu_full, 없으면
    pselive3 스트리밍. 반환값은 처리한 프레임 수."""
    cfg = cfg or Cfg.strong()
    if getattr(cfg, "cut_frames", None) is None:
        cfg.cut_frames = tn_cut_frames(src)
    if use_gpu is None:
        use_gpu = gpu_available()
    if use_gpu:
        return _filter_gpu(src, dst, cfg)
    return _filter_cpu(src, dst, cfg)


def _filter_gpu(src, dst, cfg: Cfg) -> int:
    import psegpu_full

    try:
        rep, _ = psegpu_full.run(str(src), cfg, psegpu_full.OptF(),
                                 video_out=str(dst), lossless=False,
                                 progress=False)
    except OSError as exc:
        # ffmpeg writer 가 먼저 죽으면 stdin write 가 OSError 로 끊긴다 —
        # CPU 경로와 같은 예외 형태(RuntimeError)로 통일한다.
        raise RuntimeError(f"GPU 필터 인코딩 실패: {exc}") from exc
    n = int(rep.get("frames", 0))
    p = Path(dst)
    if n == 0 or not p.exists() or p.stat().st_size == 0:
        raise RuntimeError(f"GPU 필터가 출력을 만들지 못했습니다: {dst}")
    return n


def _filter_cpu(src, dst, cfg: Cfg) -> int:
    """pselive3 를 스트리밍으로 적용. 메모리 O(1).

    pselive3.run() 과 같은 알고리즘·같은 인코딩 인자이지만 프레임을
    버퍼링하지 않고 ffmpeg stdin 으로 바로 흘린다. 오디오는 src 에서 copy.
    """
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise RuntimeError(f"영상을 열 수 없습니다: {src}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    s = cfg.short_side / min(W, H) if min(W, H) > cfg.short_side else 1.0
    aw, ah = max(2, int(W * s)), max(2, int(H * s))
    live = LiveFilter3(fps, (ah, aw), cfg)

    # 오디오는 영상 길이까지만 복사한다(입력측 -t). -shortest 를 쓰면
    # 오디오가 영상보다 짧은 클립에서 ffmpeg 가 조기 종료해 영상 꼬리가
    # 잘리거나 stdin 파이프가 끊긴다 (REGRESS_0820.md 7절).
    a_limit = (["-t", f"{total / fps:.3f}"] if total > 0 and fps > 0 else [])
    p = subprocess.Popen(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
         "-r", str(fps), "-i", "-",
         *a_limit, "-i", str(src), "-map", "0:v:0", "-map", "1:a:0?",
         "-c:a", "copy",
         "-sws_flags", "bicubic+accurate_rnd+full_chroma_int",
         "-c:v", "libx264", "-preset", "medium", "-crf", "16",
         "-pix_fmt", "yuv420p", "-colorspace", "bt709",
         "-color_primaries", "bt709", "-color_trc", "bt709",
         "-movflags", "+faststart", str(dst)],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    # ffmpeg 의 stderr 를 계속 비워두지 않으면 OS 파이프 버퍼가 가득 찼을 때
    # ffmpeg 가 stderr 쓰기에서 멈추고 → stdin 읽기도 멈춰 p.stdin.write() 가
    # 영원히 블록될 수 있다. 별도 스레드로 병행 drain 한다. (최근 ~300바이트만
    # 보관하면 충분하므로 무한정 쌓이지 않도록 잘라낸다.)
    err_buf = bytearray()

    def _drain_stderr():
        for chunk in iter(lambda: p.stderr.read(4096), b""):
            err_buf.extend(chunk)
            del err_buf[:-300]

    err_thread = threading.Thread(target=_drain_stderr, daemon=True)
    err_thread.start()

    n = 0
    try:
        while True:
            ok, f = cap.read()
            if not ok:
                break
            sm = (cv2.resize(f, (aw, ah), interpolation=cv2.INTER_AREA)
                  if s != 1.0 else f)
            g = live.push(f, sm)
            try:
                p.stdin.write(np.ascontiguousarray(g).tobytes())
            except OSError:
                # ffmpeg 가 먼저 죽어 파이프가 끊긴 경우. 종료 코드는
                # 아래 finally 에서 확인해 RuntimeError 로 통일한다.
                break
            n += 1
    finally:
        cap.release()
        try:
            p.stdin.close()
        except OSError:
            pass
        err_thread.join()
        rc = p.wait()
        if rc != 0:
            err = bytes(err_buf).decode(errors="replace")
            raise RuntimeError(f"ffmpeg 인코딩 실패: {err[:300]}")
    if n == 0:
        raise RuntimeError("프레임을 하나도 읽지 못했습니다")
    return n
