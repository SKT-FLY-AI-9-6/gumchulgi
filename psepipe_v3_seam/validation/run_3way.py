# -*- coding: utf-8 -*-
"""A vs D_ste vs A→D_ste 3파전 — compare_ad 의 심판·이질감 자 재사용."""
import os
import sys
import time
import subprocess

sys.path.insert(0, "/home/user/gumchulgi/psepipe_v3_seam")
import pse_bt1702 as BT
import psepipe as PP
import seam

SCRATCH = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(SCRATCH, "adwork")
CFG = os.path.join(SCRATCH, "cfg_cpu.yaml")
CLIPS = ["01_flash_5hz", "03_red_black_5hz", "04_stripes_10pairs",
         "07_iso_red_blue_desat", "10_stripes_moving"]


def judge(p):
    return BT.analyze(p, width=320)["failed_rules"]


def dste(src, dst):
    t0 = time.time()
    r = subprocess.run([sys.executable, "-m", "blazebvd.cli", "correct", src,
                        "-o", dst, "--stage", "ste", "--config", CFG],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-200:])
    return round(time.time() - t0, 1)


rows = []
for name in CLIPS:
    src = os.path.join(SCRATCH, "eval/testclips", name + ".mkv")
    print(f"── {name}", flush=True)
    row = {"clip": name, "before": judge(src)}
    ctrl = os.path.join(WORK, name + "_ctrl.mp4")
    if not os.path.exists(ctrl):
        seam.make_control(src, ctrl)

    def seam_x(out):
        m = seam.measure(src, out)
        b = seam.measure(src, ctrl)
        return (round(max(m["pumping"] - b["pumping"], 0.0), 3),
                round(max(m["halo"] - b["halo"], 0.0), 3))

    # A
    outA = os.path.join(WORK, name + "_A.mp4")
    t0 = time.time()
    PP.run(src, outA, width=320, verbose=False)
    row["A_sec"] = round(time.time() - t0, 1)
    row["A_after"] = judge(outA)
    row["A_pump"], row["A_halo"] = seam_x(outA)

    # D_ste
    outD = os.path.join(WORK, name + "_Dste.mp4")
    row["D_sec"] = dste(src, outD)
    row["D_after"] = judge(outD)
    row["D_pump"], row["D_halo"] = seam_x(outD)

    # A → D_ste (우리 파이프라인: A 로 규격 통과 후 D 로 잔상 청소)
    outAD = os.path.join(WORK, name + "_AD.mp4")
    t0 = time.time()
    dste(outA, outAD)
    row["AD_sec"] = round(row["A_sec"] + (time.time() - t0), 1)
    row["AD_after"] = judge(outAD)
    row["AD_pump"], row["AD_halo"] = seam_x(outAD)
    rows.append(row)
    print(f"   전 {row['before']} | A후 {row['A_after']} "
          f"| D후 {row['D_after']} | A→D후 {row['AD_after']}", flush=True)

print()
hdr = ["clip", "전", "A후", "A펌핑+", "A헤일로+", "A초",
       "Dste후", "D펌핑+", "D헤일로+", "D초",
       "A→D후", "AD펌핑+", "AD헤일로+", "AD초"]
print(" | ".join(hdr))
print(" | ".join(["---"] * len(hdr)))
for r in rows:
    print(" | ".join(str(x) for x in [
        r["clip"], ",".join(r["before"]) or "-",
        ",".join(r["A_after"]) or "적합", r["A_pump"], r["A_halo"], r["A_sec"],
        ",".join(r["D_after"]) or "적합", r["D_pump"], r["D_halo"], r["D_sec"],
        ",".join(r["AD_after"]) or "적합", r["AD_pump"], r["AD_halo"],
        r["AD_sec"]]))

import csv
with open(os.path.join(SCRATCH, "three_way.csv"), "w", newline="",
          encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    for r in rows:
        w.writerow({k: (";".join(v) if isinstance(v, list) else v)
                    for k, v in r.items()})
print("\nCSV -> three_way.csv")
