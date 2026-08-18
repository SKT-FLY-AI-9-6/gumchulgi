# -*- coding: utf-8 -*-
"""CPU(0.00) 와 GPU(1.14) 가 14번에서 어디서 갈라지는지 수치로 잡는다.

추측을 멈추고 출력 자체를 프레임 단위로 비교한다.
"""
import os, sys
sys.path.insert(0, os.getcwd())
import cv2, numpy as np
import psecore as PC, pselive3 as P3, psegpu_full as PGF

clip = sys.argv[1] if len(sys.argv) > 1 else "synth/14_stripes_drift_10pairs.mp4"
cap = cv2.VideoCapture(clip); fps = cap.get(cv2.CAP_PROP_FPS) or 30.0; fr = []
while True:
    ok, f = cap.read()
    if not ok: break
    fr.append(f)
cap.release()

cfg = P3.Cfg()
_, oc = P3.run(clip, cfg, verbose=False)
_, og = PGF.run(clip, cfg, PGF.OptF(), warmup=2)


def lum(frames):
    out = []
    for f in frames:
        lin = PC._LIN[f].astype(np.float32)
        out.append(float((lin[..., 0]*0.0722 + lin[..., 1]*0.7152
                          + lin[..., 2]*0.2126).mean()))
    return np.array(out)


yi, yc, yg = lum(fr), lum(oc), lum(og)
for lab, y in [("원본", yi), ("CPU", yc), ("GPU", yg)]:
    d = np.abs(np.diff(y))
    print(f"{lab:5} 평균 {y.mean():.5f}  표준편차 {y.std():.5f}  "
          f"프레임간 최대 {d.max():.5f}  평균 {d.mean():.5f}")

# 프레임별 |출력 - 원본| 차이가 가장 큰 지점
dc = np.abs(np.stack([cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float32)
                      - cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float32)
                      for a, b in zip(oc, fr)])).mean(axis=(1, 2))
dg = np.abs(np.stack([cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float32)
                      - cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float32)
                      for a, b in zip(og, fr)])).mean(axis=(1, 2))
print(f"\n원본 대비 평균 절대차 (8비트)  CPU {dc.mean():.2f}  GPU {dg.mean():.2f}")
print(f"  CPU 최대 {dc.max():.2f} (프레임 {int(dc.argmax())})"
      f"   GPU 최대 {dg.max():.2f} (프레임 {int(dg.argmax())})")

# CPU 와 GPU 출력끼리의 차이
dcg = np.abs(np.stack([cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float32)
                       - cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float32)
                       for a, b in zip(oc, og)])).mean(axis=(1, 2))
print(f"CPU vs GPU 출력 평균 절대차 {dcg.mean():.2f}  최대 {dcg.max():.2f} "
      f"(프레임 {int(dcg.argmax())})")
