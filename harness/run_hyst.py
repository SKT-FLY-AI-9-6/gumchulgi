# -*- coding: utf-8 -*-
"""순 방향성 관문의 진동을 잡는 두 변형 시험.

Db2LyhvyHI5 는 관문이 임계 근처에서 진동해 마스크가 깜빡이고, 그 때문에
마스크 면적이 줄었는데도 헤일로가 역행한 유일한 클립이다.

  히스 : net_hyst 0.7 — 열려 있으면 더 낮은 임계에서만 닫는다
  유지 : net_hold    — 한 번 열리면 hold_s 동안 열어 둔다

큰 승리 클립 3편을 같이 넣어 **감소폭을 잃지 않는지** 확인한다.
"""
import csv, os, sys, time
sys.path.insert(0, os.getcwd())
import numpy as np, cv2
import pselive3 as P3, psegpu_full as PGF, pse_bt1702 as BT, seam

S = os.environ.get("PSE_FLAGGED", "data/s1_flagged")
CLIPS = ["Db2LyhvyHI5",   # 역행 (22.74 -> 26.93)
         "Db2BKAWvAXs",   # 최대 승리 (52.44 -> 1.12)
         "Db155zGxJRf",   # 큰 승리 (47.26 -> 27.62)
         "Db2D03pxZjy"]   # 플래시 위반 — 적합 유지되어야 한다
CFGS = (("기준", {}),
        ("순방향", {"net_directional": True}),
        ("히스0.7", {"net_directional": True, "net_hyst": 0.7}),
        ("히스0.5", {"net_directional": True, "net_hyst": 0.5}),
        ("유지", {"net_directional": True, "net_hold": True}))
OUT, CSVP = "out_hyst", "results_hyst.csv"
os.makedirs(OUT, exist_ok=True)


def toggles(path):
    """마스크 켜짐/꺼짐 전환 횟수 — 헤일로 역행의 직접 원인."""
    return None


rows = []
for name in CLIPS:
    src = os.path.join(S, name + ".mp4")
    before = ";".join(BT.analyze(src, width=320)["failed_rules"] or ["적합"])
    ctrl = os.path.join(OUT, name + "_ctrl.mp4")
    if not os.path.exists(ctrl):
        seam.make_control(src, ctrl)
    base = seam.measure(src, ctrl)
    for tag, kw in CFGS:
        t0 = time.time()
        dst = os.path.join(OUT, f"{name}_{tag}.mp4")
        # 프레임별 마스크 면적을 받아 토글 수를 센다
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
        v = ";".join(BT.analyze(dst, width=320)["failed_rules"] or ["적합"])
        rows.append([name, before, tag, v, halo, r["mean_mask_area"],
                     r["net_blocked"], tg, r["frames"]])
        print("%-13s %-8s 판정 %-12s 헤일로 %7.3f  마스크 %.4f  차단 %4d  토글 %3d (%.0fs)"
              % (name, tag, v, halo, r["mean_mask_area"], r["net_blocked"], tg,
                 time.time() - t0), flush=True)
    print(flush=True)

with open(CSVP, "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.writer(fh)
    w.writerow(["clip", "before", "config", "after", "halo", "mask",
                "net_blocked", "toggles", "frames"])
    w.writerows(rows)
print("완료 ->", CSVP)
