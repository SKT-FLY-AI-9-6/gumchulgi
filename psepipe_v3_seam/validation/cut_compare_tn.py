# -*- coding: utf-8 -*-
"""cut_compare_tn.py — 원본/보정본의 NCC 컷 vs TransNetV2 샷 경계 비교.

AI-PoC-0824 2번(cut_compare_transnet.csv)과 같은 정의로 잰다:
  NCC컷        = pselive3._is_cut 의 NCC 판별(64x64 대비정규화, cut_thresh 0.45,
                 flat_sd 6.0 가드)을 불응기 없이 그대로 센 원시 트리거 수
  NCC컷_불응기 = 같은 판별에 cut_min_gap_s 0.5s 불응기 적용 (실제 필터 동작)
  TransNetV2컷 = 샷 경계 수 (장면 수 - 1, threshold 0.5)

사용 (validation/ 에서):
    python cut_compare_tn.py "원본=../_dfull/클립.mp4" "base=_regress/클립_base.mp4" \
        [--csv 결과.csv]

필요: pip install transnetv2-pytorch  (torch 포함)
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

import cv2
import numpy as np

CUT_THRESH = 0.45
FLAT_SD = 6.0
CUT_MIN_GAP_S = 0.5


def ncc_cuts(path):
    """pselive3._is_cut 재현 — (원시 컷 수, 불응기 적용 컷 수)."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise SystemExit(f"영상 열기 실패: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    gap_n = max(0, int(round(CUT_MIN_GAP_S * fps)))
    prev, prev_flat = None, False
    raw = gated = 0
    since_cut = 10 ** 9
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        g = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32),
                       (64, 64), interpolation=cv2.INTER_AREA)
        g -= g.mean()
        sd = float(g.std())
        flat = sd < FLAT_SD
        gn = g / sd if sd > 1e-3 else np.zeros_like(g)
        cut = False
        if prev is not None and not flat and not prev_flat:
            cut = float((gn * prev).mean()) < CUT_THRESH
        if cut:
            raw += 1
        g_cut = cut and since_cut >= gap_n
        if g_cut:
            gated += 1
        since_cut = 0 if g_cut else since_cut + 1
        prev, prev_flat = gn, flat
    cap.release()
    return raw, gated


def main():
    if hasattr(sys.stdout, "reconfigure"):   # cp949 콘솔 크래시 방지
        sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("variants", nargs="+", help='"라벨=경로" 목록 (첫 항목이 원본)')
    ap.add_argument("--csv", default=None)
    a = ap.parse_args()

    import torch
    from transnetv2_pytorch import TransNetV2
    model = TransNetV2()
    model.eval()

    first = a.variants[0].split("=", 1)[1]
    clip = os.path.splitext(os.path.basename(first))[0]
    rows = []
    for arg in a.variants:
        variant, path = arg.split("=", 1)
        raw, gated = ncc_cuts(path)
        with torch.no_grad():
            tn = model.get_scene_count(path, threshold=0.5) - 1
        rows.append({"clip": clip, "variant": variant,
                     "NCC컷": raw, "NCC컷_불응기": gated, "TransNetV2컷": tn})
        print(f"{variant:<8} NCC {raw:>3} (불응기 {gated:>3})  TN {tn:>3}  "
              f"{os.path.basename(path)}", flush=True)

    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"CSV -> {a.csv}")


if __name__ == "__main__":
    main()
