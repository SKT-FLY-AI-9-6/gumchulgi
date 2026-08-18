# -*- coding: utf-8 -*-
"""compare_ad.py — 작동기 A(내장 조명장 사다리) vs D(외부 보정기) 실측 비교표.

같은 심판(pse_bt1702)·같은 이질감 자(seam)로 두 보정기를 나란히 잰다.
승자 규칙: ① 남은 위반 규칙 수가 적은 쪽 → ② 이질감(펌핑+헤일로 초과분 합)이
낮은 쪽 → ③ 빠른 쪽. 판정이 같아야 이질감을 비교한다 — 위반을 남긴 채
깨끗한 것은 승리가 아니다.

잔상축(lag/drag, seam.py 참조)은 표에 같이 나오지만 승자 규칙에는 안 들어간다
— 잔상과 점멸 억제는 같은 동전의 양면이라(Kim&Moon 실측) drag 낮음이 항상
선이 아니다. 같은 판정끼리의 상대 비교 축으로 읽는다.

사용:
    python compare_ad.py 클립1.mp4 클립2.mp4 ...
        [--d-cmd "python -m blazebvd.cli correct {src} -o {dst} --stage ste"]
        [--csv 비교표.csv] [--workdir 폴더]

--d-cmd 를 안 주면 A 열만 채운다 (D 열은 "미실행").
"""
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pse_bt1702 as BT
import psepipe as PP
import seam


def _judge(path, width=320):
    r = BT.analyze(path, width=width)
    return r["failed_rules"]


def _seam_excess(src, out, ctrl):
    """(펌핑+, 헤일로+, 잔상lag, 잔상drag+) — 전부 인코딩 대조군 초과분.

    잔상축(lag/drag)은 표시 축이다 — 승자 규칙(판정 → 펌핑+헤일로 → 속도)에는
    넣지 않는다. Kim&Moon 실측대로 잔상과 점멸 억제는 같은 동전의 양면이라
    drag 낮음이 항상 선(善)이 아니기 때문(개입을 껐어도 drag 는 내려간다).
    같은 판정 결과끼리의 상대 비교로 읽을 것."""
    m = seam.measure(src, out)
    b = seam.measure(src, ctrl)
    return (round(max(m["pumping"] - b["pumping"], 0.0), 3),
            round(max(m["halo"] - b["halo"], 0.0), 3),
            round(m["ghost_lag"], 2),
            round(max(m["ghost_drag"] - b["ghost_drag"], 0.0), 3))


def run_one(src, d_cmd, workdir, width=320):
    name = os.path.splitext(os.path.basename(src))[0]
    row = {"clip": name, "before": _judge(src, width)}
    if not row["before"]:
        row["note"] = "원본 적합 — 비교 불필요"
        return row
    ctrl = os.path.join(workdir, name + "_ctrl.mp4")
    if not os.path.exists(ctrl):
        seam.make_control(src, ctrl)

    # ── A: 내장 파이프라인
    outA = os.path.join(workdir, name + "_A.mp4")
    t0 = time.time()
    rA = PP.run(src, outA, width=width, verbose=False)
    row["A_sec"] = round(time.time() - t0, 1)
    row["A_after"] = rA["after_failed"]
    row["A_touched"] = rA.get("touched_time_pct")
    if not rA.get("untouched"):
        (row["A_pump"], row["A_halo"],
         row["A_glag"], row["A_gdrag"]) = _seam_excess(src, outA, ctrl)

    # ── D: 외부 보정기
    if d_cmd:
        outD = os.path.join(workdir, name + "_D.mp4")
        cmd = [x.format(src=src, dst=outD) for x in shlex.split(d_cmd)]
        t0 = time.time()
        rd = subprocess.run(cmd, capture_output=True, text=True)
        row["D_sec"] = round(time.time() - t0, 1)
        if rd.returncode != 0 or not os.path.exists(outD):
            row["D_after"] = ["실행실패"]
            row["D_err"] = (rd.stderr or "")[-200:]
        else:
            row["D_after"] = _judge(outD, width)
            (row["D_pump"], row["D_halo"],
             row["D_glag"], row["D_gdrag"]) = _seam_excess(src, outD, ctrl)

    # ── 승자
    if d_cmd and "D_pump" in row or (d_cmd and row.get("D_after") is not None):
        a_n = len(row.get("A_after", []))
        d_n = len(row.get("D_after", ["실행실패"]))
        if row.get("D_after") == ["실행실패"]:
            row["winner"] = "A"
        elif a_n != d_n:
            row["winner"] = "A" if a_n < d_n else "D"
        else:
            a_q = row.get("A_pump", 9e9) + row.get("A_halo", 9e9)
            d_q = row.get("D_pump", 9e9) + row.get("D_halo", 9e9)
            row["winner"] = ("A" if a_q < d_q else "D") if abs(a_q - d_q) > 1e-9 \
                else ("A" if row["A_sec"] <= row["D_sec"] else "D")
    return row


def fmt(rows):
    hdr = ["clip", "전(위반)", "A후", "A펌핑+", "A헤일로+", "A잔상 lag/drag+", "A초",
           "D후", "D펌핑+", "D헤일로+", "D잔상 lag/drag+", "D초", "승자"]
    L = [" | ".join(hdr), " | ".join(["---"] * len(hdr))]

    def _ghost(r, k):
        if f"{k}_glag" not in r:
            return "-"
        return f"{r[f'{k}_glag']}/{r[f'{k}_gdrag']}"

    for r in rows:
        if r.get("note"):
            L.append(f"{r['clip']} | (적합) | {r['note']}" + " | -" * 10)
            continue
        L.append(" | ".join(str(x) for x in [
            r["clip"], ",".join(r["before"]) or "-",
            ",".join(r.get("A_after", [])) or "적합",
            r.get("A_pump", "-"), r.get("A_halo", "-"), _ghost(r, "A"), r.get("A_sec", "-"),
            ",".join(r.get("D_after", ["미실행"])) or "적합",
            r.get("D_pump", "-"), r.get("D_halo", "-"), _ghost(r, "D"), r.get("D_sec", "-"),
            r.get("winner", "-")]))
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="작동기 A vs D 실측 비교")
    ap.add_argument("srcs", nargs="+")
    ap.add_argument("--d-cmd", default=None,
                    help="외부 보정기 명령 ({src} {dst} 치환)")
    ap.add_argument("--csv", default=None)
    ap.add_argument("--width", type=int, default=320)
    ap.add_argument("--workdir", default="_ad_work")
    a = ap.parse_args()
    os.makedirs(a.workdir, exist_ok=True)
    rows = []
    for s in a.srcs:
        print(f"── {s}", flush=True)
        rows.append(run_one(s, a.d_cmd, a.workdir, a.width))
    print()
    print(fmt(rows))
    if a.csv:
        import csv as _csv
        keys = ["clip", "before", "A_after", "A_pump", "A_halo", "A_glag",
                "A_gdrag", "A_sec", "A_touched", "D_after", "D_pump", "D_halo",
                "D_glag", "D_gdrag", "D_sec", "winner"]
        with open(a.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = _csv.writer(f)
            w.writerow(keys)
            for r in rows:
                w.writerow([";".join(r[k]) if isinstance(r.get(k), list)
                            else r.get(k, "") for k in keys])
        print(f"\nCSV -> {a.csv}")
