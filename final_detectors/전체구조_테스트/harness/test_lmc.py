# -*- coding: utf-8 -*-
"""국소 움직임 보상(블록매칭) 효과 측정 — 네 축을 한 번에.

  drag    잔상 (낮을수록 좋음)  <- 이걸 잡으려고 만든 것
  제거율  위반 제거 (높을수록)   <- 이게 떨어지면 실패
  악화    안전한 원본을 위반으로 (0 이어야 함)
  ms      프레임당 시간 (실시간 33ms 안이어야 함)
"""
import os, sys
sys.path.insert(0, os.getcwd())
import cv2, numpy as np
import psecore as PC, pseenv as ENV, pselive3 as P3, rawmeasure as RM
import psegpu_full as PGF

VIOL = ["_dfull/cera_khin_360.mp4", "_dfull/travis_fein_360.mp4",
        "_yt/TXeDgXiytM0.mp4", "_yt/xbawhCyMsRI.mp4"]
SAFE = ["_yt/ila-hAUXR5U.mp4", "_yt/kMJVNerOtRI.mp4",
        "_ig_safe/Db1-YyQJh6m.mp4"]
SAFE = [p for p in SAFE if os.path.exists(p)]


def read_all(p):
    cap = cv2.VideoCapture(p); fps = cap.get(cv2.CAP_PROP_FPS) or 30.0; fr = []
    while True:
        ok, f = cap.read()
        if not ok: break
        fr.append(f)
    cap.release(); return fr, fps


def judge(frames, fps):
    q = ENV.tmp("lmc.mkv"); RM.write_lossless(frames, q, fps)
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
print(f"  위반 {sum(1 for p in VIOL if base[p][0]>1e-9)}편  안전 {len(SAFE)}편\n", flush=True)

CFGS = [("끔 (현재)", dict(local_mc=False)),
        ("blk16 r8 s2 gain.15", dict(local_mc=True)),
        ("blk16 r8 s2 gain.05", dict(local_mc=True, lmc_min_gain=0.05)),
        ("blk8  r8 s2 gain.15", dict(local_mc=True, lmc_block=8)),
        ("blk16 r12 s2 gain.15", dict(local_mc=True, lmc_radius=12))]

print(f"{'설정':<22}{'평균제거%':>10}{'평균drag':>10}{'악화':>6}{'ms/frame':>10}")
for name, kw in CFGS:
    cfg = P3.Cfg()
    for k, v in kw.items():
        setattr(cfg, k, v)
    rem, dr, worse, ms = [], [], 0, []
    for p in VIOL + SAFE:
        v0, fps = base[p]
        try:
            rg, og = PGF.run(p, cfg, PGF.OptF(), warmup=2)
        except Exception as e:
            print(f"   {os.path.basename(p)} 오류 {type(e).__name__}: {str(e)[:70]}")
            continue
        v1 = judge(og, fps)
        if v1 > v0 + 1e-9: worse += 1
        if v0 > 1e-9: rem.append((1 - v1 / v0) * 100)
        og_g = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32) for f in og]
        dr.append(drag(gray[p], og_g)); ms.append(rg["ms_per_frame"])
    if rem:
        print(f"{name:<22}{np.mean(rem):>9.1f}%{np.mean(dr):>10.3f}{worse:>6}"
              f"{np.mean(ms):>10.1f}", flush=True)
