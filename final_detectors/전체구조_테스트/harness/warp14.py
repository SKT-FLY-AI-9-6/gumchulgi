# -*- coding: utf-8 -*-
"""GPU 14번 잔여 악화 — 움직임 보상 부재가 원인인지 확인한다.

CPU 는 phaseCorrelate 로 (부정확하게라도) 워프를 걸어 줄무늬 흐름이 d 에서
상쇄된다. GPU 는 봉우리 비 게이트가 주기 패턴을 기각해 warped=0 이라 그 흐름을
전부 플래시로 받는다 — 가설이 맞다면 게이트를 열수록 위반이 줄어야 한다.
"""
import os, sys
sys.path.insert(0, os.getcwd())
import cv2
import psecore as PC, pseenv as ENV, pselive3 as P3, rawmeasure as RM
import psegpu_full as PGF

clip = sys.argv[1] if len(sys.argv) > 1 else "synth/14_stripes_drift_10pairs.mp4"
cap = cv2.VideoCapture(clip); fps = cap.get(cv2.CAP_PROP_FPS) or 30.0; fr = []
while True:
    ok, f = cap.read()
    if not ok: break
    fr.append(f)
cap.release()


def judge(frames):
    p = ENV.tmp("w14.mkv"); RM.write_lossless(frames, p, fps)
    r = PC.analyze(p, PC.PROFILES["bt1702"]); os.remove(p)
    return sum(r.channel_seconds().values()), r.verdict


v0, d0 = judge(fr)
print(f"{os.path.basename(clip)}  원본 {v0:.2f}s {d0}\n")
print(f"{'peak_ratio_min':>15}{'warped':>8}{'초':>8}  판정")
for pr in [1.35, 1.20, 1.10, 1.00, 0.0]:
    o = PGF.OptF(); o.peak_ratio_min = pr
    rg, og = PGF.run(clip, P3.Cfg(), o, warmup=2)
    v, d = judge(og)
    mark = "  <- 악화" if v > v0 + 1e-9 else ""
    print(f"{pr:>15.2f}{rg['warped']:>8}{v:>8.2f}  {d}{mark}", flush=True)

# 참고: motion_comp 자체를 끄면?
cfg = P3.Cfg(); cfg.motion_comp = False
rg, og = PGF.run(clip, cfg, PGF.OptF(), warmup=2)
v, d = judge(og)
print(f"{'motion_comp off':>15}{rg['warped']:>8}{v:>8.2f}  {d}")
