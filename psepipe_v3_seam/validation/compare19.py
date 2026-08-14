# -*- coding: utf-8 -*-
"""compare19.py — 두 검출기(pse_bt1702 / psecore)로 같은 영상들을 나란히 판정한다.

    python compare19.py data/s2_rand20/*.mp4 --outdir out --jobs 4

각 영상마다 out/json/<이름>.json 을 남기고, 마지막에 요약표를 찍는다.
이미 만들어진 json 은 건너뛴다(--force 로 재실행).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _jsonable(o):
    import numpy as np
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def run_one(src: str, width: int = 320) -> dict:
    import pse_bt1702 as BT
    import psecore as PC
    import tier as TIER

    name = os.path.splitext(os.path.basename(src))[0]
    row: dict = {"clip": name, "path": src}

    # ── 검출기 1: pse_bt1702 (규격 판정 정본)
    t0 = time.time()
    try:
        r = BT.analyze(src, width=width)
        t, why = TIER.tier(r)
        row["bt"] = {
            "verdict": "위반" if not r["compliant"] else "적합",
            "tier": t, "tier_why": why,
            "failed_rules": r["failed_rules"],
            "supplementary_flags": r["supplementary_flags"],
            "duration_s": r["duration_s"], "fps": r["fps"], "frames": r["frames"],
            "sustained_over_5s": r["sustained_over_5s"],
            "rules": r["rules"],
            "supplementary": r["supplementary"],
            "frame_separation": r["frame_separation"],
            "violation_segments": r["violation_segments"],
        }
    except Exception as exc:  # noqa: BLE001
        row["bt"] = {"error": f"{type(exc).__name__}: {exc}"}
    row["bt_sec"] = round(time.time() - t0, 1)

    # ── 검출기 2: psecore (통합 검출기 v2.0, bt1702 프로파일)
    t0 = time.time()
    try:
        cfg = PC.PROFILES["bt1702"]
        rep = PC.analyze(src, cfg, profile_name="bt1702")
        d = rep.to_dict(cfg)
        row["pc"] = {
            "verdict": "위반" if d["verdict"] == "FAIL" else "적합",
            "raw_verdict": d["verdict"],
            "failed_channels": d["failed_channels"],
            "warn_channels": sorted({s["channel"] for s in d["warnings"]}),
            "channel_seconds": d["channel_seconds"],
            "summary": d["summary"],
            "violations": d["violations"],
            "warnings": d["warnings"],
            "video": d["video"],
        }
    except Exception as exc:  # noqa: BLE001
        row["pc"] = {"error": f"{type(exc).__name__}: {exc}"}
    row["pc_sec"] = round(time.time() - t0, 1)

    bv = row.get("bt", {}).get("verdict")
    pv = row.get("pc", {}).get("verdict")
    row["agree"] = (bv == pv) if (bv and pv) else None
    return row


def _worker(args):
    src, width, jdir, force = args
    name = os.path.splitext(os.path.basename(src))[0]
    jp = os.path.join(jdir, name + ".json")
    if os.path.exists(jp) and not force:
        return json.load(open(jp, encoding="utf-8"))
    row = run_one(src, width)
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(row, f, ensure_ascii=False, indent=1, default=_jsonable)
    return row


def summary_table(rows) -> str:
    L = [f"{'영상':<20}{'BT1702':<8}{'단계':<10}{'BT 근거':<26}"
         f"{'psecore':<9}{'PC 채널':<14}{'일치'}",
         "-" * 100]
    for r in sorted(rows, key=lambda x: x["clip"]):
        bt, pc = r.get("bt", {}), r.get("pc", {})
        bv = bt.get("verdict") or ("오류")
        pv = pc.get("verdict") or ("오류")
        why = ",".join(bt.get("failed_rules", [])) or "-"
        ch = ",".join(pc.get("failed_channels", [])) or "-"
        ok = "O" if r.get("agree") else "X  <<<"
        L.append(f"{r['clip']:<20}{bv:<8}{bt.get('tier','-'):<10}{why:<26}"
                 f"{pv:<9}{ch:<14}{ok}")
    n = len(rows)
    dis = [r for r in rows if r.get("agree") is False]
    L.append("-" * 100)
    L.append(f"총 {n}편 · 일치 {n - len(dis)}편 · 불일치 {len(dis)}편"
             + (" → " + ", ".join(r["clip"] for r in dis) if dis else ""))
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("srcs", nargs="+")
    ap.add_argument("--outdir", default="out")
    ap.add_argument("--width", type=int, default=320)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    srcs = []
    for s in a.srcs:
        srcs.extend(sorted(glob.glob(s)) if any(c in s for c in "*?[") else [s])
    jdir = os.path.join(a.outdir, "json")
    os.makedirs(jdir, exist_ok=True)

    rows, t0 = [], time.time()
    tasks = [(s, a.width, jdir, a.force) for s in srcs]
    if a.jobs <= 1:
        for t in tasks:
            rows.append(_worker(t))
            print(f"[{len(rows)}/{len(tasks)}] {rows[-1]['clip']}", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=a.jobs) as ex:
            futs = {ex.submit(_worker, t): t[0] for t in tasks}
            for f in as_completed(futs):
                try:
                    rows.append(f.result())
                except Exception as exc:  # noqa: BLE001
                    print(f"실패 {futs[f]}: {exc}", flush=True)
                    continue
                print(f"[{len(rows)}/{len(tasks)}] {rows[-1]['clip']}  "
                      f"BT={rows[-1].get('bt',{}).get('verdict')} "
                      f"PC={rows[-1].get('pc',{}).get('verdict')}", flush=True)

    print()
    print(summary_table(rows))
    print(f"\n소요 {time.time()-t0:.0f}s")
    with open(os.path.join(a.outdir, "compare19.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1, default=_jsonable)
    with open(os.path.join(a.outdir, "compare19_summary.txt"), "w",
              encoding="utf-8") as f:
        f.write(summary_table(rows) + "\n")
