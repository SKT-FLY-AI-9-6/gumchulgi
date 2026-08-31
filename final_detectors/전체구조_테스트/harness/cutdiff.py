# -*- coding: utf-8 -*-
"""CPU 기준판과 GPU 판의 컷 결정을 **프레임 단위로** 대조한다.
숫자만 맞춘 게 아니라 같은 프레임에서 같은 판단을 하는지 본다."""
import os, sys
sys.path.insert(0, os.getcwd())
import cv2, numpy as np, torch
import pselive3 as P3
import psegpu_full as PGF

clip = sys.argv[1]
cap = cv2.VideoCapture(clip)
fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
frames = []
while True:
    ok, f = cap.read()
    if not ok:
        break
    frames.append(f)
cap.release()
H, W = frames[0].shape[:2]
cfg = P3.Cfg()

# --- CPU 기준판의 컷 결정 (pselive3._is_cut 을 그대로 재사용)
cpu = P3.LiveFilter3(fps, (H, W), cfg)
s = cfg.short_side / min(H, W) if min(H, W) > cfg.short_side else 1.0
cpu_cuts = []
for i, f in enumerate(frames):
    small = cv2.resize(f, (int(round(W*s)), int(round(H*s))),
                       interpolation=cv2.INTER_AREA) if s < 1.0 else f
    if cpu._is_cut(small):
        cpu_cuts.append(i)

# --- GPU 판의 컷 결정
gpu = PGF.FullFilterGPU(fps, (H, W), cfg, PGF.OptF())
gpu_cuts = []
for i, f in enumerate(frames):
    gpu.h_in.copy_(torch.from_numpy(np.ascontiguousarray(f)))
    gpu.d_in.copy_(gpu.h_in)
    dt = gpu.dt
    xe = gpu.d_in.to(dt) / 255.0
    c = gpu._cut_gate((xe * gpu.w601).sum(-1) * 255.0)
    if float(c) > 0.5:
        gpu_cuts.append(i)

sc, sg = set(cpu_cuts), set(gpu_cuts)
print(f"{os.path.basename(clip)}  프레임 {len(frames)}")
print(f"  CPU 컷 {len(sc)}  GPU 컷 {len(sg)}  일치 {len(sc & sg)}")
print(f"  GPU 만 (과검출) {sorted(sg - sc)}")
print(f"  CPU 만 (미검출) {sorted(sc - sg)}")
