# -*- coding: utf-8 -*-
"""make_sbs.py — 비교 영상(사이드바이사이드) 제작.

여러 보정본을 원본과 나란히 붙여 라벨을 얹는다. 발표·설문 자극 제작용.
2026-08-14 합성 5클립 3파전 비교 영상을 만든 스크립트의 재사용판.

사용:
    python make_sbs.py 출력.mp4 "ORIGINAL=원본.mp4" "A (ours)=보정A.mp4" \
                       "A->D=체인출력.mp4" [--height 480]

주의: 라벨은 ASCII 권장 (환경에 따라 한글 폰트가 없어 깨질 수 있음).
출력은 libx264 CRF18 — 판정 측정용이 아니라 눈 비교용이다. 판정 수치는
반드시 무손실(rawmeasure)로 잴 것.
"""
from __future__ import annotations
import argparse
import os
import subprocess
import tempfile

import cv2
import numpy as np


def build(out_path: str, arms: list[tuple[str, str]], height: int = 480) -> str:
    caps = [cv2.VideoCapture(p) for _, p in arms]
    for (_, p), c in zip(arms, caps):
        if not c.isOpened():
            raise IOError(p)
    fps = caps[0].get(cv2.CAP_PROP_FPS) or 30.0
    # 패널 폭은 첫 영상 비율 기준
    w0 = int(caps[0].get(cv2.CAP_PROP_FRAME_WIDTH))
    h0 = int(caps[0].get(cv2.CAP_PROP_FRAME_HEIGHT))
    pw = max(2, int(round(height * w0 / max(h0, 1))))
    gap, bar = 4, 36

    frames = []
    while True:
        panels = []
        for c in caps:
            ok, f = c.read()
            if not ok:
                panels = None
                break
            panels.append(cv2.resize(f, (pw, height)))
        if panels is None:
            break
        row = []
        for i, f in enumerate(panels):
            row.append(f)
            if i < len(panels) - 1:
                row.append(np.full((height, gap, 3), 24, np.uint8))
        body = np.hstack(row)
        img = np.vstack([np.full((bar, body.shape[1], 3), 24, np.uint8), body])
        for i, (label, _) in enumerate(arms):
            cv2.putText(img, label, (i * (pw + gap) + 8, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2,
                        cv2.LINE_AA)
        frames.append(img)
    for c in caps:
        c.release()
    if not frames:
        raise RuntimeError("프레임 없음 — 입력 확인")

    h, w = frames[0].shape[:2]
    tmp = os.path.join(tempfile.gettempdir(), "_sbs_raw.mp4")
    vw = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for f in frames:
        vw.write(f)
    vw.release()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp,
                    "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                    out_path], check=True)
    os.remove(tmp)
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="비교 영상(사이드바이사이드) 제작")
    ap.add_argument("output")
    ap.add_argument("arms", nargs="+", help='"라벨=영상경로" 쌍 (2개 이상)')
    ap.add_argument("--height", type=int, default=480)
    a = ap.parse_args()
    arms = []
    for s in a.arms:
        if "=" not in s:
            ap.error(f'"라벨=경로" 형식이어야 합니다: {s}')
        label, path = s.split("=", 1)
        arms.append((label, path))
    print("->", build(a.output, arms, a.height))
