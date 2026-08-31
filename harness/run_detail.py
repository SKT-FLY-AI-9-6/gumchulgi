# -*- coding: utf-8 -*-
"""detail_sigma 스윕 — 잔상(유령 얼굴)을 줄일 수 있는가.

기전: out = prev + k·d 의 상한 S 가 프레임당 0.04(선형광)라, 마스크 안의
인물도 같이 묶여 못 따라온다. detail_sigma 는 **저주파(레벨)만 제한하고
질감은 현재 프레임에서** 가져오는 장치인데, 기본 2.0 은 반경이 너무 작아
수십 픽셀 규모인 얼굴이 통째로 '저주파'로 분류돼 제한을 받는다.

규격 근거: BT.1702 의 플래시는 화면 1/4 이상 면적을 요구한다 — 위험 신호는
본질적으로 아주 낮은 공간주파수다. 얼굴·질감은 그보다 높은 대역이다.

함정: pselive3.py 주석대로 tex 를 [0.25,4] 로 자르므로 sigma 를 키우면
클리핑이 잦아져 고대비 경계에서 항등이 깨진다(과거 악화 2건의 원인).
그래서 **잔상만 보지 말고 악화·헤일로·스펙트럼을 같이 잰다.**
"""
from __future__ import annotations

import csv, os, re, subprocess, sys, time
sys.path.insert(0, os.getcwd())
import pselive3 as P3, psegpu_full as PGF, pse_bt1702 as BT, seam

S1 = r"C:/Users/dltmd/Downloads/pse_detectors final/pse_detectors/data/s1_flagged"
CLIPS = [(os.path.join(S1, "Db2D03pxZjy.mp4"), "Db2D03pxZjy"),
         (r"C:/Users/dltmd/Downloads/cera_640.mp4", "cera_640")]
SIGMAS = [2.0, 8.0, 16.0, 32.0]
OUT, CSVP = "out_detail", "results_detail.csv"
os.makedirs(OUT, exist_ok=True)


def spectrum(src, dst):
    """3~30Hz 대역 에너지의 원본 대비 비율(%)."""
    r = subprocess.run([sys.executable, "pse_spectrum.py", src, dst],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    m = re.findall(r"\(원본 대비\s+([\d.]+)%", r.stdout or "")
    return float(m[0]) if m else float("nan")


rows = []
for src, name in CLIPS:
    before = ";".join(BT.analyze(src, width=320)["failed_rules"] or ["적합"])
    ctrl = os.path.join(OUT, name + "_ctrl.mp4")
    if not os.path.exists(ctrl):
        seam.make_control(src, ctrl)
    base = seam.measure(src, ctrl)
    print(f"── {name}  원본: {before}", flush=True)
    for sg in SIGMAS:
        t0 = time.time()
        dst = os.path.join(OUT, f"{name}_sg{int(sg)}.mp4")
        cfg = P3.Cfg(net_directional=True, detail_sigma=sg)
        r, _ = PGF.run(src, cfg, PGF.OptF(), video_out=dst, warmup=0, progress=False)
        m = seam.measure(src, dst)
        halo = round(max(m["halo"] - base["halo"], 0.0), 3)
        pump = round(max(m["pumping"] - base["pumping"], 0.0), 3)
        after = ";".join(BT.analyze(dst, width=320)["failed_rules"] or ["적합"])
        pct = spectrum(src, dst)
        worse = (before == "적합" and after != "적합")
        rows.append([name, before, sg, after, halo, pump, pct,
                     r["mean_mask_area"], r["frames"], "악화" if worse else ""])
        print("   sigma %-5.1f 판정 %-10s 헤일로 %7.3f  펌핑 %6.3f  "
              "점멸 %5.1f%%  마스크 %.4f %s (%.0fs)"
              % (sg, after, halo, pump, pct, r["mean_mask_area"],
                 "<- 악화" if worse else "", time.time() - t0), flush=True)
    print(flush=True)

with open(CSVP, "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.writer(fh)
    w.writerow(["clip", "before", "detail_sigma", "after", "halo", "pumping",
                "spectrum_pct", "mask", "frames", "worse"])
    w.writerows(rows)
print("완료 ->", CSVP)
print("\n읽는 법: 점멸%가 낮게 유지되면서 펌핑/헤일로가 줄고 악화가 없으면 채택.")
print("        점멸%가 올라가면 위험 억제를 포기한 것이므로 기각.")
