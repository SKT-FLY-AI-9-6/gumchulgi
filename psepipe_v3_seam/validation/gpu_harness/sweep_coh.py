# -*- coding: utf-8 -*-
"""부호 일관성 게이트 스윕 — 잔상과 위반 제거를 **동시에** 본다.

목표는 둘 다다: 잔상(drag)을 줄이면서 위반 제거율은 지키고 악화는 0.
한 축만 보면 다른 축을 잃는다.
"""
import os, sys, glob
sys.path.insert(0, os.getcwd())
import cv2, numpy as np
import psecore as PC, pseenv as ENV, pselive3 as P3, rawmeasure as RM
import psegpu_full as PGF

VIOL = ["_dfull/cera_khin_360.mp4", "_dfull/travis_fein_360.mp4",
        "_yt/TXeDgXiytM0.mp4", "_yt/Y76O5wY7EcM.mp4", "_yt/xbawhCyMsRI.mp4"]
SAFE = ["_yt/ila-hAUXR5U.mp4", "_yt/kMJVNerOtRI.mp4", "_yt/4UEAYxGC1gE.mp4",
        "_ig_safe/Db1-YyQJh6m.mp4", "_ig_safe/Db10sPmutPf.mp4"]
SAFE = [p for p in SAFE if os.path.exists(p)]
GATES = [0.0, 0.3, 0.5, 0.7, 1.0]


def read_gray(p):
    cap = cv2.VideoCapture(p); fr = []
    while True:
        ok, f = cap.read()
        if not ok: break
        fr.append(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32))
    cap.release(); return fr


def read_all(p):
    cap = cv2.VideoCapture(p); fps = cap.get(cv2.CAP_PROP_FPS) or 30.0; fr = []
    while True:
        ok, f = cap.read()
        if not ok: break
        fr.append(f)
    cap.release(); return fr, fps


def judge(frames, fps):
    q = ENV.tmp("sc.mkv"); RM.write_lossless(frames, q, fps)
    r = PC.analyze(q, PC.PROFILES["bt1702"]); os.remove(q)
    return sum(r.channel_seconds().values())


def drag(inp, out):
    n = min(len(inp), len(out)); v = []
    for t in range(1, n):
        mo = np.abs(inp[t] - inp[t - 1]); m = mo > 6.0
        if m.sum() < 100: continue
        v.append(float(np.abs(out[t][m] - inp[t][m]).mean() / (mo[m].mean() + 1e-6)))
    return float(np.mean(v)) if v else 0.0


print("원본 판정 중...", flush=True)
base, gray = {}, {}
for p in VIOL + SAFE:
    fr, fps = read_all(p)
    base[p] = (judge(fr, fps), fps)
    gray[p] = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32) for f in fr]
print(f"  위반 {sum(1 for p in VIOL if base[p][0]>1e-9)}편, 안전 {len(SAFE)}편\n", flush=True)

print(f"{'coh_gate':>9}{'평균제거%':>10}{'평균drag':>10}{'악화':>6}   클립별 제거율")
for g in GATES:
    cfg = P3.Cfg(); cfg.coh_gate = g
    rem, dr, worse, per = [], [], 0, []
    for p in VIOL + SAFE:
        v0, fps = base[p]
        rg, og = PGF.run(p, cfg, PGF.OptF(), warmup=2)
        v1 = judge(og, fps)
        if v1 > v0 + 1e-9: worse += 1
        if v0 > 1e-9:
            r = (1 - v1 / v0) * 100; rem.append(r); per.append(f"{r:.0f}%")
        og_g = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32) for f in og]
        dr.append(drag(gray[p], og_g))
    print(f"{g:>9.1f}{np.mean(rem):>9.1f}%{np.mean(dr):>10.3f}{worse:>6}   {' '.join(per)}",
          flush=True)
