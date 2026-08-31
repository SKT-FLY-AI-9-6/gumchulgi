# -*- coding: utf-8 -*-
"""22번/seg6 의 cuts 과검출이 판정 불일치의 원인인지 확인한다.
verify_full.py 와 동일한 방식으로 판정(PC.analyze)한다."""
import os, sys, cv2, numpy as np
sys.path.insert(0, os.getcwd())
import psecore as PC, pseenv as ENV, pselive3 as P3, rawmeasure as RM
import psegpu_full as PGF


def read_all(p):
    cap = cv2.VideoCapture(p)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    fr = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        fr.append(f)
    cap.release()
    return fr, fps


def judge(frames, fps, tag):
    p = ENV.tmp(f"sw_{tag}.mkv")
    RM.write_lossless(frames, p, fps)
    r = PC.analyze(p, PC.PROFILES["bt1702"])
    os.remove(p)
    return sum(r.channel_seconds().values()), r.verdict


for clip in sys.argv[1:]:
    fr, fps = read_all(clip)
    v0, d0 = judge(fr, fps, "0")
    print(f"\n=== {os.path.basename(clip)}  원본 {v0:.2f}s {d0} ===")
    print(f"{'cut_thresh':>11}{'cuts':>7}{'초':>8}  판정")
    for ct in [0.45, 0.20, 0.05, -1.0]:
        cfg = P3.Cfg()
        cfg.cut_thresh = ct          # CLI 의 --cut-thresh 는 OptF 에 쓰여 무시된다
        rg, og = PGF.run(clip, cfg, PGF.OptF(), warmup=2)
        vg, dg = judge(og, fps, "g")
        flag = "  <- 악화" if vg > v0 + 1e-9 else ""
        print(f"{ct:>11.2f}{rg['cuts']:>7}{vg:>8.2f}  {dg}{flag}")
