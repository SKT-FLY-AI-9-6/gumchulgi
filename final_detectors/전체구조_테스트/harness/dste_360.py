# -*- coding: utf-8 -*-
"""D_ste 를 D_full 과 **같은 360p 클립**에 돌려 공정 비교한다.

앞선 2단계의 D_ste 는 원본 해상도, 3단계의 D_full 은 360p 라 서로 비교할 수
없었다. 이질감 자(seam)와 심판(pse_bt1702)은 동일.
"""
import os, sys, time, subprocess, csv
sys.path.insert(0, os.getcwd())
import pse_bt1702 as BT
import seam
import tier as T
import cv2

W = "../../blazebvd-wt/blazebvd-training"
WORK = "_3way"
os.makedirs(WORK, exist_ok=True)


def judge(p):
    r = BT.analyze(p, width=320)
    t, why = T.tier(r)
    return r["failed_rules"], t


rows = []
for name in sys.argv[1:]:
    src = f"_dfull/{name}_360.mp4"
    dst = os.path.join(WORK, name + "_Dste.mp4")
    cap = cv2.VideoCapture(src); nf = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); cap.release()
    t0 = time.time()
    r = subprocess.run([sys.executable, "-m", "blazebvd.cli", "correct", src, "-o", dst,
                        "--stage", "ste", "--config", f"{W}/configs/default.yaml"],
                       capture_output=True, text=True)
    el = round(time.time() - t0, 1)
    if r.returncode != 0:
        print(f"{name}: 실패 {(r.stderr or '')[-300:]}", flush=True); continue
    ctrl = os.path.join(WORK, name + "_ctrl.mp4")
    if not os.path.exists(ctrl):
        seam.make_control(src, ctrl)
    base = seam.measure(src, ctrl)
    m = seam.measure(src, dst)
    pump = round(max(m["pumping"] - base["pumping"], 0.0), 3)
    halo = round(max(m["halo"] - base["halo"], 0.0), 3)
    after, tier_ = judge(dst)
    print(f"{name}: D_ste {after or '적합'}/{tier_}  pump {pump}  halo {halo}  "
          f"{el}s ({el/max(nf,1)*1000:.0f} ms/frame)", flush=True)
    rows.append([name, ";".join(after), tier_, pump, halo, el, nf, round(el/max(nf,1)*1000,1)])

with open("validation/dste_360.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["clip","Dste_after","Dste_tier","Dste_pump","Dste_halo","sec","frames","ms_per_frame"])
    w.writerows(rows)
print("\nCSV -> validation/dste_360.csv")
