# -*- coding: utf-8 -*-
"""불응기(cut_min_gap_s) 위에서 net_directional 효과가 유지되는가.

앞선 측정(70편 3파전 · 10편 A/B)은 전부 **불응기 이전** 코드에서 나왔다.
불응기가 들어가면 컷 리셋이 줄어 필터가 훨씬 많이 개입하므로, 헤일로 절대값과
악화 판정이 달라질 수 있다. 대표 8편으로 그것만 확인한다.

  s1_flagged 4편 — 히스테리시스 실험과 같은 세트 (직전 값과 비교 가능)
  explore  4편 — 70편에서 A 가 **악화**시킨 클립. 불응기 이후에도 악화하는가
"""
from __future__ import annotations

import csv
import os
import sys
import time

sys.path.insert(0, os.getcwd())

import cv2
import numpy as np

import pselive3 as P3
import psegpu_full as PGF
import pse_bt1702 as BT
import seam

S1 = os.environ.get("PSE_FLAGGED", "data/s1_flagged")
EX = os.environ.get("PSE_EXPLORE", "data/explore_100")

CLIPS = [(S1, "Db2LyhvyHI5"), (S1, "Db2BKAWvAXs"), (S1, "Db155zGxJRf"),
         (S1, "Db2D03pxZjy"),
         (EX, "DbhPStxi7eE"), (EX, "DZ3fRSEvFoi"),
         (EX, "DbvE_Zohmv6"), (EX, "Dbs05gpxSuY")]
CFGS = (("기준", {}), ("순방향", {"net_directional": True}))
OUT, CSVP = "out_rebased", "results_rebased.csv"
os.makedirs(OUT, exist_ok=True)

rows = []
for d, name in CLIPS:
    src = os.path.join(d, name + ".mp4")
    before = ";".join(BT.analyze(src, width=320)["failed_rules"] or ["적합"])
    ctrl = os.path.join(OUT, name + "_ctrl.mp4")
    if not os.path.exists(ctrl):
        seam.make_control(src, ctrl)
    base = seam.measure(src, ctrl)
    for tag, kw in CFGS:
        t0 = time.time()
        dst = os.path.join(OUT, f"{name}_{tag}.mp4")
        rec = []
        orig = PGF.FullFilterGPU._detect

        def patched(self, lin_s, _r=rec, _o=orig):
            M = _o(self, lin_s)
            _r.append(float(M.float().mean()))
            return M

        PGF.FullFilterGPU._detect = patched
        try:
            r, _ = PGF.run(src, P3.Cfg(**kw), PGF.OptF(), video_out=dst,
                           warmup=0, progress=False)
        finally:
            PGF.FullFilterGPU._detect = orig
        on = np.array(rec) > 0.01
        tg = int((on[1:] != on[:-1]).sum()) if len(on) > 1 else 0
        m = seam.measure(src, dst)
        halo = round(max(m["halo"] - base["halo"], 0.0), 3)
        after = ";".join(BT.analyze(dst, width=320)["failed_rules"] or ["적합"])
        worse = (before == "적합" and after != "적합")
        rows.append([name, os.path.basename(d), before, tag, after, halo,
                     r["mean_mask_area"], r["net_blocked"], r["cuts"], tg,
                     r["frames"], "악화" if worse else ""])
        print("%-13s %-6s 전:%-10s -> %-10s 헤일로 %7.3f  마스크 %.4f  "
              "차단 %4d  컷 %4d  토글 %3d %s (%.0fs)"
              % (name, tag, before, after, halo, r["mean_mask_area"],
                 r["net_blocked"], r["cuts"], tg, "<- 악화" if worse else "",
                 time.time() - t0), flush=True)
    print(flush=True)

with open(CSVP, "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.writer(fh)
    w.writerow(["clip", "set", "before", "config", "after", "halo", "mask",
                "net_blocked", "cuts", "toggles", "frames", "worse"])
    w.writerows(rows)

print("=== 요약 ===")
for tag, _ in CFGS:
    sub = [r for r in rows if r[3] == tag]
    h = [r[5] for r in sub]
    print("%-5s 헤일로 평균 %6.2f  악화 %d/%d"
          % (tag, sum(h) / len(h), sum(1 for r in sub if r[11]), len(sub)))
print("완료 ->", CSVP)
