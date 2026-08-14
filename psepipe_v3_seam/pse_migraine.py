# -*- coding: utf-8 -*-
"""
pse_migraine.py — 편두통 고유 축 M1(정적 패턴)·M2(색상)   [WARN 전용]
========================================================================
왜 별도 모듈인가
  PSE 규격 축(플래시·적색·패턴·화면전환)은 발작 방지 목적의 국제 표준이고,
  편두통 축은 표준이 없다(ACM TACCESS 2024 갭 분석). 그래서 red_mode 와 같은
  원칙을 따른다 — **판정(FAIL)에 섞지 않고 WARN/점수로만 보고**하며, 환자
  설문으로 임계가 검증되면 그때 FAIL 로 승격한다.

근거 기준 (축별 신뢰 등급)
  M1 정적 패턴 [문헌]
    · Wilkins et al. 1984 (Brain): 유발 공간주파수 1–4 cpd(중심 3 cpd),
      Michelson 대비 10% 이상부터 이상반응. duty ~50% 에서 최대.
    · Evans & Stevenson 2008 (OPO): Pattern Glare Test 규준 — 3 cpd 판이
      편두통/시각스트레스 선별 축. 12 cpd 는 대조 자극(반응 적음).
    · PSE 패턴 규칙(pse_pattern.py)과의 차이: 저대비(10%)·정지 패턴도 잡고,
      줄 쌍 수 대신 **시야각 기준 공간주파수(cpd)** 로 판정한다.
  M2 색상 [문헌→가설]
    · Noseda/Burstein (Brain 2016): 협대역 광자극에서 청색(450–480nm)이
      광공포 통증 최대, 녹색(520–530nm)만 저강도에서 통증 감소.
      → 단색광 실험을 영상 RGB 성분으로 번역한 것은 우리의 외삽 [가설].
    · Haigh et al. 2019 (Headache): CIE 1976 UCS 색도분리가 클수록 불쾌감
      단조 증가, 편두통군에서 증폭. 구체 임계는 논문에 없음 → CHROMA_STEP
      은 적색 플래시 규격(Δu'v' ≥ 0.20, ISO 9241-391)의 절반 이하로 잡은
      안전측 추정 [가설].

티어 파라미터 (기획서 통합 티어 표 v2 와 동일)
  t4 = 편두통 기본:  패턴 1–8 cpd·대비≥30% / 색도분리 감점
  t5 = 편두통 보수:  패턴 1–4 cpd·대비≥10% / + 청색 가중·녹색 완화

시야각 가정 [미규정]
  cpd 는 시청 거리에 의존한다. 기준 시청 조건을 "세로 쇼츠를 30cm 거리
  스마트폰으로 시청, 화면 세로 = 시야각 25°" 로 두고 파라미터로 노출한다
  (--view-deg). 분석 폭 W px 에서 검출 가능한 상한은 나이퀴스트 여유를 두어
  짧은변/3 cycles ≈ (W/3)/VIEW_DEG cpd — 기본 320px·25° 면 약 4.3 cpd 까지.
  t4 의 8 cpd 상한까지 보려면 --width 640 이상을 쓸 것.
"""
from __future__ import annotations
import argparse
import numpy as np
import cv2

import pse_pattern                      # _dominant_freq (FFT 지배 주파수·방향 선택도)
from pse_bt1702 import (decode_linear, luminance_cd, uv_prime,
                        UV_RED, UV_BLUE, RB_NEAR, RB_MIN_V)

# ── 공통 상수 ──────────────────────────────────────────────────────────
VIEW_DEG = 25.0           # [미규정] 기준 시야각: 화면 세로 높이(도). 위 주석 참조
CONC_MIN = pse_pattern.CONCENTRATION_MIN   # 방향 선택도 — 텍스처 오탐 방지, 재보정값 공유
MIN_DURATION_S = 0.5      # 패턴 지속 하한 (pse_pattern 과 동일 근거)
BLUE_SUSTAIN_S = 1.0      # [가설] 청색 노출은 순간이 아니라 지속이 문제 (광공포 기전)
AREA_MIN = 0.25           # [가설] 화면 25% — PSE 면적 기준을 차용 (편두통 실측치 없음)
LUM_LIT_CD = 10.0         # cd/m², 이보다 어두운 화소는 색·패턴 자극으로 안 봄

