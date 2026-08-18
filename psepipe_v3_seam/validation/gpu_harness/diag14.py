# -*- coding: utf-8 -*-
"""14번 악화 진단 — 안전한 원본을 A 필터가 위반으로 만든다.
어느 규칙·어느 축이 떨어지는지, 원본/CPU출력/GPU출력을 나란히 잰다."""
import os, sys
sys.path.insert(0, os.getcwd())
import cv2, numpy as np
import psecore as PC, pseenv as ENV, pselive3 as P3, rawmeasure as RM
import pse_bt1702 as BT, psepipe as PP, tier as T

clip = sys.argv[1] if len(sys.argv) > 1 else "synth/14_stripes_drift_10pairs.mp4"


def read_all(p):
    cap = cv2.VideoCapture(p); fps = cap.get(cv2.CAP_PROP_FPS) or 30.0; fr = []
    while True:
        ok, f = cap.read()
        if not ok: break
        fr.append(f)
    cap.release(); return fr, fps


def save(frames, fps, path):
    RM.write_lossless(frames, path, fps)
    return path


fr, fps = read_all(clip)
print(f"{os.path.basename(clip)}  {len(fr)}프레임 {fps:.1f}fps  {fr[0].shape}")

# CPU 기준판 출력
rc, oc = P3.run(clip, P3.Cfg(), verbose=False)
p_cpu = ENV.tmp("d14_cpu.mkv"); save(oc, fps, p_cpu)

for label, path in [("원본", clip), ("A(CPU)", p_cpu)]:
    r = BT.analyze(path, width=320)
    t, why = T.tier(r)
    print(f"\n--- {label}: {t}  실패규칙 {r['failed_rules'] or '없음'}")
    for n, m, l, act in PP.axes(r):
        if l:
            print(f"      {n:<10}{m:9.2f} / {l:7.2f} = {m/l*100:6.1f}%   작동기 {act}")

# psecore 쪽 채널 초 (verify_full 이 쓰는 자)
for label, path in [("원본", clip), ("A(CPU)", p_cpu)]:
    r = PC.analyze(path, PC.PROFILES["bt1702"])
    ch = r.channel_seconds()
    print(f"{label:8} psecore {r.verdict}  채널초 { {k: round(v,2) for k,v in ch.items()} }")

os.remove(p_cpu)
