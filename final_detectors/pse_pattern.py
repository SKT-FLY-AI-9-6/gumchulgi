# -*- coding: utf-8 -*-
"""
pse_pattern.py  —  B1 규칙적 패턴(줄무늬/격자) 검출   [지금까지 미구현이던 마지막 축]
========================================================================
근거 기준
  · ITU-R BT.1702 / Ofcom 2.12 / 국내 가이드북 2026 §5.4 "규칙적 패턴"
  · Epilepsy Foundation 2022: "**5쌍 이상**의 명확히 구분되는 명암 줄무늬
    (부드럽게 이동하면 **8쌍**), 화면의 25% 이상, 0.5초 이상 지속"
  · Ofcom: 정지 줄무늬는 화면 **40%** 이상, 방향전환·흔들림·점멸·대비반전이
    있으면 **25%** 이상이면 불허. 어두운 바 < 160 cd/m², 밝은 바와 차이 ≥ 20 cd/m².

구현
  1) 프레임 휘도의 2D FFT 로 **지배적 공간주파수와 방향**을 찾는다.
  2) 그 주파수·방향의 **Gabor 필터**(복소)로 국소 진폭·위상을 구한다.
     정규화상 진폭 A ≈ 2|response| 이고 명암 진폭차(peak-to-trough) ≈ 4|response|.
  3) 픽셀 단위로 "줄무늬 조건"(진폭차 ≥ 20 cd/m², 어두운 바 < 160 cd/m²)을
     만족하는 면적비를 재고, 화면을 가로지르는 **줄 쌍 수**를 추정한다.
  4) 프레임 간 **위상 변화**로 정지/이동/대비반전을 분류해 면적 임계를 정한다.
"""
from __future__ import annotations
import argparse, json
import numpy as np
import cv2

# pse_analyze(색 대립축 검출기) 의존을 끊었다 — BT.1702 규격에 없는 채널이라
# 규격 준수 판정에서 제외했기 때문. 필요한 휘도 변환만 여기서 정의한다.
SDR_PEAK = 200.0          # cd/m^2, BT.1702 NOTE 3 (SDR peak white)
EOTF_GAMMA = 2.4          # BT.1886


def decode_linear(frame_bgr):
    """8bit BGR -> 선형광 RGB [0,1] (BT.1886 EOTF)"""
    rgb = frame_bgr[..., ::-1].astype(np.float32) / 255.0
    return np.power(rgb, EOTF_GAMMA, dtype=np.float32)

W_Y = np.array([0.2126, 0.7152, 0.0722], np.float32)

PAIRS_MIN_STATIC = 5      # 정지 패턴 최소 줄 쌍
PAIRS_MIN_DRIFT = 8       # 부드럽게 이동하는 패턴 최소 줄 쌍
AREA_STATIC = 0.40        # 정지 패턴 면적 임계
AREA_DYNAMIC = 0.25       # 이동/반전/점멸 패턴 면적 임계
LUM_DIFF_MIN = 20.0       # cd/m^2, 밝은 바 - 어두운 바
DARK_BAR_MAX = 160.0      # cd/m^2, 어두운 바가 이보다 밝으면 위험 없음
MIN_DURATION_S = 0.5      # 이 시간 이상 지속돼야 위험
DRIFT_PHASE_THR = 0.15    # rad/frame, 이보다 크면 '움직이는 패턴'
CONCENTRATION_MIN = 0.75  # 방향 선택도 하한 — 규칙적 패턴 vs 자연 텍스처를 가른다.
                          # 재보정(2026-08-10): 줄무늬·격자 0.99~1.00 vs 텍스처(쌍>=5) 최대 0.56.
                          # 이전 값 0.12 는 저주파 편향 척도에 맞춘 것이라 노이즈를 오탐했다.


