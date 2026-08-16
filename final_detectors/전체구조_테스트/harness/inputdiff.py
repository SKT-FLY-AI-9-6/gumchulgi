# -*- coding: utf-8 -*-
"""검출 입력값을 CPU 와 GPU 에서 **직접 꺼내 비교**한다.

로직은 다 같은데 마스크가 다르다면(0.750 vs 0.875) 입력이 다른 것이다.
지금까지 '같을 것'이라고 가정만 하고 한 번도 재지 않았다.
"""
import os, sys
sys.path.insert(0, os.getcwd())
import cv2, numpy as np, torch
import torch.nn.functional as F
import psecore as PC, pselive3 as P3, psegpu_full as PGF

clip = sys.argv[1] if len(sys.argv) > 1 else "synth/14_stripes_drift_10pairs.mp4"
cap = cv2.VideoCapture(clip)
W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
frames = []
while True:
    ok, f = cap.read()
    if not ok: break
    frames.append(f)
cap.release()
c = P3.Cfg()

# --- CPU 가 쓰는 분석 해상도와 입력
s = c.short_side / min(W, H) if min(W, H) > c.short_side else 1.0
aw_c, ah_c = max(2, int(W * s)), max(2, int(H * s))

# --- GPU 가 쓰는 분석 해상도
g = PGF.FullFilterGPU(30.0, (H, W), c, PGF.OptF())
aw_g, ah_g = g.aw, g.ah
print(f"영상 {W}x{H}   CPU 분석 {aw_c}x{ah_c}   GPU 분석 {aw_g}x{ah_g}"
      f"   {'일치' if (aw_c, ah_c) == (aw_g, ah_g) else '★ 불일치'}")

dev = torch.device("cuda")
for i in [0, 20, 40, 60]:
    f = frames[i]
    # CPU 경로
    sm = cv2.resize(f, (aw_c, ah_c), interpolation=cv2.INTER_AREA) if s != 1.0 else f
    lin_c = PC._LIN[sm]                                    # (h,w,3) BGR 선형
    # GPU 경로
    d_in = torch.from_numpy(np.ascontiguousarray(f)).to(dev)
    xe = d_in.to(torch.float32) / 255.0
    lin = torch.where(xe <= 0.04045, xe / 12.92,
                      ((xe + 0.055) / 1.055).pow(2.4)).permute(2, 0, 1).unsqueeze(0)
    xe3 = xe.permute(2, 0, 1).unsqueeze(0)

    def eotf(t):
        return torch.where(t <= 0.04045, t / 12.92, ((t + 0.055) / 1.055).pow(2.4))

    variants = {}
    # 1) 현재: 선형 도메인 축소
    variants["선형축소(현재)"] = F.interpolate(lin, size=(ah_g, aw_g), mode="area")
    # 2) 감마 도메인 축소 -> 선형화
    xs = F.interpolate(xe3, size=(ah_g, aw_g), mode="area")
    variants["감마축소"] = eotf(xs)
    # 3) 감마 축소 + uint8 재양자화 (CPU 의 cv2.resize 결과와 같은 자리)
    variants["감마축소+uint8"] = eotf(torch.round(xs * 255.0) / 255.0)
    # 4~6) 리샘플러를 바꿔본다 — cv2.INTER_AREA 는 분수 가중 면적평균이라
    #      torch 의 area(=adaptive_avg_pool2d, 정수 경계)와 다르다.
    for m in ["bilinear", "bicubic"]:
        xb = F.interpolate(xe3, size=(ah_g, aw_g), mode=m,
                           align_corners=False, antialias=True)
        variants[f"감마{m}+AA"] = eotf(torch.round(xb * 255.0) / 255.0)
    xl = F.interpolate(xe3, size=(ah_g, aw_g), mode="bilinear",
                       align_corners=False, antialias=False)
    variants["감마bilinear"] = eotf(torch.round(xl * 255.0) / 255.0)

    print(f"  f{i}  CPU평균 {lin_c.mean():.5f}")
    for name, t in variants.items():
        lg = t[0].permute(1, 2, 0).cpu().numpy()
        d = np.abs(lin_c - lg)
        print(f"      {name:<16} 평균차 {d.mean():.6f}  최대차 {d.max():.6f}  "
              f"GPU평균 {lg.mean():.5f}  임계초과화소 {float((d > 0.10).mean())*100:.2f}%")
