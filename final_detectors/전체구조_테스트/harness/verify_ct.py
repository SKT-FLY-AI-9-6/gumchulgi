# -*- coding: utf-8 -*-
"""verify_full.py 를 cut_thresh 를 바꿔가며 전수로 돌린다.
verify_full.py 본체는 건드리지 않는다 (리포 오염 방지)."""
import os, sys, glob
sys.path.insert(0, os.getcwd())
import cv2, numpy as np
import psecore as PC, pseenv as ENV, pselive3 as P3, rawmeasure as RM
import psegpu_full as PGF
import torch

CT = float(sys.argv[1]) if len(sys.argv) > 1 else 0.20

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
    p = ENV.tmp(f"vct_{tag}.mkv")
    RM.write_lossless(frames, p, fps)
    r = PC.analyze(p, PC.PROFILES["bt1702"])
    os.remove(p)
    return sum(r.channel_seconds().values()), r.verdict

print(f"torch {torch.__version__}  {torch.cuda.get_device_name(0)}   cut_thresh={CT}\n")
files = sorted(glob.glob("synth/*.mp4")) + sorted(glob.glob("genre/*.mp4")) + ["run3/seg6.mp4"]
print(f"{'클립':<30}{'원본':>7}{'CPU':>7}{'GPU전체':>8}{'선명도':>8}{'cuts':>6}{'CPU ms':>8}{'GPU ms':>8}  판정")
n_ok = n_bad = n_worse = 0
for f in files:
    fr, fps = read_all(f)
    if not fr: continue
    v0, _ = judge(fr, fps, "0")
    rc, oc = P3.run(f, P3.Cfg(), verbose=False)
    vc, dc = judge(oc, fps, "c")
    cfg = P3.Cfg(); cfg.cut_thresh = CT
    try:
        rg, og = PGF.run(f, cfg, PGF.OptF(), warmup=4)
    except Exception as e:
        print(f"{os.path.basename(f):<30}  실패: {type(e).__name__}: {e}"); n_bad += 1; continue
    vg, dg = judge(og, fps, "g")
    worse = vg > v0 + 1e-9
    same = (dg == dc)
    n_ok += int(same and not worse); n_bad += int(not same); n_worse += int(worse)
    mark = ("  <- 악화" if worse else "") + ("" if same else f"  <- CPU와 판정 다름({dc}->{dg})")
    print(f"{os.path.basename(f):<30}{v0:>7.2f}{vc:>7.2f}{vg:>8.2f}"
          f"{hf(og)/max(hf(fr),1e-9)*100:>7.0f}%{rg['cuts']:>6}{rc['ms_per_frame']:>8.1f}"
          f"{rg['ms_per_frame']:>8.1f}  {dg}{mark}")
print(f"\ncut_thresh={CT}  ->  CPU와 판정 일치 {n_ok} / 불일치 {n_bad} / 악화 {n_worse}")