# sRGB 원색 green 의 CIE 1976 UCS 좌표 (UV_RED/UV_BLUE 와 같은 방식으로 산출)
UV_GREEN = np.array([0.1250, 0.5625], np.float32)

# 색도분리 플리커: 1초 창에서 프레임간 Δu'v' ≥ CHROMA_STEP 인 전환이
# CHROMA_PER_SEC 회를 넘으면 색 플리커로 본다. 휘도 플래시 계수 규칙(3회/s)의
# 구조를 차용했고 임계만 편두통 안전측 [가설].
CHROMA_STEP = 0.06        # [가설] 적색 규격 Δu'v'≥0.20 의 30% — Haigh 2019 단조증가 근거
CHROMA_PER_SEC = 3
GREEN_RELIEF = 0.5        # [가설] 녹색 우세 프레임의 색 점수 감면율 (Noseda 방향만 차용)

TIERS = {
    # cpd_lo/hi: 검출 대역, mich_min: Michelson 대비 하한
    "t4": {"cpd_lo": 1.0, "cpd_hi": 8.0, "mich_min": 0.30, "blue_weight": 0.0},
    "t5": {"cpd_lo": 1.0, "cpd_hi": 4.0, "mich_min": 0.10, "blue_weight": 1.0},
}


class Stream:
    """프레임을 한 장씩 받아 편두통 축을 누적한다 (pse_pattern.Stream 과 동일 계약).

    push() 에 주는 프레임은 **이미 분석 폭으로 축소된 BGR uint8**. pse_bt1702
    메인 루프에 pat_stream 과 나란히 끼워 넣을 수 있도록 같은 구조로 만들었다
    — 지금은 tier.py 가 별도 디코드로 부르지만(2회 디코드), 통합 시 이 클래스를
    analyze 루프에 push 하면 추가 디코드가 사라진다.
    """

    def __init__(self, tier: str = "t5", view_deg: float = VIEW_DEG):
        if tier not in TIERS:
            raise ValueError(f"tier 는 {list(TIERS)} 중 하나여야 합니다: {tier}")
        self.tier = tier
        self.p = TIERS[tier]
        self.view_deg = float(view_deg)
        self.series: list[dict] = []
        self._prev_uv_mean = None

    def push(self, small_bgr: np.ndarray) -> None:
        lum = luminance_cd(small_bgr, coherent=False)      # cd/m² (화소별)
        lit = lum >= LUM_LIT_CD

        # ── M1 정적 패턴 ────────────────────────────────────────────
        # 지배 주파수 탐색 대역을 cpd → cycles/screen 으로 환산해서 넘긴다.
        # (pse_pattern 기본 대역 2–60 은 줄 '쌍 수' 도메인이라 3 cpd(=75쌍/25°)
        #  같은 가는 줄무늬가 대역 밖으로 떨어진다.)
        h, w = lum.shape
        f_lo = self.p["cpd_lo"] * self.view_deg
        f_hi = min(self.p["cpd_hi"] * self.view_deg, min(h, w) / 3.0)
        pairs, period_px, theta, conc = pse_pattern._dominant_freq(
            lum, fmin=f_lo, fmax=max(f_lo + 1.0, f_hi))
        cpd = pairs / self.view_deg
        # Michelson 대비 = (밝은 바 − 어두운 바)/(밝은 바 + 어두운 바).
        # 바 휘도는 pse_pattern 과 같은 dilate/erode 국소 극값으로 잰다 —
        # Gabor 진폭은 사각파에서 4/pi 배 부풀어 저대비 판정에 부적합(실측).
        if period_px > 1.5:
            ksz = int(max(3, min(31, round(period_px) | 1)))
            ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksz, ksz))
            hi_bar = cv2.dilate(lum, ker)
            lo_bar = cv2.erode(lum, ker)
            mich = (hi_bar - lo_bar) / (hi_bar + lo_bar + 1e-6)
            pat_area = float(((mich >= self.p["mich_min"]) & lit).mean())
        else:
            pat_area = 0.0
        pat_hit = (self.p["cpd_lo"] <= cpd <= self.p["cpd_hi"]) and \
                  (conc >= CONC_MIN) and (pat_area >= AREA_MIN)

        # ── M2 색상 ────────────────────────────────────────────────
        uv = uv_prime(small_bgr)
        near_blue = (np.linalg.norm(uv - UV_BLUE, axis=-1) < RB_NEAR) & lit \
                    & (small_bgr.max(axis=2) >= RB_MIN_V)
        near_green = (np.linalg.norm(uv - UV_GREEN, axis=-1) < RB_NEAR) & lit \
                     & (small_bgr.max(axis=2) >= RB_MIN_V)
        blue_area = float(near_blue.mean())
        green_area = float(near_green.mean())
        # 프레임 대표 색도는 휘도 가중 평균 — 어두운 배경이 평균을 끌어내리는
        # 것을 막는다 (색도는 밝은 화소가 지각을 지배).
        wsum = float(lum.sum()) + 1e-6
        uv_mean = (uv * lum[..., None]).reshape(-1, 2).sum(axis=0) / wsum
        duv = 0.0
        if self._prev_uv_mean is not None:
            duv = float(np.linalg.norm(uv_mean - self._prev_uv_mean))
        self._prev_uv_mean = uv_mean

        self.series.append({
            "i": len(self.series),
            "cpd": round(float(cpd), 2), "conc": round(float(conc), 3),
            "mich_area": round(pat_area, 4), "pat_hit": bool(pat_hit),
            "blue_area": round(blue_area, 4), "green_area": round(green_area, 4),
            "duv": round(duv, 4),
        })

    # ── 집계 ───────────────────────────────────────────────────────
    def finish(self, fps: float, video: str = "<frames>") -> dict:
        s = self.series
        n = len(s)
        if n == 0 or fps <= 0:
            raise ValueError("빈 스트림이거나 fps 가 없습니다")

        def runs(flags: np.ndarray, min_run: int):
            """min_run 이상 지속된 True 구간만 남긴다 + (시작,끝) 초 목록."""
            out = np.zeros(n, bool)
            segs, st = [], None
            for i in range(n + 1):
                v = bool(flags[i]) if i < n else False
                if v and st is None:
                    st = i
                elif not v and st is not None:
                    if i - st >= min_run:
                        out[st:i] = True
                        segs.append((round(st / fps, 2), round(i / fps, 2)))
                    st = None
            return out, segs

        # M1: 지속 0.5초 이상만 인정 (일시적 텍스처 오탐 배제)
        pat_flags = np.array([x["pat_hit"] for x in s])
        pat_out, pat_segs = runs(pat_flags, max(1, int(round(MIN_DURATION_S * fps))))

        # M2a: 청색 지속 노출 (t5 만 가중 — t4 는 blue_weight 0)
        blue_flags = np.array([x["blue_area"] >= AREA_MIN for x in s])
        blue_out, blue_segs = runs(blue_flags, max(1, int(round(BLUE_SUSTAIN_S * fps))))
        if self.p["blue_weight"] <= 0.0:
            blue_out[:] = False
            blue_segs = []

        # M2b: 색도분리 플리커 — 1초 슬라이딩 창의 Δu'v' 전환 계수
        duv_step = np.array([x["duv"] >= CHROMA_STEP for x in s])
        win = max(1, int(round(fps)))
        kern = np.ones(win)
        cnt = np.convolve(duv_step.astype(np.float32), kern, mode="same")
        chroma_out, chroma_segs = runs(cnt > CHROMA_PER_SEC, 1)

        # 녹색 감면 [가설]: 색 경고 프레임에서 녹색 면적이 클수록 점수를 깎는다.
        # 경고 판정 자체는 유지 — 감면은 점수(우선순위)에만 작용한다.
        color_out = blue_out | chroma_out
        if color_out.any():
            g = float(np.mean([s[i]["green_area"] for i in np.where(color_out)[0]]))
            relief = 1.0 - GREEN_RELIEF * min(1.0, g / max(AREA_MIN, 1e-6))
        else:
            relief = 1.0

        pat_sec = round(float(pat_out.sum()) / fps, 2)
        color_sec = round(float(color_out.sum()) / fps * relief, 2)
        return {
            "video": video, "tier": self.tier, "fps": round(fps, 3), "frames": n,
            "view_deg": self.view_deg,
            # WARN 전용 축 — 규격 판정이 아니므로 pass 는 항상 True.
            "pass": True,
            "warn": bool(pat_out.any() or color_out.any()),
            "pattern": {
                "warn_seconds": pat_sec, "segments": pat_segs,
                "max_cpd": round(float(max((x["cpd"] for x in s), default=0)), 2),
                "max_mich_area_pct": round(float(max((x["mich_area"] for x in s),
                                                     default=0)) * 100, 1),
            },
            "color": {
                "warn_seconds": color_sec,
                "blue_segments": blue_segs, "chroma_segments": chroma_segs,
                "max_blue_area_pct": round(float(max((x["blue_area"] for x in s),
                                                     default=0)) * 100, 1),
                "max_duv": round(float(max((x["duv"] for x in s), default=0)), 3),
                "green_relief": round(relief, 3),
            },
            # 단일 점수 [가설]: 경고 초의 합. 설문 검증 전까지 정렬용으로만 쓸 것.
            "score": round(pat_sec + color_sec, 2),
            "_series": s,
        }


