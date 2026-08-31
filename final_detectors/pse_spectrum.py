# -*- coding: utf-8 -*-
"""
pse_spectrum.py  —  주파수 영역 플리커 에너지 측정  [정직성 검증용]
====================================================================
왜 필요한가
  BT.1702 판정은 **인접 프레임 간 변화량**을 본다. 그래서 영상을 60fps 로 보간하면
  같은 밝기 변화가 두 프레임에 나뉘어 프레임당 변화량이 절반이 되고,
  **실제 점멸은 그대로인데 판정만 통과**할 수 있다. 전형적인 지표 게이밍이다.

  그래서 프레임률과 무관한 척도가 필요하다: 시간 신호를 실제 **주파수**로 분해해
  광과민성 위험대역(3~30Hz, 문헌상 15~20Hz 최대)의 **에너지**를 잰다.
  이 값이 안 줄면 아무리 판정을 통과해도 실제로는 안전해지지 않은 것이다.

측정
  · 블록별 평균 휘도 시계열 -> 추세 제거 -> Hann 창 -> FFT
  · 3~30Hz 대역 에너지, 그리고 민감도 최대인 10~20Hz 대역 에너지를 따로 집계
  · 프레임률이 달라도 물리적 Hz 기준이라 **직접 비교 가능**
"""
from __future__ import annotations
import argparse, json
import numpy as np
import cv2

from pse_analyze import SDR_PEAK, decode_linear

W_Y = np.array([0.2126, 0.7152, 0.0722], np.float32)
BAND_ALL = (3.0, 30.0)     # PSE 위험대역
BAND_PEAK = (10.0, 20.0)   # 민감도 최대 구간 (Epilepsy Foundation 2022: 15~20Hz)


def measure(path: str, block: int = 40, width: int = 320,
            t0: float | None = None, t1: float | None = None, verbose=False) -> dict:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise IOError(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frames = []
    i = 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        t = i / fps
        i += 1
        if t0 is not None and t < t0:
            continue
        if t1 is not None and t > t1:
            break
        h0, w0 = f.shape[:2]
        sm = cv2.resize(f, (width, max(2, int(h0 * width / w0))), interpolation=cv2.INTER_AREA)
        Y = (decode_linear(sm) @ W_Y) * SDR_PEAK
        gh, gw = max(1, Y.shape[0] // block), max(1, Y.shape[1] // block)
        Yb = cv2.resize(Y, (gw, gh), interpolation=cv2.INTER_AREA)
        frames.append(Yb.astype(np.float32))
    cap.release()
    if len(frames) < 8:
        return {"video": path, "fps": fps, "frames": len(frames),
                "band_3_30": 0.0, "band_10_20": 0.0}
    X = np.stack(frames)                       # (T, gh, gw)
    T = X.shape[0]
    sig = X.reshape(T, -1)
    sig = sig - sig.mean(0, keepdims=True)     # 추세(정적 성분) 제거
    win = np.hanning(T).astype(np.float32)[:, None]
    F = np.fft.rfft(sig * win, axis=0)
    P = (np.abs(F) ** 2)
    freqs = np.fft.rfftfreq(T, d=1.0 / fps)
    # 창 함수 보정 + 블록 평균. 프레임 수가 달라도 비교 가능하도록 T 로 정규화.
    norm = (win ** 2).sum() * max(T, 1)
    def band(lo, hi):
        m = (freqs >= lo) & (freqs <= hi)
        return float(P[m].sum() / norm) if m.any() else 0.0
    return {"video": path, "fps": round(fps, 2), "frames": T,
            "band_3_30": round(band(*BAND_ALL), 3),
            "band_10_20": round(band(*BAND_PEAK), 3)}


def brief(r, ref=None):
    s = (f"  {r['video']:<34} {r['fps']:>5.1f}fps  "
         f"3~30Hz {r['band_3_30']:>9.2f}  10~20Hz {r['band_10_20']:>9.2f}")
    if ref:
        a = r['band_3_30'] / max(ref['band_3_30'], 1e-9)
        b = r['band_10_20'] / max(ref['band_10_20'], 1e-9)
        s += f"   (원본 대비 {a*100:5.1f}% / {b*100:5.1f}%)"
    return s


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("srcs", nargs="+")
    ap.add_argument("--t0", type=float, default=None)
    ap.add_argument("--t1", type=float, default=None)
    a = ap.parse_args()
    ref = None
    for p in a.srcs:
        r = measure(p, t0=a.t0, t1=a.t1)
        if ref is None:
            ref = r
        print(brief(r, ref if r is not ref else None), flush=True)
