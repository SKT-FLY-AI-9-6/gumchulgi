# -*- coding: utf-8 -*-
"""A vs D_full vs A->D_full 3파전 (GPU).

validation/run_3way.py 의 이식판. 원본은 CPU 컨테이너 경로와 D_ste 에
하드코딩돼 있어 그대로 못 쓴다. 심판(pse_bt1702)·이질감 자(seam)는 동일.

가이드가 남긴 질문에 답한다:
  "travis 에서 A->D-full 체인이 D-full 단독보다 헤일로를 줄이는가"
"""
import os, sys, time, subprocess, csv
sys.path.insert(0, os.getcwd())
import pse_bt1702 as BT
import psepipe as PP
import seam
import tier as T

W = "../../blazebvd-wt/blazebvd-training"
WORK = "_3way"
os.makedirs(WORK, exist_ok=True)


def judge(p):
    r = BT.analyze(p, width=320)
    t, why = T.tier(r)
    return r["failed_rules"], t


def dfull(src, dst):
    t0 = time.time()
    r = subprocess.run([sys.executable, "-m", "blazebvd.cli", "correct", src,
                        "-o", dst, "--stage", "full", "--device", "cuda",
                        "--checkpoint", f"{W}/runs/davis_blazebvd/tcm/best.pt",
                        "--config", f"{W}/configs/default.yaml",
                        "--clip-length", "8", "--overlap", "2"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "")[-400:])
    return round(time.time() - t0, 1)


rows = []
for name in sys.argv[1:]:
    src = f"_dfull/{name}_360.mp4"
    print(f"-- {name}", flush=True)
    before, tb = judge(src)
    row = {"clip": name, "before": before, "before_tier": tb}
    ctrl = os.path.join(WORK, name + "_ctrl.mp4")
    if not os.path.exists(ctrl):
        seam.make_control(src, ctrl)
    base = seam.measure(src, ctrl)

    def seam_x(out):
        m = seam.measure(src, out)
        return (round(max(m["pumping"] - base["pumping"], 0.0), 3),
                round(max(m["halo"] - base["halo"], 0.0), 3))

    # A
    outA = os.path.join(WORK, name + "_A.mp4")
    t0 = time.time()
    PP.run(src, outA, width=320, verbose=False)
    row["A_sec"] = round(time.time() - t0, 1)
    row["A_after"], row["A_tier"] = judge(outA)
    row["A_pump"], row["A_halo"] = seam_x(outA)

    # D_full 단독 (3단계에서 이미 만든 것 재사용)
    outD = f"_dfull/{name}_360_Dfull.mp4"
    row["D_sec"] = ""
    row["D_after"], row["D_tier"] = judge(outD)
    row["D_pump"], row["D_halo"] = seam_x(outD)

    # A -> D_full 체인
    outAD = os.path.join(WORK, name + "_AD.mp4")
    row["AD_sec"] = round(row["A_sec"] + dfull(outA, outAD), 1)
    row["AD_after"], row["AD_tier"] = judge(outAD)
    row["AD_pump"], row["AD_halo"] = seam_x(outAD)

    rows.append(row)
    print(f"   before {before}/{tb} | A {row['A_after']}/{row['A_tier']} "
          f"halo {row['A_halo']} | D-full {row['D_after']}/{row['D_tier']} "
          f"halo {row['D_halo']} | A->D {row['AD_after']}/{row['AD_tier']} "
          f"halo {row['AD_halo']}", flush=True)

hdr = ["clip", "before", "A_after", "A_tier", "A_pump", "A_halo", "A_sec",
       "Dfull_after", "Dfull_tier", "Dfull_pump", "Dfull_halo",
       "AD_after", "AD_tier", "AD_pump", "AD_halo", "AD_sec"]
print()
print(" | ".join(hdr))
print(" | ".join(["---"] * len(hdr)))
for r in rows:
    print(" | ".join(str(x) for x in [
        r["clip"], ",".join(r["before"]) or "-",
        ",".join(r["A_after"]) or "적합", r["A_tier"], r["A_pump"], r["A_halo"], r["A_sec"],
        ",".join(r["D_after"]) or "적합", r["D_tier"], r["D_pump"], r["D_halo"],
        ",".join(r["AD_after"]) or "적합", r["AD_tier"], r["AD_pump"], r["AD_halo"], r["AD_sec"]]))

with open("validation/three_way_reels_dfull.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(hdr)
    for r in rows:
        w.writerow([r["clip"], ";".join(r["before"]), ";".join(r["A_after"]), r["A_tier"],
                    r["A_pump"], r["A_halo"], r["A_sec"],
                    ";".join(r["D_after"]), r["D_tier"], r["D_pump"], r["D_halo"],
                    ";".join(r["AD_after"]), r["AD_tier"], r["AD_pump"], r["AD_halo"], r["AD_sec"]])
print("\nCSV -> validation/three_way_reels_dfull.csv")
