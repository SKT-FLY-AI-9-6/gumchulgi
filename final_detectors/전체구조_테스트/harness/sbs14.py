# -*- coding: utf-8 -*-
"""CPU 와 GPU 를 **같은 입력으로 한 프레임씩 나란히** 돌리며 중간값을 대조한다.

검출(마스크)에서 갈리는지, 적용(알파·kmax)에서 갈리는지 확정한다.
"""
import os, sys
sys.path.insert(0, os.getcwd())
import cv2, numpy as np, torch
import psecore as PC, pselive3 as P3, psegpu_full as PGF

clip = sys.argv[1] if len(sys.argv) > 1 else "synth/14_stripes_drift_10pairs.mp4"
cap = cv2.VideoCapture(clip); fps = cap.get(cv2.CAP_PROP_FPS) or 30.0; fr = []
while True:
    ok, f = cap.read()
    if not ok: break
    fr.append(f)
cap.release()
H, W = fr[0].shape[:2]
cfg = P3.Cfg(); cfg.guard = False

cpu = P3.LiveFilter3(fps, None, cfg) if False else None
# 분석 해상도
s = cfg.short_side / min(H, W) if min(H, W) > cfg.short_side else 1.0
aw, ah = int(round(W * s)), int(round(H * s))
cpu = P3.LiveFilter3(fps, (ah, aw), cfg)
gpu = PGF.FullFilterGPU(fps, (H, W), cfg, PGF.OptF())

print(f"{clip}  {W}x{H} -> 분석 {aw}x{ah}")
print(f"{'f':>4}{'CPU마스크':>10}{'GPU마스크':>10}{'마스크IoU':>10}"
      f"{'CPU알파':>9}{'GPU알파':>9}{'CPU출력Y':>10}{'GPU출력Y':>10}")
rows = []
for i, f in enumerate(fr):
    small = cv2.resize(f, (aw, ah), interpolation=cv2.INTER_AREA) if s < 1.0 else f
    # --- CPU 한 프레임
    oc = cpu.push(f, small)
    Mc = cpu.hold > 0
    ac = cpu.alpha
    # --- GPU 한 프레임
    og = gpu.push(f)
    Mg = (gpu.hold > 0).cpu().numpy()
    ag = gpu.alpha_prev.squeeze().cpu().numpy()

    inter = float((Mc & Mg).sum()); union = float((Mc | Mg).sum())
    iou = inter / union if union > 0 else 1.0
    yc = float(PC._LIN[oc][..., 1].mean())
    yg = float(PC._LIN[og][..., 1].mean())
    rows.append((Mc.mean(), Mg.mean(), iou, ac.mean(), ag.mean(), yc, yg))
    if i < 8 or i % 20 == 0:
        print(f"{i:>4}{Mc.mean():>10.4f}{Mg.mean():>10.4f}{iou:>10.4f}"
              f"{ac.mean():>9.4f}{ag.mean():>9.4f}{yc:>10.5f}{yg:>10.5f}")

r = np.array(rows)
print(f"\n평균  CPU마스크 {r[:,0].mean():.4f}  GPU마스크 {r[:,1].mean():.4f}  "
      f"IoU {r[:,2].mean():.4f}")
print(f"평균  CPU알파 {r[:,3].mean():.4f}  GPU알파 {r[:,4].mean():.4f}")
print(f"평균  CPU출력Y {r[:,5].mean():.5f}  GPU출력Y {r[:,6].mean():.5f}")