def _dominant_freq(Y, fmin=2.0, fmax=60.0):
    """
    지배적 공간주파수와 방향.  **줄 쌍 수는 '화면을 가로지르는 주기 수'** 로 센다.
    (FFT 인덱스를 화면 높이 기준으로 정규화하면 세로 줄무늬에서 h/w 배 부풀어
     3쌍짜리가 5.3쌍으로 잡혔다 — 실측 오탐.)
      fx = 가로로 가로지르는 주기 수,  fy = 세로로 가로지르는 주기 수
      pairs = sqrt(fx^2 + fy^2),  픽셀 주기 = 1/sqrt((fx/w)^2 + (fy/h)^2)
    """
    h, w = Y.shape
    win = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    F = np.fft.fftshift(np.abs(np.fft.fft2((Y - Y.mean()) * win)))
    cy, cx = h // 2, w // 2
    yy, xx = np.mgrid[0:h, 0:w]
    fy = (yy - cy).astype(np.float32)          # cycles / image-height
    fx = (xx - cx).astype(np.float32)          # cycles / image-width
    pairs_map = np.sqrt(fx ** 2 + fy ** 2)
    band = (pairs_map >= fmin) & (pairs_map <= fmax)
    if not band.any():
        return 0.0, 0.0, 0.0, 0.0
    idx = int(np.argmax(np.where(band, F, 0.0)))
    py, px = idx // w, idx % w
    fxv, fyv = float(fx[py, px]), float(fy[py, px])
    pairs = float(np.hypot(fxv, fyv))
    period_px = 1.0 / max(np.hypot(fxv / max(w, 1), fyv / max(h, 1)), 1e-6)
    theta = float(np.arctan2(fyv / max(h, 1), fxv / max(w, 1)))

    # **방향 선택도** — 규칙적 패턴인지 자연 텍스처인지 가르는 척도.
    #
    # 예전에는 "피크 원반 / 밴드 전체" 로 쟀는데, 그 값은 **저주파에 편향**된다.
    # 저주파 블롭 노이즈는 주기적이어서가 아니라 그냥 저주파라서 에너지가 원점
    # 근처에 몰리고, 그 결과 0.31 이 나와 임계 0.12 를 넘겨 오탐했다(실측).
    #
    # 진짜 판별점은 "같은 공간주파수에서 에너지가 **한 방향**에 몰려 있는가"다.
    # 줄무늬·격자는 링 위 한 지점(및 대칭점)에만 에너지가 있고, 등방성 텍스처는
    # 링 전체에 고르게 퍼진다. 그래서 같은 반경 링을 기준으로 정규화한다.
    Pw = F ** 2
    r_pk = float(np.hypot(px - cx, py - cy))
    ring = (pairs_map >= max(1.0, r_pk - 2.0)) & (pairs_map <= r_pk + 2.0)
    if not ring.any():
        return pairs, period_px, theta, 0.0
    dd = np.sqrt((yy - py) ** 2 + (xx - px) ** 2)
    dm = np.sqrt((yy - (h - 1 - py)) ** 2 + (xx - (w - 1 - px)) ** 2)
    disc = ((dd <= 3.0) | (dm <= 3.0)) & ring
    conc = float(Pw[disc].sum() / max(Pw[ring].sum(), 1e-9))
    return pairs, period_px, theta, conc


GABOR_SCALE_W = 96        # Gabor 는 이 폭으로 줄여서 계산한다 (아래 주석 참조)


def _gabor(Y, period, theta):
    """검출된 주파수·방향의 복소 Gabor 응답 (패턴 이동/반전 위상 추적용).

    **축소해서 계산한다.** Gabor 는 오직 위상(정지/이동/반전 분류)에만 쓰이고,
    위상은 강한 영역의 평균으로 뽑는 거의 전역적인 양이라 해상도가 필요 없다.
    반면 비용은 커널 크기의 제곱으로 늘어나 원해상도에서는 프레임당 90ms 가
    걸렸다(1,000편이면 4코어로 7.5시간). 96px 로 줄이면 결과는 같고 훨씬 빠르다.
    면적 판정은 이 함수가 아니라 dilate/erode 로 원해상도에서 그대로 잰다.
    """
    if period <= 1.5:
        return np.zeros_like(Y), np.zeros_like(Y)
    h, w = Y.shape
    sc = min(1.0, GABOR_SCALE_W / float(w))
    if sc < 1.0:
        Ys = cv2.resize(Y, (max(8, int(round(w * sc))), max(8, int(round(h * sc)))),
                        interpolation=cv2.INTER_AREA)
        per = max(2.0, period * sc)
    else:
        Ys, per = Y, period

    sigma = max(2.0, 1.5 * per)
    ks = int(max(7, min(41, round(sigma * 4) | 1)))
    ax = np.arange(ks) - ks // 2
    X, Yk = np.meshgrid(ax, ax)
    rot = X * np.cos(theta) + Yk * np.sin(theta)
    env = np.exp(-(X ** 2 + Yk ** 2) / (2 * sigma ** 2)).astype(np.float32)
    env /= env.sum()                          # 합=1 정규화 -> |resp| ≈ A/2
    kc = (env * np.cos(2 * np.pi * rot / per)).astype(np.float32)
    ks_ = (env * np.sin(2 * np.pi * rot / per)).astype(np.float32)
    re = cv2.filter2D(Ys, -1, kc, borderType=cv2.BORDER_REFLECT)
    im = cv2.filter2D(Ys, -1, ks_, borderType=cv2.BORDER_REFLECT)
    if sc < 1.0:                              # 호출부와 크기를 맞춰 돌려준다
        re = cv2.resize(re, (w, h), interpolation=cv2.INTER_LINEAR)
        im = cv2.resize(im, (w, h), interpolation=cv2.INTER_LINEAR)
    return re, im


