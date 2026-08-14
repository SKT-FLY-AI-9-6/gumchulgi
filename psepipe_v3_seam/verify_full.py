# -*- coding: utf-8 -*-
"""
verify_full.py — **전 GPU 판을 믿기 전에 반드시 돌린다.**

psegpu(적용부만 GPU)는 검출이 CPU 라 CPU 기준판과 화소가 1 LSB 안에서 같았다.
psegpu_full 은 검출까지 옮겼으므로 **결과가 달라질 수 있다.** 세 군데가 원인이다.

  1) 축소     cv2.INTER_AREA  vs  F.interpolate(mode="area")
  2) 위상상관 cv2.phaseCorrelate(응답 기준)  vs  자체 FFT(봉우리 비 기준)
  3) 컷 판정  8비트 그레이 기준  vs  선형광 기준

그래서 화소 일치는 **기대하지 않는다.** 대신 진짜 중요한 것만 본다.

  A. 판정   — 27클립(또는 지정 클립)에서 PASS/FAIL 이 같은가
  B. 악화   — 안전한 원본을 위반으로 만들지 않는가   ← 절대 조건
  C. 선명도 — 얼마나 깎였나
  D. 속도   — CPU 기준판 대비

사용:
    python verify_full.py                 # 27클립 전수
    python verify_full.py --quick         # 핵심 6클립
    python verify_full.py --clip synth/14_stripes_drift_10pairs.mp4
"""
from __future__ import annotations

import argparse
import glob
import os

import cv2
import numpy as np

import psecore as PC
import pseenv as ENV
import pselive3 as P3
import rawmeasure as RM

QUICK = ["synth/01_lum_strobe_5hz.mp4", "synth/12_porygon_redblue_12hz.mp4",
         "synth/14_stripes_drift_10pairs.mp4", "genre/22_game_hud_7hz.mp4",
         "genre/26_safe_shaky.mp4", "run3/seg6.mp4"]


def hf(fr):
    v = []
    for f in fr:
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32)
        v.append(float(np.abs(g - cv2.GaussianBlur(g, (0, 0), 2.0)).mean()))
    return float(np.mean(v)) if v else 1.0


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
    p = ENV.tmp(f"vf_{tag}.mkv")
    RM.write_lossless(frames, p, fps)
    r = PC.analyze(p, PC.PROFILES["bt1702"])
    os.remove(p)
    return sum(r.channel_seconds().values()), r.verdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--clip", default=None)
    ap.add_argument("--half", action="store_true")
    a = ap.parse_args()

    import psegpu_full as PGF
    import torch
    print(f"torch {torch.__version__}  {torch.cuda.get_device_name(0)}\n")

    if a.clip:
        files = [a.clip]
    elif a.quick:
        files = [f for f in QUICK if os.path.exists(f)]
    else:
        files = sorted(glob.glob("synth/*.mp4")) + sorted(glob.glob("genre/*.mp4")) \
            + ["run3/seg6.mp4"]

    opt = PGF.OptF(half=a.half)
    print(f"{'클립':<30}{'원본':>7}{'CPU':>7}{'GPU전체':>8}"
          f"{'선명도':>8}{'CPU ms':>8}{'GPU ms':>8}  판정")
    n_ok = n_bad = n_worse = 0
    for f in files:
        fr, fps = read_all(f)
        if not fr:
            continue
        v0, _ = judge(fr, fps, "0")
        rc, oc = P3.run(f, P3.Cfg(), verbose=False)
        vc, dc = judge(oc, fps, "c")
        try:
            rg, og = PGF.run(f, P3.Cfg(), opt, warmup=4)
        except Exception as e:
            print(f"{os.path.basename(f):<30}  실패: {type(e).__name__}: {e}")
            n_bad += 1
            continue
        vg, dg = judge(og, fps, "g")

        worse = vg > v0 + 1e-9
        same = (dg == dc)
        n_ok += int(same and not worse)
        n_bad += int(not same)
        n_worse += int(worse)
        mark = ""
        if worse:
            mark += "  ← 악화"
        if not same:
            mark += f"  ← CPU와 판정 다름({dc}->{dg})"
        print(f"{os.path.basename(f):<30}{v0:>7.2f}{vc:>7.2f}{vg:>8.2f}"
              f"{hf(og)/max(hf(fr),1e-9)*100:>7.0f}%{rc['ms_per_frame']:>8.1f}"
              f"{rg['ms_per_frame']:>8.1f}  {dg}{mark}")

    print(f"\nCPU와 판정 일치 {n_ok} / 불일치 {n_bad} / 악화 {n_worse}")
    print("악화 0 이 절대 조건입니다. 불일치는 검출 구현 차이라 허용될 수 있지만,")
    print("안전한 원본을 위반으로 만드는 건(악화) 어떤 이유로도 안 됩니다.")


if __name__ == "__main__":
    main()
