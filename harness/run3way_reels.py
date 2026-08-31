# -*- coding: utf-8 -*-
"""A / D_ste / A->D_ste 3파전 — 실사 릴스 전수.

08-15 의 3파전은 A / D_full / A->D_full 이었고 실사 3편·360p 였다.
여기서는 **A->D_ste 라는 빈 칸**을 채우고, 표본을 원본 해상도 100편으로 올린다.

설계상 언제든 끊어도 된다:
  · 클립 한 편이 끝날 때마다 CSV 에 한 줄씩 append
  · 이미 CSV 에 있는 클립은 건너뛴다 (--resume 기본 동작)
  · 출력 영상은 out/{A,Dste,AD}/ 에 남으므로 눈으로 볼 수 있다

사용:
  python run3way_reels.py <입력폴더> [--limit N] [--no-seam]
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time

sys.path.insert(0, os.getcwd())

import cv2

import pse_bt1702 as BT
import seam

BLAZE = os.environ.get("BLAZEBVD_HOME", "../blazebvd-training")
OUT = "out"
CSV_PATH = "results_reels_3way.csv"

COLS = ["clip", "w", "h", "frames", "dur_s",
        "before", "A", "Dste", "AD",
        "A_halo", "Dste_halo", "AD_halo",
        "A_pump", "Dste_pump", "AD_pump",
        "A_s", "Dste_s", "AD_s"]


def judge(path: str) -> str:
    """위반 축을 문자열로. 적합이면 빈 문자열."""
    r = BT.analyze(path, width=320)
    return ";".join(r["failed_rules"])


def run_A(src: str, dst: str) -> float:
    t0 = time.time()
    r = subprocess.run([sys.executable, "psegpu_full.py", src, "--video", dst],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst):
        raise RuntimeError("A 실패: " + (r.stderr or "")[-300:])
    return round(time.time() - t0, 1)


def run_Dste(src: str, dst: str) -> float:
    t0 = time.time()
    r = subprocess.run([sys.executable, "-m", "blazebvd.cli", "correct", src,
                        "-o", dst, "--stage", "ste",
                        "--config", os.path.join(BLAZE, "configs", "default.yaml")],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst):
        raise RuntimeError("D_ste 실패: " + (r.stderr or "")[-300:])
    return round(time.time() - t0, 1)


def seam_excess(src: str, out: str, base: dict) -> tuple[float, float]:
    """인코딩 대조군을 뺀 초과분 (헤일로, 펌핑)."""
    m = seam.measure(src, out)
    return (round(max(m["halo"] - base["halo"], 0.0), 3),
            round(max(m["pumping"] - base["pumping"], 0.0), 3))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("srcdir")
    ap.add_argument("--limit", type=int, default=0, help="앞에서 N 편만")
    ap.add_argument("--sample", type=int, default=0,
                    help="남은 것 중 N 편을 **무작위로**. 길이순 편향을 피한다")
    ap.add_argument("--seed", type=int, default=20260817, help="--sample 재현용")
    ap.add_argument("--no-seam", action="store_true", help="이질감 측정 생략 (빠름)")
    a = ap.parse_args()

    for d in ("A", "Dste", "AD", "_ctrl"):
        os.makedirs(os.path.join(OUT, d), exist_ok=True)

    done = set()
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, encoding="utf-8-sig") as fh:
            done = {r["clip"] for r in csv.DictReader(fh)}
    else:
        with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as fh:
            csv.writer(fh).writerow(COLS)

    files = sorted(f for f in os.listdir(a.srcdir) if f.lower().endswith(".mp4"))
    # 짧은 것부터 — 끊더라도 편수를 최대한 확보한다
    files.sort(key=lambda f: os.path.getsize(os.path.join(a.srcdir, f)))
    todo = [f for f in files if os.path.splitext(f)[0] not in done]
    if a.sample and a.sample < len(todo):
        # 길이순 정렬이 만드는 편향을 피한다 — 짧은 것만 남기면 ④지속·누적
        # 조항이 긴 영상에서 더 잘 걸리는 만큼 위반율이 과소평가된다.
        import random
        todo = random.Random(a.seed).sample(todo, a.sample)
        todo.sort(key=lambda f: os.path.getsize(os.path.join(a.srcdir, f)))
    if a.limit:
        todo = todo[:a.limit]

    print(f"대상 {len(todo)}편 (완료 {len(done)}편 건너뜀)", flush=True)

    for i, fn in enumerate(todo, 1):
        src = os.path.join(a.srcdir, fn)
        name = os.path.splitext(fn)[0]
        cap = cv2.VideoCapture(src)
        w, h = int(cap.get(3)), int(cap.get(4))
        nf, fps = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), cap.get(5) or 30.0
        cap.release()
        t_clip = time.time()
        print(f"[{i}/{len(todo)}] {name}  {w}x{h}  {nf}f", flush=True)

        try:
            oA = os.path.join(OUT, "A", fn)
            oD = os.path.join(OUT, "Dste", fn)
            oAD = os.path.join(OUT, "AD", fn)
            sA = run_A(src, oA)
            sD = run_Dste(src, oD)
            sAD = run_Dste(oA, oAD)          # A 출력 위에 D_ste

            v0, vA, vD, vAD = (judge(src), judge(oA), judge(oD), judge(oAD))

            hA = hD = hAD = pA = pD = pAD = ""
            if not a.no_seam:
                ctrl = os.path.join(OUT, "_ctrl", fn)
                if not os.path.exists(ctrl):
                    seam.make_control(src, ctrl)
                base = seam.measure(src, ctrl)
                hA, pA = seam_excess(src, oA, base)
                hD, pD = seam_excess(src, oD, base)
                hAD, pAD = seam_excess(src, oAD, base)

            row = [name, w, h, nf, round(nf / fps, 2),
                   v0 or "적합", vA or "적합", vD or "적합", vAD or "적합",
                   hA, hD, hAD, pA, pD, pAD, sA, sD, sAD]
            with open(CSV_PATH, "a", newline="", encoding="utf-8-sig") as fh:
                csv.writer(fh).writerow(row)

            print(f"    전:{v0 or '적합'}  A:{vA or '적합'}  D:{vD or '적합'}  "
                  f"AD:{vAD or '적합'}   헤일로+ A {hA} / D {hD} / AD {hAD}   "
                  f"({time.time() - t_clip:.0f}s)", flush=True)

        except Exception as e:
            print(f"    실패: {type(e).__name__}: {e}", flush=True)

    print(f"\n완료 -> {CSV_PATH}", flush=True)


if __name__ == "__main__":
    main()