def analyze(path: str, width: int = 320, verbose: bool = True) -> dict:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise IOError(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    series, prev_phase = [], None
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        h0, w0 = frame.shape[:2]
        small = cv2.resize(frame, (width, max(2, int(h0 * width / w0))),
                           interpolation=cv2.INTER_AREA)
        lin = decode_linear(small)
        Y = (lin @ W_Y) * SDR_PEAK              # cd/m^2
        h, w = Y.shape
        pairs, period_px, theta, conc = _dominant_freq(Y)
        Yf = Y.astype(np.float32)
        re, im = _gabor(Yf, period_px, theta)
        # **명암 바 차이는 Gabor 진폭이 아니라 국소 최대-최소로 잰다.**
        # 사각파는 기본파 진폭이 실제 진폭의 4/pi(≈1.27)배라, Gabor 로 재면
        # 16 cd/m^2 짜리가 20.4 로 부풀어 안전한 저대비 줄무늬를 오탐했다(실측).
        ksz = int(max(3, min(31, round(period_px) | 1)))
        ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksz, ksz))
        hi_bar = cv2.dilate(Yf, ker); lo_bar = cv2.erode(Yf, ker)
        p2t = hi_bar - lo_bar                   # 밝은 바 - 어두운 바 (cd/m^2)
        strong = (p2t >= LUM_DIFF_MIN) & (lo_bar < DARK_BAR_MAX) & (conc >= CONCENTRATION_MIN)
        area = float(strong.mean())
        # 위상 (패턴 이동/반전 판정용) — 강한 영역의 평균 위상
        if strong.any():
            ph = float(np.angle(np.mean((re + 1j * im)[strong])))
        else:
            ph = 0.0
        dphase = 0.0
        if prev_phase is not None:
            d = ph - prev_phase
            dphase = float(abs((d + np.pi) % (2 * np.pi) - np.pi))
        prev_phase = ph
        series.append({"i": idx, "period": round(period_px, 2), "conc": round(conc, 4),
                       "area": round(area, 4), "pairs": round(float(pairs), 2),
                       "dphase": round(dphase, 4)})
        idx += 1
        if verbose and idx % 300 == 0:
            print(f"    ... {idx} frames", flush=True)
    cap.release()

    n = len(series)
    dph = np.array([s["dphase"] for s in series])
    moving = dph > DRIFT_PHASE_THR
    viol = np.zeros(n, bool)
    for i, s in enumerate(series):
        mv = bool(moving[i])
        need_pairs = PAIRS_MIN_DRIFT if mv else PAIRS_MIN_STATIC
        need_area = AREA_DYNAMIC if mv else AREA_STATIC
        viol[i] = (s["pairs"] >= need_pairs) and (s["area"] >= need_area)
    # 0.5초 이상 지속된 것만 위험으로 인정
    minrun = max(1, int(round(MIN_DURATION_S * fps)))
    out = np.zeros(n, bool)
    st = None
    for i in range(n + 1):
        v = viol[i] if i < n else False
        if v and st is None:
            st = i
        elif not v and st is not None:
            if i - st >= minrun:
                out[st:i] = True
            st = None
    segs, st = [], None
    for i in range(n + 1):
        v = out[i] if i < n else False
        if v and st is None:
            st = i
        elif not v and st is not None:
            segs.append((round(st / fps, 2), round(i / fps, 2))); st = None
    return {"video": path, "fps": round(fps, 3), "frames": n,
            "pass": bool(out.sum() == 0),
            "violation_seconds": round(float(out.sum()) / fps, 2),
            "max_pairs": round(float(max((s["pairs"] for s in series), default=0)), 2),
            "max_area_pct": round(float(max((s["area"] for s in series), default=0)) * 100, 1),
            "segments": segs, "_series": series}


def brief(r):
    return (f"  PATTERN {'PASS' if r['pass'] else 'FAIL'}  "
            f"위반 {r['violation_seconds']:.2f}s  최대 {r['max_pairs']:.1f}쌍  "
            f"최대면적 {r['max_area_pct']:.0f}%")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("srcs", nargs="+")
    a = ap.parse_args()
    for p in a.srcs:
        r = analyze(p, verbose=False)
        print(f"{p}\n{brief(r)}")
