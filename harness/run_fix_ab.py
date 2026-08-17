# -*- coding: utf-8 -*-
"""플래시 라벨 릴스 10편 × 4조합 — 수정 2건의 효과 측정.

조합: 기준 / 워프(warp_alpha) / 순방향(net_directional) / 둘다
보는 것: ① 미탐 (위반이 안 고쳐지는가)  ② 헤일로 (부작용이 주는가)
"""
import csv, os, sys, time
sys.path.insert(0, os.getcwd())
import cv2
import pselive3 as P3, psegpu_full as PGF, pse_bt1702 as BT, seam

SRC = r"C:/Users/dltmd/Downloads/pse_detectors final/pse_detectors/data/s1_flagged"
OUT, CSVP = "out_ab", "results_fix_ab.csv"
CFGS = (("기준", {}), ("워프", {"warp_alpha": True}),
        ("순방향", {"net_directional": True}),
        ("둘다", {"warp_alpha": True, "net_directional": True}))
COLS = ["clip", "frames", "before"] + [f"{t}_{k}" for t, _ in CFGS
                                       for k in ("판정", "헤일로", "마스크", "net차단")]

os.makedirs(OUT, exist_ok=True)
done = set()
if os.path.exists(CSVP):
    done = {r["clip"] for r in csv.DictReader(open(CSVP, encoding="utf-8-sig"))}
else:
    with open(CSVP, "w", newline="", encoding="utf-8-sig") as fh:
        csv.writer(fh).writerow(COLS)

files = sorted(f for f in os.listdir(SRC) if f.endswith(".mp4"))
for i, fn in enumerate(files, 1):
    name = os.path.splitext(fn)[0]
    if name in done:
        continue
    src = os.path.join(SRC, fn)
    cap = cv2.VideoCapture(src); nf = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); cap.release()
    t0 = time.time()
    before = BT.analyze(src, width=320)["failed_rules"] or ["적합"]
    ctrl = os.path.join(OUT, name + "_ctrl.mp4")
    if not os.path.exists(ctrl):
        seam.make_control(src, ctrl)
    base = seam.measure(src, ctrl)
    row = [name, nf, ";".join(before)]
    line = []
    for tag, kw in CFGS:
        dst = os.path.join(OUT, f"{name}_{tag}.mp4")
        try:
            r, _ = PGF.run(src, P3.Cfg(**kw), PGF.OptF(), video_out=dst,
                           warmup=4, progress=False)
            v = BT.analyze(dst, width=320)["failed_rules"] or ["적합"]
            m = seam.measure(src, dst)
            halo = round(max(m["halo"] - base["halo"], 0.0), 3)
            row += [";".join(v), halo, r["mean_mask_area"], r["net_blocked"]]
            line.append(f"{tag} {';'.join(v)}/h{halo}")
        except Exception as e:
            row += [f"실패:{type(e).__name__}", "", "", ""]
            line.append(f"{tag} 실패")
    with open(CSVP, "a", newline="", encoding="utf-8-sig") as fh:
        csv.writer(fh).writerow(row)
    print("[%d/%d] %-14s %5df 전:%-22s %s (%.0fs)"
          % (i, len(files), name, nf, ";".join(before), "  ".join(line),
             time.time() - t0), flush=True)
print("\n완료 ->", CSVP)
