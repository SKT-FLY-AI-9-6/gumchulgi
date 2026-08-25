# -*- coding: utf-8 -*-
"""rawmeasure.py — **코덱을 빼고** 필터 자체의 잔여 위반을 잰다.

발견
----
같은 화소를 인코더 설정만 바꿔 저장했더니 판정이 2.42s ~ 8.96s 로 흔들렸다
(무손실 2.46s). preset/crf 에 단조성도 없다. 즉 필터가 임계 근처까지 눌러 놓으면
그 다음은 **DCT 양자화 잡음이 판정을 좌우**한다. 블록 단위 양자화는 넓은 면적이
동시에 같은 방향으로 움직이므로 psecore 의 동기화·면적 조건을 그대로 통과한다.

따라서 필터 성능은 **RGB 무손실(FFV1)** 로 저장해서 재야 한다.
"""
from __future__ import annotations
import subprocess
import numpy as np


def write_lossless(frames, path, fps):
    """FFV1 / gbrp — 크로마 서브샘플링도 양자화도 없다.

    **FFV1 은 MP4 컨테이너에 들어가지 않는다.** .mkv 만 된다.
    (mp4 로 부르면 ffmpeg 이 'Could not find tag for codec ffv1' 로 죽고,
     파이썬 쪽에는 BrokenPipeError 로만 보여서 원인을 찾기 어렵다.)
    """
    if not str(path).lower().endswith((".mkv", ".nut", ".avi")):
        raise ValueError(
            f"무손실(FFV1)은 .mkv 로만 저장됩니다. 받은 경로: {path}\n"
            f"  사람이 볼 영상이면 확장자를 .mp4 로 두고 psegpu_full.py --video 를 쓰세요.")
    H, W = frames[0].shape[:2]
    p = subprocess.Popen(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps),
         "-i", "-", "-c:v", "ffv1", "-level", "3", "-pix_fmt", "gbrp", path],
        stdin=subprocess.PIPE)
    for f in frames:
        p.stdin.write(np.ascontiguousarray(f).tobytes())
    p.stdin.close()
    p.wait()
    return path


def verify_roundtrip(frames, path):
    import cv2
    cap = cv2.VideoCapture(path)
    n, bad = 0, 0
    while True:
        ok, b = cap.read()
        if not ok:
            break
        if n < len(frames) and not np.array_equal(b, frames[n]):
            bad += 1
        n += 1
    cap.release()
    return n, bad
