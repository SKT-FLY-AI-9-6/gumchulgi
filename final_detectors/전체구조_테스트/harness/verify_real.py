# -*- coding: utf-8 -*-
"""실사 클립으로 psegpu_full 을 검증한다 — verify_full.py 의 실사판.

27클립 코퍼스는 합성 위주(실사 4편)라 거기서 얻은 '악화 0' 이 실제 영상에서도
버티는지 확인해야 한다. 특히 페더 0 은 스윕이 비단조라 그 코퍼스 최적이
일반화한다는 보장이 없다.
"""
import os, sys, glob
sys.path.insert(0, os.getcwd())
import cv2, numpy as np
import psecore as PC, pseenv as ENV, pselive3 as P3, rawmeasure as RM
import psegpu_full as PGF
import torch

SRC = sys.argv[1] if len(sys.argv) > 1 else "_yt"


def hf(fr):
    v = []
    for f in fr:
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32)
        v.append(float(np.abs(g - cv2.GaussianBlur(g, (0, 0), 2.0)).mean()))
    return float(np.mean(v)) if v else 1.0


def read_all(p):
    cap = cv2.VideoCapture(p); fps = cap.get(cv2.CAP_PROP_FPS) or 30.0; fr = []
    while True:
        ok, f = cap.read()
        if not ok: break
        fr.append(f)
    cap.release(); return fr, fps


def judge(frames, fps, tag):
    p = ENV.tmp(f"vr_{tag}.mkv")
    RM.write_lossless(frames, p, fps)
    r = PC.analyze(p, PC.PROFILES["bt1702"])
    os.remove(p)
    return sum(r.channel_seconds().values()), r.verdict


print(f"torch {torch.__version__}  {torch.cuda.get_device_name(0)}\n")
files = sorted(glob.glob(os.path.join(SRC, "*.mp4")))
print(f"{'클립':<20}{'해상도':>11}{'원본':>8}{'CPU':>8}{'GPU':>8}"
      f"{'선명도':>8}{'CPU ms':>8}{'GPU ms':>8}  판정")
n_ok = n_bad = n_worse = 0
rows = []
for f in files:
    fr, fps = read_all(f)
    if not fr:
        continue
    H, W = fr[0].shape[:2]
    v0, _ = judge(fr, fps, "0")
    rc, oc = P3.run(f, P3.Cfg(), verbose=False)
    vc, dc = judge(oc, fps, "c")
    try:
        rg, og = PGF.run(f, P3.Cfg(), PGF.OptF(), warmup=4)
    except Exception as e:
        print(f"{os.path.basename(f):<20}  실패: {type(e).__name__}: {e}")
        n_bad += 1
        continue
    vg, dg = judge(og, fps, "g")
    worse = vg > v0 + 1e-9
    same = (dg == dc)
    n_ok += int(same and not worse); n_bad += int(not same); n_worse += int(worse)
    mark = ("  <- 악화" if worse else "") + ("" if same else f"  <- CPU와 다름({dc}->{dg})")
    print(f"{os.path.basename(f)[:18]:<20}{W}x{H:<6}{v0:>8.2f}{vc:>8.2f}{vg:>8.2f}"
          f"{hf(og)/max(hf(fr),1e-9)*100:>7.0f}%{rc['ms_per_frame']:>8.1f}"
          f"{rg['ms_per_frame']:>8.1f}  {dg}{mark}", flush=True)
    rows.append((os.path.basename(f), W, H, v0, vc, vg, rc['ms_per_frame'],
                 rg['ms_per_frame']))

print(f"\n실사 {len(rows)}편 — CPU와 판정 일치 {n_ok} / 불일치 {n_bad} / 악화 {n_worse}")
if rows:
    a = np.array([[r[6], r[7]] for r in rows])
    print(f"속도 평균  CPU {a[:,0].mean():.1f} ms  GPU {a[:,1].mean():.1f} ms  "
          f"({a[:,0].mean()/a[:,1].mean():.1f}배)")
import csv
with open("validation/verify_real_yt.csv", "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.writer(fh)
    w.writerow(["clip", "w", "h", "before_s", "cpu_s", "gpu_s", "cpu_ms", "gpu_ms"])
    w.writerows(rows)
print("CSV -> validation/verify_real_yt.csv")
