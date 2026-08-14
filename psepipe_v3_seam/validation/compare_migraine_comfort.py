# -*- coding: utf-8 -*-
"""pse_migraine(티어 WARN) vs pse_comfort(연속 점수) — 합성 자극 7종 대조."""
import numpy as np
import cv2
import pse_migraine
import pse_comfort

fps, n, w, h = 30.0, 60, 320, 568


def grating(cpd, contrast, mean=0.5, deg=25.0):
    cycles = cpd * deg
    x = np.arange(w, dtype=np.float32)
    wave = mean * (1.0 + contrast * np.sign(np.sin(2 * np.pi * cycles * x / w)))
    g = np.tile((np.power(np.clip(wave, 0, 1), 1 / 2.4) * 255).astype(np.uint8), (h, 1))
    return cv2.merge([g, g, g])


def solid(b, g, r):
    f = np.zeros((h, w, 3), np.uint8)
    f[..., 0] = b
    f[..., 1] = g
    f[..., 2] = r
    return f


gray = solid(128, 128, 128)
blue = solid(255, 0, 0)
red = solid(0, 0, 255)


def subtle(i):
    # 관문 미달 15Hz 플리커: 선형 0.30<->0.34 (ΔY 0.04 < PSE 관문 0.10)
    v = 0.34 if i % 2 == 0 else 0.30
    val = int(round((v ** (1 / 2.4)) * 255))
    return solid(val, val, val)


clips = {
    "무지 회색": [gray] * n,
    "3cpd 대비90%": [grating(3.0, 0.9)] * n,
    "3cpd 대비15%": [grating(3.0, 0.15)] * n,
    "경계(어둡고 12%)": [grating(3.0, 0.12, mean=0.35)] * n,
    "청색 지속": [blue] * n,
    "적-청 6.7Hz 교대": [red if (i // 2) % 2 == 0 else blue for i in range(n)],
    "은은한 15Hz 플리커": [subtle(i) for i in range(n)],
}

print(f"{'클립':<18}{'migraine t5':<26}{'comfort':<9}성분 f/p/c/g")
print("-" * 78)
for name, frames in clips.items():
    r = pse_migraine.analyze(frames, tier="t5", fps=fps)
    tag = "WARN" if r["warn"] else "ok"
    mg = (f"{tag:<5} 패턴{r['pattern']['warn_seconds']:4.1f}s"
          f" 색{r['color']['warn_seconds']:4.1f}s")
    cs = pse_comfort.Stream(fps)
    for f in frames:
        cs.push(f)
    o = cs.summary()
    c = o["components"]
    comps = (f"{c.get('flash', 0):3.0f}/{c.get('pattern', 0):3.0f}"
             f"/{c.get('color', 0):3.0f}/{c.get('glare', 0):3.0f}")
    print(f"{name:<18}{mg:<28}{o['score']:>5.1f}    {comps}")
