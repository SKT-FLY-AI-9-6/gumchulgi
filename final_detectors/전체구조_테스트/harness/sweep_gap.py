# -*- coding: utf-8 -*-
"""불응기 간격(cut_min_gap_s) 스윕.

0.2 초는 "아무리 빠른 편집도 초당 5 회를 넘지 않는다"는 물리적 근거로 고른
값이지 스윕으로 찾은 최적값이 아니다. 더 길게 하면 헛컷을 더 막지만 진짜 컷을
더 놓치고, 짧게 하면 그 반대다.

유튜브 24편(위반 16 + 안전 8)으로 잰다. 원본 판정은 한 번만 하고 재사용한다.
"""
import os, sys, glob, csv, time
sys.path.insert(0, os.getcwd())
import cv2, numpy as np
import psecore as PC, pseenv as ENV, pselive3 as P3, rawmeasure as RM
import psegpu_full as PGF

GAPS = [0.0, 0.1, 0.15, 0.2, 0.3, 0.5]
files = sorted(glob.glob("_yt/*.mp4"))


def read_all(p):
    cap = cv2.VideoCapture(p); fps = cap.get(cv2.CAP_PROP_FPS) or 30.0; fr = []
    while True:
        ok, f = cap.read()
        if not ok: break
        fr.append(f)
    cap.release(); return fr, fps


def judge(frames, fps, tag):
    q = ENV.tmp(f"sg_{tag}.mkv"); RM.write_lossless(frames, q, fps)
    r = PC.analyze(q, PC.PROFILES["bt1702"]); os.remove(q)
    return sum(r.channel_seconds().values())


print("원본 판정 중...", flush=True)
base = {}
for f in files:
    fr, fps = read_all(f)
    base[f] = (judge(fr, fps, "0"), fps)
viol = [f for f in files if base[f][0] > 1e-9]
safe = [f for f in files if base[f][0] <= 1e-9]
print(f"  위반 {len(viol)}편  안전 {len(safe)}편\n", flush=True)

rows = []
print(f"{'간격':>6}{'평균제거%':>10}{'완전제거':>9}{'악화':>6}{'평균컷':>8}  잔여 큰 클립")
for g in GAPS:
    cfg = P3.Cfg(); cfg.cut_min_gap_s = g
    rem, cuts, worse, full, resid = [], [], 0, 0, []
    for f in files:
        v0, fps = base[f]
        try:
            rg, og = PGF.run(f, cfg, PGF.OptF(), warmup=2)
            v1 = judge(og, fps, "g")
        except Exception as e:
            print(f"   {os.path.basename(f)} 오류 {type(e).__name__}"); continue
        cuts.append(rg["cuts"])
        if v1 > v0 + 1e-9:
            worse += 1
        if v0 > 1e-9:
            r = (1 - v1 / v0) * 100
            rem.append(r)
            if r >= 99.5:
                full += 1
            elif v1 > 5.0:
                resid.append(f"{os.path.basename(f)[:12]}({r:.0f}%)")
        rows.append({"gap": g, "clip": os.path.basename(f), "before": round(v0, 2),
                     "after": round(v1, 2), "cuts": rg["cuts"]})
    print(f"{g:>6.2f}{np.mean(rem):>9.1f}%{full:>6}/{len(viol)}{worse:>6}"
          f"{np.mean(cuts):>8.0f}  {', '.join(resid[:4]) or '-'}", flush=True)
    with open("validation/sweep_gap.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
print("\nCSV -> validation/sweep_gap.csv")
