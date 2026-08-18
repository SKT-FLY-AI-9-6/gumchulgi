# -*- coding: utf-8 -*-
"""가설 검증 — 14번에서 A 가 만드는 피해는 '공간적으로 결맞은 전역 휘도 스윙'인가.

입력의 화소별 진동은 줄무늬가 지나가는 것이라 공간적으로 흩어져 있어서
프레임 평균 휘도는 거의 일정해야 한다. A 출력이 프레임 평균 휘도를 흔든다면
그게 psecore 가 LUM 0.77s 로 잡는 정체다.
"""
import os, sys
sys.path.insert(0, os.getcwd())
import cv2, numpy as np
import psecore as PC, pselive3 as P3

clip = sys.argv[1] if len(sys.argv) > 1 else "synth/14_stripes_drift_10pairs.mp4"


def read_all(p):
    cap = cv2.VideoCapture(p); fps = cap.get(cv2.CAP_PROP_FPS) or 30.0; fr = []
    while True:
        ok, f = cap.read()
        if not ok: break
        fr.append(f)
    cap.release(); return fr, fps


def lum_series(frames):
    """프레임 평균 선형 휘도 (BT.709)."""
    out = []
    for f in frames:
        lin = PC._LIN[f].astype(np.float32)          # BGR 선형광
        Y = lin[..., 0]*0.0722 + lin[..., 1]*0.7152 + lin[..., 2]*0.2126
        out.append(float(Y.mean()))
    return np.array(out)


fr, fps = read_all(clip)
rc, oc = P3.run(clip, P3.Cfg(), verbose=False)
rn, on = P3.run(clip, P3.Cfg(guard=False), verbose=False)

for label, frames in [("원본", fr), ("A(guard on)", oc), ("A(guard off)", on)]:
    y = lum_series(frames)
    d = np.abs(np.diff(y))
    print(f"{label:14} 평균휘도 {y.mean():.5f}  표준편차 {y.std():.5f}  "
          f"프레임간 최대변화 {d.max():.5f}  평균변화 {d.mean():.5f}")

print(f"\ngain: guard on  최소 {rc['gain_min']:.3f}  평균 {rc['gain_sum']/max(rc['frames'],1):.3f}")
print(f"gain: guard off 최소 {rn['gain_min']:.3f}  평균 {rn['gain_sum']/max(rn['frames'],1):.3f}")
