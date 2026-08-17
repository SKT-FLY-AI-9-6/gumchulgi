# -*- coding: utf-8 -*-
"""편두통 축(M1 정적패턴 · M2 색상)으로도 필터 효과를 잰다.

지금까지는 BT.1702(발작) 기준으로만 쟀다. 편두통 축은 국제 표준이 없어
pse_migraine.py 가 WARN 전용으로 분리해 둔 것인데, 필터가 이 축에서 **나쁘게
만들지 않는지**는 확인해야 한다 — 발작을 막으려고 편두통을 유발하면 안 된다.

t5(보수) 로 잰다: 패턴 1~4 cpd·대비 10% 이상, 청색 가중.
cpd 상한 때문에 width 640 으로 돌린다 (모듈 주석 참고).
"""
import os, sys, glob, csv
sys.path.insert(0, os.getcwd())
import cv2, numpy as np
import pselive3 as P3, psegpu_full as PGF, rawmeasure as RM, pseenv as ENV
import pse_migraine as MG

CLIPS = sys.argv[1:] or (sorted(glob.glob("_dfull/*_360.mp4"))
                         + sorted(glob.glob("_yt/*.mp4"))[:8])


def score(path):
    """M1/M2 지표를 비교 가능한 숫자 묶음으로 편다."""
    r = MG.analyze(path, tier="t5", width=640)
    out = {"score": float(r.get("score", 0.0))}
    for grp in ("pattern", "color"):
        v = r.get(grp)
        if isinstance(v, dict):
            for k, x in v.items():
                if isinstance(x, (int, float)):
                    out[f"{grp}.{k}"] = float(x)
        elif isinstance(v, (int, float)):
            out[grp] = float(v)
    return out, r


rows = []
print(f"{'클립':<22}{'지표':<22}{'원본':>10}{'A후':>10}  변화")
for c in CLIPS:
    if not os.path.exists(c):
        continue
    cap = cv2.VideoCapture(c); fps = cap.get(cv2.CAP_PROP_FPS) or 30.0; cap.release()
    try:
        s0, r0 = score(c)
        _, og = PGF.run(c, P3.Cfg(), PGF.OptF(), warmup=2)
        tmp = ENV.tmp("mg.mkv"); RM.write_lossless(og, tmp, fps)
        s1, r1 = score(tmp); os.remove(tmp)
    except Exception as e:
        print(f"{os.path.basename(c)[:20]:<22}오류 {type(e).__name__}: {str(e)[:60]}")
        continue
    keys = [k for k in s0 if k in s1]
    if not keys:
        print(f"{os.path.basename(c)[:20]:<22}(수치 지표 없음) {list(r0)[:6]}")
        continue
    for k in keys:
        a, b = s0[k], s1[k]
        if abs(a) < 1e-9 and abs(b) < 1e-9:
            continue
        mark = "  <- 악화" if b > a + 1e-6 else ("  개선" if b < a - 1e-6 else "")
        print(f"{os.path.basename(c)[:20]:<22}{k:<22}{a:>10.3f}{b:>10.3f}{mark}",
              flush=True)
        rows.append({"clip": os.path.basename(c), "metric": k,
                     "before": round(a, 4), "after": round(b, 4),
                     "worse": int(b > a + 1e-6)})

if rows:
    with open("validation/eval_migraine.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    n_w = sum(r["worse"] for r in rows)
    print(f"\n지표 {len(rows)}건 중 악화 {n_w}건")
    print("CSV -> validation/eval_migraine.csv")
