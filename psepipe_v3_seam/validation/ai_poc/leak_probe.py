# -*- coding: utf-8 -*-
"""σ32 누수 판별자 — 점멸 광원의 공간 규모·복원 가능 대비를 클립 단위로 잰다.

배경 (REGRESS_0820 3·5절)
  detail_sigma=32 는 pselive3 질감 복원(513-530행)에서 32px 급 이하 구조를
  "질감"으로 보고 **억제된 플래시를 입력에서 되살린다** — 실사 209편 중 5편.
  5절의 사전 판별자 후보(net, a_hot)는 분포가 겹쳐 기각됐고, 그래서 현행은
  사후 폴백(strong → 재판정 → 못 미치면 base)이다.

이 파일이 재는 것
  · 점멸 마스크(시간축 표준편차)의 **연결성분 등가지름** 분포와 영역 수
    → 전면형(1영역·수백 px)과 국소형(수십~수백 영역·10px 대)을 자릿수로 가른다.
  · 마스크 안 화소의 **tex 비율** `Y/blur(Y,σ)` 분포 — 복원식이 실제로 쓰는 양.
    `clamped_frac` 은 [0.25,4] 클램프에 걸려 복원이 제한되는 비율,
    `restorable_frac` 은 밝은 쪽이면서 클램프 안(=온전히 복원됨)인 비율.

2026-08-26 로컬 실측의 한계 (정직)
  합성으로는 누수를 **재현하지 못했다**. 소형 광원 가설(12_bulbs_grid,
  등가지름 15px·257영역)도, tex 클램프 가설(bg_matrix.py, 배경 밝기 4단)도
  base·strong 모두 적합이라 양성 표본이 없다. cera(실사, 등가지름 4.3px·
  66영역)도 strong 성공 사례다. 즉 **이 축이 누수를 가르는지는 미검증**이고,
  검증은 누수 5편이 있는 GPU 노트북에서 해야 한다(README 참조).
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import pse_bt1702 as BT
import pselive3 as P3


def probe(path: str, sigma: float = 32.0, aw: int = 320, max_frames: int = 180) -> dict:
    """점멸 마스크 안의 tex 비율 분포 + 영역 등가지름 통계."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise IOError(path)
    src_w = float(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or aw
    frames = []
    while len(frames) < max_frames:
        ok, fr = cap.read()
        if not ok:
            break
        h = int(round(fr.shape[0] * aw / fr.shape[1]))
        frames.append(cv2.resize(fr, (aw, h), interpolation=cv2.INTER_AREA))
    cap.release()
    if not frames:
        raise IOError(path)
    st = np.stack([f.astype(np.float32).mean(axis=2) / 255.0 for f in frames])
    sd = st.std(axis=0)
    flick = sd > max(0.5 * float(sd.max()), 0.02)
    sg = sigma * (aw / src_w)          # 원본 화소 기준 σ 를 분석폭으로 환산
    ratios, diams, nreg = [], [], []
    for f in frames[::5]:
        Y = f.astype(np.float32).mean(axis=2) / 255.0
        r = Y / np.maximum(cv2.GaussianBlur(Y, (0, 0), max(sg, 0.8)), 1e-4)
        ratios.append(r[flick])
    num, _, stats, _ = cv2.connectedComponentsWithStats(flick.astype(np.uint8), 8)
    area = stats[1:, cv2.CC_STAT_AREA]
    area = area[area >= 4]
    if len(area):
        diams = 2 * np.sqrt(area / np.pi)
        nreg = len(area)
    else:
        diams, nreg = np.array([0.0]), 0
    R = np.concatenate(ratios) if ratios else np.array([1.0])
    bright = R > 1.05
    return dict(flick_area=round(float(flick.mean()), 4),
                tex_p50=round(float(np.percentile(R, 50)), 3),
                tex_p95=round(float(np.percentile(R, 95)), 3),
                clamped_frac=round(float((R >= 4.0).mean()), 4),
                restorable_frac=round(float((bright & (R < 4.0)).mean()), 4),
                med_diam_px=round(float(np.median(diams)), 1),
                p90_diam_px=round(float(np.percentile(diams, 90)), 1),
                n_regions=int(nreg))


def judge(path: str) -> str:
    return ",".join(BT.analyze(path)["failed_rules"]) or "적합"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="σ32 누수 판별자 — 클립별 광원 규모·복원 대비 통계 (+선택적 base/strong 판정)")
    ap.add_argument("clips", nargs="+", help="영상 경로 (glob 가능)")
    ap.add_argument("--csv", default="leak_probe.csv")
    ap.add_argument("--filter", action="store_true",
                    help="base/strong 로 실제 필터링해 판정까지 (누수 라벨 생성)")
    ap.add_argument("--workdir", default="_leak")
    ap.add_argument("--sigma", type=float, default=32.0)
    a = ap.parse_args()
    srcs = []
    for s in a.clips:
        srcs += sorted(glob.glob(s)) if any(ch in s for ch in "*?[") else [s]
    os.makedirs(a.workdir, exist_ok=True)

    rows = []
    for src in srcs:
        name = os.path.splitext(os.path.basename(src))[0]
        row = dict(clip=name, **probe(src, sigma=a.sigma))
        if a.filter:
            row["judge_src"] = judge(src)
            for tag, cfg in (("base", P3.Cfg()), ("strong", P3.Cfg.strong())):
                out = os.path.join(a.workdir, f"{name}_{tag}.mp4")
                if not os.path.exists(out):
                    P3.run(src, cfg, video_out=out, verbose=False)
                row["judge_" + tag] = judge(out)
            row["누수"] = "Y" if (row["judge_base"] == "적합"
                                and row["judge_strong"] != "적합") else "N"
        print(json.dumps(row, ensure_ascii=False), flush=True)
        rows.append(row)
    with open(a.csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"CSV -> {a.csv}")
    if a.filter:
        leak = [r["clip"] for r in rows if r.get("누수") == "Y"]
        print(f"누수 {len(leak)}편: {', '.join(leak) or '없음'}")
        if leak:
            ok = [r for r in rows if r.get("누수") == "N"]
            for k in ("med_diam_px", "restorable_frac", "n_regions"):
                lv = [r[k] for r in rows if r.get("누수") == "Y"]
                ov = [r[k] for r in ok]
                print(f"  {k:<16} 누수 {np.median(lv):.3f} vs 정상 {np.median(ov):.3f}")


if __name__ == "__main__":
    main()