def analyze(path, tier: str = "t5", width: int = 320, view_deg: float = VIEW_DEG,
            verbose: bool = False, fps: float = None) -> dict:
    """path 대신 프레임 이터러블(BGR uint8)도 받는다. 그 경우 fps 필수."""
    import os as _os
    if isinstance(path, (str, _os.PathLike)):
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            raise IOError(path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frames_in = None
    else:
        if fps is None:
            raise ValueError("프레임을 직접 넘길 때는 fps 가 필요합니다")
        cap, frames_in = None, iter(path)
    st = Stream(tier=tier, view_deg=view_deg)
    idx = 0
    while True:
        if cap is not None:
            ok, frame = cap.read()
            if not ok:
                break
        else:
            frame = next(frames_in, None)
            if frame is None:
                break
        h0, w0 = frame.shape[:2]
        small = (cv2.resize(frame, (width, max(2, int(h0 * width / w0))),
                            interpolation=cv2.INTER_AREA) if w0 != width else frame)
        st.push(small)
        idx += 1
        if verbose and idx % 300 == 0:
            print(f"    ... {idx} frames", flush=True)
    if cap is not None:
        cap.release()
    return st.finish(fps, video=str(path) if cap is not None else "<frames>")


def brief(r: dict) -> str:
    tag = "WARN" if r["warn"] else "ok"
    return (f"  MIGRAINE[{r['tier']}] {tag:<4} 점수 {r['score']:.2f}"
            f"  패턴 {r['pattern']['warn_seconds']:.2f}s"
            f" (최대 {r['pattern']['max_cpd']:.1f}cpd,"
            f" 면적 {r['pattern']['max_mich_area_pct']:.0f}%)"
            f"  색상 {r['color']['warn_seconds']:.2f}s"
            f" (청 {r['color']['max_blue_area_pct']:.0f}%,"
            f" Δu'v' {r['color']['max_duv']:.2f})")


# ══════════════════════════════════════════════ 합성 자극 셀프테스트
def _selftest() -> int:
    """영상 파일 없이 축이 옳게 동작하는지 확인한다. 실패 축 수를 반환."""
    fps, n, w, h = 30.0, 45, 320, 568          # 세로 쇼츠 비율 1.5초

    def grating(cpd, contrast, deg=VIEW_DEG):
        # 세로 줄무늬: cpd × 시야각 = 화면을 가로지르는 주기 수
        cycles = cpd * deg
        x = np.arange(w, dtype=np.float32)
        wave = 0.5 + 0.5 * contrast * np.sign(np.sin(2 * np.pi * cycles * x / w))
        g = np.tile((np.power(wave, 1 / 2.4) * 255).astype(np.uint8), (h, 1))
        return cv2.merge([g, g, g])

    fails = 0

    def check(name, cond):
        nonlocal fails
        print(f"  {'PASS' if cond else 'FAIL'}  {name}")
        fails += (not cond)

    # 1) 3 cpd 고대비 정지 줄무늬 → t5·t4 모두 패턴 WARN
    frames = [grating(3.0, 0.9)] * n
    r5 = analyze(frames, tier="t5", fps=fps)
    r4 = analyze(iter([grating(3.0, 0.9)] * n), tier="t4", fps=fps)
    check("3cpd·대비90% → t5 패턴 WARN", r5["warn"] and r5["pattern"]["warn_seconds"] > 0)
    check("3cpd·대비90% → t4 패턴 WARN", r4["warn"] and r4["pattern"]["warn_seconds"] > 0)

    # 2) 3 cpd 저대비(15%) → t5 만 WARN (t4 하한 30% 미달)
    r5 = analyze([grating(3.0, 0.15)] * n, tier="t5", fps=fps)
    r4 = analyze([grating(3.0, 0.15)] * n, tier="t4", fps=fps)
    check("3cpd·대비15% → t5 WARN", r5["warn"])
    check("3cpd·대비15% → t4 통과", not r4["warn"])

    # 3) 무지 회색 → 경고 없음
    gray = np.full((h, w, 3), 128, np.uint8)
    r = analyze([gray] * n, tier="t5", fps=fps)
    check("무지 회색 → 통과", not r["warn"])

    # 4) 청색 화면 지속 → t5 색상 WARN, t4 는 청색 축 꺼짐
    blue = np.zeros((h, w, 3), np.uint8); blue[..., 0] = 255
    r5 = analyze([blue] * n, tier="t5", fps=fps)
    r4 = analyze([blue] * n, tier="t4", fps=fps)
    check("청색 지속 → t5 색상 WARN", r5["warn"] and r5["color"]["warn_seconds"] > 0)
    check("청색 지속 → t4 통과(청색 축 미가중)", not r4["warn"])

    # 5) 적↔청 6.7Hz 교대 → 색도분리 플리커 WARN (양 티어)
    red = np.zeros((h, w, 3), np.uint8); red[..., 2] = 255
    alt = [red if (i // 2) % 2 == 0 else blue for i in range(n)]
    r4 = analyze(alt, tier="t4", fps=fps)
    check("적↔청 교대 → t4 색도분리 WARN", r4["warn"] and len(r4["color"]["chroma_segments"]) > 0)

    # 6) 녹색 감면: 녹↔회 교대는 duv 가 작아 경고로 이어지지 않아야 함
    green = np.zeros((h, w, 3), np.uint8); green[..., 1] = 255
    r = analyze([green] * n, tier="t5", fps=fps)
    check("녹색 지속 → 통과", not r["warn"])

    print(f"\n  {'모두 통과' if fails == 0 else f'{fails}개 실패'}")
    return fails


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="편두통 고유 축 M1(정적 패턴)·M2(색상) — WARN 전용, 규격 판정과 분리")
    ap.add_argument("srcs", nargs="*", help="영상 파일 (여러 개 가능)")
    ap.add_argument("--tier", choices=list(TIERS), default="t5")
    ap.add_argument("--width", type=int, default=320,
                    help="분석 폭 px (t4 의 8cpd 상한까지 보려면 640 이상)")
    ap.add_argument("--view-deg", type=float, default=VIEW_DEG,
                    help="기준 시야각(화면 세로, 도). 기본 25 = 스마트폰 30cm")
    ap.add_argument("--selftest", action="store_true", help="합성 자극 셀프테스트")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(_selftest())
    if not a.srcs:
        ap.error("영상 파일을 주거나 --selftest 를 쓰세요")
    for p in a.srcs:
        r = analyze(p, tier=a.tier, width=a.width, view_deg=a.view_deg)
        print(f"{p}\n{brief(r)}")
