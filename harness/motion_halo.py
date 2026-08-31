# -*- coding: utf-8 -*-
"""가설 검증: 카메라가 움직일수록 A 의 헤일로가 큰가.

알파맵이 워프되지 않으므로(pselive3.py:291), 전역 이동이 큰 클립일수록
직전 마스크가 엉뚱한 곳에 얹혀 잔상이 커질 것이다.
움직임 지표 = 프레임 간 위상상관 변위의 중앙값(px, 320폭 기준).
"""
import csv, os, sys
import cv2, numpy as np

D = os.environ.get("PSE_EXPLORE", "data/explore_100")
rows = list(csv.DictReader(open("results_reels_3way.csv", encoding="utf-8-sig")))

def motion(path, step=4, cap_n=140):
    cap = cv2.VideoCapture(path)
    prev, ds, k = None, [], 0
    while len(ds) < cap_n:
        ok, f = cap.read()
        if not ok: break
        k += 1
        if k % step: continue
        g = cv2.cvtColor(cv2.resize(f, (320, int(320*f.shape[0]/f.shape[1]))),
                         cv2.COLOR_BGR2GRAY).astype(np.float32)
        if prev is not None and prev.shape == g.shape:
            (dx, dy), resp = cv2.phaseCorrelate(prev, g)
            if resp > 0.05:                     # 신뢰할 만한 정렬만
                ds.append((dx*dx + dy*dy) ** .5)
        prev = g
    cap.release()
    return float(np.median(ds)) if ds else 0.0

out = []
for i, r in enumerate(rows, 1):
    m = motion(os.path.join(D, r["clip"] + ".mp4"))
    ha, hd = float(r["A_halo"] or 0), float(r["Dste_halo"] or 0)
    out.append((r["clip"], m, ha, hd))
    print("%3d %-13s 이동 %6.2fpx  A %6.2f  D %6.2f" % (i, r["clip"], m, ha, hd), flush=True)

m = np.array([o[1] for o in out]); a = np.array([o[2] for o in out]); d = np.array([o[3] for o in out])
def pear(x, y):
    x, y = x - x.mean(), y - y.mean()
    return float((x*y).sum() / (np.sqrt((x*x).sum()*(y*y).sum()) + 1e-9))
print("\n=== 상관계수 (이동량 vs 헤일로) ===")
print("  A     r = %+.3f" % pear(m, a))
print("  D_ste r = %+.3f" % pear(m, d))
lo, hi = m <= np.median(m), m > np.median(m)
print("\n정지 쪽 %d편: A 평균 %.1f / D %.1f" % (lo.sum(), a[lo].mean(), d[lo].mean()))
print("이동 쪽 %d편: A 평균 %.1f / D %.1f" % (hi.sum(), a[hi].mean(), d[hi].mean()))
with open("motion_halo.csv","w",newline="",encoding="utf-8-sig") as fh:
    w=csv.writer(fh); w.writerow(["clip","motion_px","A_halo","Dste_halo"]); w.writerows(out)
