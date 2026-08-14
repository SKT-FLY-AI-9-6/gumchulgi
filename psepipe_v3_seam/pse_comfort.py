# -*- coding: utf-8 -*-
"""pse_comfort.py — 편두통 컴포트 점수 v0.2  [판정 아님 — 점수 전용]

v0.2 (2026-08-14): pse_migraine 병합 — 합성 자극 대조 실측
(validation/compare_migraine_comfort.py)에서 서로의 사각지대가 확인돼 합쳤다.
  + pattern 에 Wilkins 대역 Michelson 신호 (저대비 3cpd 를 1/f 이탈이 못 갈랐다)
  + chroma 성분 (색도분리 '교대' — color 의 머무름과 별개 축, Haigh 2019)
  + PRESETS t4/t5 — 통합 티어 표의 편두통 티어를 슬라이더 기본값으로 번역
  pse_migraine.py 는 티어형 WARN 참조 구현으로 유지 (tier.py --migraine).

================================================================================
** 규격 판정 정본은 pse_bt1702.py 다. 이 모듈은 판정을 내지 않는다. **
================================================================================

무엇을 하는가
-------------
편두통에는 PSE 규격 같은 "이 선 아래면 안전"이 존재하지 않는다 (유발이
지연·용량·상태 의존이라 임계 실험 자체가 성립하지 않음 — Hougaard 2013 유발
실험 실패, Sebastianelli 2024 역치 가설). 그래서 이 모듈은 선을 긋지 않고,
문헌에서 확인된 유발 요인 4개를 **연속 점수(0~100)와 초 단위 시계열**로 잰다.
어디서 자를지(발동점)는 사용자 슬라이더가 정한다.

성분과 근거 (각 성분 = 근거표의 행 하나)
----------------------------------------
  flash    관문 미달 플리커 — PSE 관문(ΔY 20cd/m²·Michelson 1/17·면적 25%)에
           못 미쳐 판정에서 버려지는 얕은 휘도 변조를 깊이×면적으로 연속 누적.
           주파수 가중은 15 Hz 피크 로그가우시안 (Kowacs 2004/2005 불쾌 피크;
           Wilkins 1989 — 지각 못 하는 변조도 두통 유발, 이중맹검).
  color    청·적 고채도 지속 — 전환(이벤트)이 아니라 **머무는 시간**을 잰다.
           청 450~480nm 통증 최대, 적 다음, 녹은 제외 (Noseda 2016 Brain).
           청색은 휘도 기여가 0.0722 라 휘도 축이 원리적으로 못 보는 구멍
           (psecore §0 실측: 콘서트 최대 60.7% 화소)을 여기서 메운다.
  glare    암순응 맥락 속 고휘도 — 편두통군은 간기에도 불쾌 임계가 낮고
           (Vanagaite 1997 ~630lx), 어두운 맥락일수록 유효 자극이 커진다.
           5초 EMA 를 순응 수준으로 삼아 그 대비 밝은 면적을 잰다.
  pattern  1/f 스펙트럼 이탈 — pse_discomfort (Penacchio & Wilkins 2015 계열,
           3 cpd 위험 대역 가중). 판정용 패턴축(pse_pattern)이 자막 오탐으로
           빠진 자리를 점수로 대신 맡는다.

가중과 눈금
-----------
성분 결합 가중(flash .35 / pattern .25 / color .25 / glare .15)은 근거의 강도
순서(플리커·패턴: 이중맹검+대조군 / 색: 기전+서열 / 휘도: 임계 실측)를 반영한
**서열**이고, 정규화 눈금(*_SCALE)은 합성 클립으로 맞춘 v0.1 잠정값이다.
절대값이 아니라 영상 간·구간 간 상대 비교용. 실영상 스윕으로 재보정할 것.

출력이 초 단위 시계열인 이유
----------------------------
편두통 유발은 순간 반응이 아니라 세션 누적 용량의 문제다 (유발 실험 실패·
지연 발현). 시계열이 있어야 (a) psepipe 가 발동점 초과 구간에만 마스크를 걸고
(b) 워처가 "이번 세션 노출 용량"을 적분할 수 있다.

사용
----
    import pse_comfort
    cs = pse_comfort.Stream(fps)
    ... 메인 루프에서 cs.push(small_bgr, lum=lum) ...
    out = cs.summary()
    # {"score": 0~100(p90), "mean": .., "dose_per_min": ..,
    #  "components": {"flash": .., "color": .., "glare": .., "pattern": ..},
    #  "per_sec": [초별 점수], "per_sec_components": {...}}

pse_bt1702.analyze(..., with_comfort=True) 로도 같은 결과가 "comfort" 키에 붙는다.
규격 판정(compliant/failed_rules)에는 어떤 경로로도 들어가지 않는다.
"""

from __future__ import annotations

import numpy as np

try:                                    # 정본과 같은 변환을 쓴다 (일관성)
    import pse_bt1702 as _BT
except Exception:                       # 단독 사용 폴백
    _BT = None

try:
    import pse_discomfort as _PD
except Exception:
    _PD = None

try:                                    # v0.2 패턴 Michelson 게이트용 (선택)
    import cv2 as _CV2
    import pse_pattern as _PP
except Exception:
    _CV2 = _PP = None

_EPS = 1e-6

# ── 눈금 (v0.1 잠정 — 합성 클립 기준. 실영상 스윕으로 재보정할 것)
FLASH_SCALE = 0.05        # 15Hz 가중 Michelson 깊이×면적의 초 평균
COLOR_SCALE = 0.40        # 청(1.0)+적(0.7) 가중 화소 비율의 초 평균
GLARE_SCALE = 0.20        # 암순응 맥락 대비 고휘도 면적의 초 평균
PATTERN_SCALE = 0.90      # pse_discomfort frame_score (3cpd 정현파 ≈ 0.98)

# ── v0.2 병합 성분 (pse_migraine 에서 이식 — validation/compare_migraine_comfort.py
#    실측이 계기: 저대비 3cpd 줄무늬가 1/f 이탈 점수로는 회색과 2~3점 차라
#    슬라이더 어디에 놔도 안 갈렸고, 관문미달 플리커는 반대로 comfort 만 잡았다.
#    → 두 모듈의 강점을 한 엔진으로 합친다.)
MICH_SCALE = 0.30         # Wilkins 대역 Michelson 깊이×면적. 0.30 = 대비 30%
                          # 전면 줄무늬에서 포화 (Wilkins 1984: 10% 부터 이상반응,
                          # 고대비일수록 강함 — 깊이 연속 누적으로 그 사이를 그린다)
MICH_FLOOR = 0.05         # 이 깊이 미만 화소는 계수 제외 (코덱 잡음 하한)
CHROMA_SCALE = 0.10       # Δu'v' 프레임 스텝의 초 평균 (주파수 가중 후).
                          # 적↔청(Δu'v' 0.457) 7.5Hz 교대 ≈ 0.18 에서 포화 근처.
CHROMA_STEP = 0.06        # 교대 '이벤트'로 세는 스텝 하한 — 적색 플래시 규격
                          # (Δu'v'≥0.20, ISO 9241-391)의 30%. Haigh 2019 는
                          # 색도분리와 불쾌감의 단조 증가만 제시 [가설 임계]

# v0.2 가중 — 근거 강도 서열 유지: 플리커·패턴(이중맹검+대조군) > 색 기전(Noseda)
# > 색도분리(단조 증가 문헌, 임계는 가설) > 휘도(임계 실측뿐)
W_FLASH, W_PATTERN, W_COLOR, W_CHROMA, W_GLARE = 0.30, 0.25, 0.20, 0.15, 0.10

# ── 발동점 프리셋 [가설 — 환자 설문 검증 대상]
# 기획서 통합 티어 표 v2 의 t4/t5 를 "선"이 아니라 슬라이더 기본값으로 번역한 것.
# 합성 자극 실측(자가 검증 7클립) 기준 눈금:
#   회색 0 · 자연풍 1.5 | 저대비 3cpd 12.5 | 고대비 3cpd 25 · 관문미달 플리커 30
#   | 청색 스트로브 52 · 적↔청 교대 65
# t4(기본)=20: 고대비 패턴·플리커·색 급부터 발동 (티어 표 t4: 대비>30%)
# t5(보수)=12: 저대비 패턴(Wilkins 10%)까지 발동, 자연풍(1.5)과 8배 마진
# 설문에서 불쾌 평정과 점수의 교차점이 나오면 이 값을 교체할 것.
PRESETS = {"t4": 20.0, "t5": 12.0}


def preset_warn(summary: dict, preset: str = "t5") -> dict:
    """프리셋 발동점으로 요약을 이진 경고로 번역한다 (서비스 UI 용)."""
    trig = PRESETS[preset]
    secs = [i for i, s in enumerate(summary.get("per_sec", [])) if s >= trig]
    return {"preset": preset, "trigger": trig, "warn": bool(secs),
            "warn_seconds": len(secs), "warn_at": secs}

FREQ_PEAK_HZ = 15.0       # 플리커 불쾌 피크 (Kowacs)
FREQ_SIGMA_OCT = 1.5      # 로그가우시안 폭 — 3Hz 도 0.3 배로는 남긴다
COLOR_W = 96              # 색 계산 폭 (pse_bt1702.COLOR_W 와 동일 근거)
GLARE_TAU_S = 5.0         # 순응(EMA) 시정수
PATTERN_FPS = 3.0         # 1/f 표본율 — 공간 통계는 천천히 변한다


def _freq_weight(f_hz: float) -> float:
    if f_hz <= 0.25:
        return 0.0
    return float(np.exp(-np.log2(f_hz / FREQ_PEAK_HZ) ** 2
                        / (2.0 * FREQ_SIGMA_OCT ** 2)))


def _decode_linear(bgr):
    if _BT is not None:
        return _BT.decode_linear(bgr)            # RGB 순서로 반환
    rgb = bgr[..., ::-1].astype(np.float32) / 255.0
    return np.power(rgb, 2.2, dtype=np.float32)


class Stream:
    """프레임(분석 폭으로 축소된 BGR uint8)을 한 장씩 받아 컴포트 성분을 누적한다.

    pse_pattern.Stream / pse_cut.Stream 과 같은 편입 관례 — pse_bt1702 의
    메인 루프가 자기 축소 프레임을 그대로 먹인다. 별도 디코드 없음.
    """

    def __init__(self, fps: float, px_per_deg: float = 32.0):
        self.fps = float(fps) if fps and fps > 0 else 30.0
        self.px_per_deg = px_per_deg
        self.idx = 0
        self._prev_y = None               # 표시 선형 휘도 (0~1)
        self._ema = None                  # 순응 맥락 (EMA of mean y)
        self._ema_a = 1.0 - np.exp(-1.0 / (GLARE_TAU_S * self.fps))
        self._sign_prev = 0
        self._flips = []                  # 초 내 부호 반전 수 집계용
        self._pat_hop = max(1, int(round(self.fps / PATTERN_FPS)))
        self._pat_last = 0.0
        self._mich_last = 0.0             # 패턴 Michelson (같은 표본율)
        self._prev_uv = None              # 색도 교대 추적 (COLOR_W 해상도)
        # 초별 누적 [ [flash..], [color..], [glare..], [pattern..] ]
        self._sec = []
        self._cur = None
        self._cur_sec = -1

    # ── 내부: 초 경계 관리
    def _bucket(self):
        s = int(self.idx / self.fps)
        if s != self._cur_sec:
            if self._cur is not None:
                self._close_sec()
            self._cur = {"flash": [], "color": [], "glare": [], "pattern": [],
                         "mich": [], "chroma": [], "chroma_ev": 0, "flips": 0}
            self._cur_sec = s
        return self._cur

    def _close_sec(self):
        c = self._cur
        f_hz = c["flips"] / 2.0                       # 반전 2회 = 1주기
        w = _freq_weight(f_hz)
        # 색도 교대도 같은 논리 — 이벤트 2회 = 1주기, 15Hz 피크 가중
        wc = _freq_weight(c["chroma_ev"] / 2.0)
        self._sec.append({
            "flash": float(np.mean(c["flash"]) * w) if c["flash"] else 0.0,
            "color": float(np.mean(c["color"])) if c["color"] else 0.0,
            "glare": float(np.mean(c["glare"])) if c["glare"] else 0.0,
            "pattern": float(np.mean(c["pattern"])) if c["pattern"]
                       else self._pat_last,
            "mich": float(np.mean(c["mich"])) if c["mich"] else self._mich_last,
            "chroma": float(np.mean(c["chroma"]) * wc) if c["chroma"] else 0.0,
            "freq_hz": f_hz,
        })

    # ── 프레임 하나
    def push(self, small_bgr: np.ndarray, lum: np.ndarray = None) -> None:
        c = self._bucket()

        # 휘도 (표시 선형 0~1). bt1702 가 계산한 cd/m² 필드를 재사용한다.
        if lum is not None:
            y = np.asarray(lum, np.float32) / float(getattr(_BT, "SDR_PEAK", 200.0))
        else:
            lin = _decode_linear(small_bgr)
            y = (0.2126 * lin[..., 0] + 0.7152 * lin[..., 1]
                 + 0.0722 * lin[..., 2])

        m = float(y.mean())

        # ① flash — 관문 없는 Michelson 깊이×면적
        if self._prev_y is not None:
            mich = np.abs(y - self._prev_y) / (y + self._prev_y + _EPS)
            c["flash"].append(float(np.where(mich > 0.02, mich, 0.0).mean()))
            dm = m - self._m_prev
            sg = 1 if dm > 1e-4 else (-1 if dm < -1e-4 else 0)
            if sg and self._sign_prev and sg != self._sign_prev:
                c["flips"] += 1
            if sg:
                self._sign_prev = sg
        self._prev_y, self._m_prev = y, m

        # ② color — 청·적 고채도 지속 (COLOR_W 축소, 선형광)
        w = small_bgr.shape[1]
        if w > COLOR_W:
            try:
                import cv2
                hh = max(2, int(round(small_bgr.shape[0] * COLOR_W / w)))
                sc = cv2.resize(small_bgr, (COLOR_W, hh),
                                interpolation=cv2.INTER_AREA)
            except Exception:
                sc = small_bgr[:, ::max(1, w // COLOR_W)]
        else:
            sc = small_bgr
        lin = _decode_linear(sc)
        r, g, b = lin[..., 0], lin[..., 1], lin[..., 2]
        tot = r + g + b + _EPS
        frac_b = float(((b / tot >= 0.45) & (b >= 0.05)).mean())
        frac_r = float(((r / tot >= 0.60) & (r >= 0.05)).mean())
        c["color"].append(1.0 * frac_b + 0.7 * frac_r)

        # ②b chroma — 색도분리 '교대' (v0.2, pse_migraine 이식).
        # color 성분은 머무는 시간이라 청색 지속과 적↔청 교대를 구분 못 한다.
        # 프레임 대표 색도(휘도 가중 u'v')의 스텝을 따로 잰다 — Haigh 2019 의
        # "색도분리가 클수록 불쾌, 편두통군 증폭" 축. 색 계산용 lin 을 재사용.
        X = 0.4124 * r + 0.3576 * g + 0.1805 * b
        Yc = 0.2126 * r + 0.7152 * g + 0.0722 * b
        Z = 0.0193 * r + 0.1192 * g + 0.9505 * b
        d4 = X + 15.0 * Yc + 3.0 * Z + _EPS
        wY = float(Yc.sum()) + _EPS
        uv = (float((4.0 * X / d4 * Yc).sum()) / wY,
              float((9.0 * Yc / d4 * Yc).sum()) / wY)
        if self._prev_uv is not None:
            duv = float(np.hypot(uv[0] - self._prev_uv[0],
                                 uv[1] - self._prev_uv[1]))
            c["chroma"].append(duv)
            if duv >= CHROMA_STEP:
                c["chroma_ev"] += 1
        self._prev_uv = uv

        # ③ glare — 순응 맥락(EMA) 대비 고휘도 면적
        ctx = self._ema if self._ema is not None else m
        dark_ctx = max(0.0, 0.30 - ctx) / 0.30
        c["glare"].append(float((y > 0.75).mean()) * dark_ctx)
        self._ema = ctx + self._ema_a * (m - ctx)

        # ④ pattern — 1/f 이탈 (표본)
        if _PD is not None and self.idx % self._pat_hop == 0:
            try:
                self._pat_last = float(_PD.frame_score(small_bgr,
                                                       self.px_per_deg))
            except Exception:
                pass
            c["pattern"].append(self._pat_last)

        # ④b pattern — Wilkins 대역 Michelson 깊이×면적 (v0.2, pse_migraine 이식).
        # 실측(compare_migraine_comfort.py): 1/f 이탈은 저대비 3cpd 를 회색과
        # 2~3점 차로만 갈랐다. Wilkins 1984 는 대비 10% 부터 이상반응을 보고하니
        # 대역(1~8cpd)·방향선택도 게이트 안에서 Michelson 깊이를 직접 누적한다.
        if _CV2 is not None and _PP is not None and self.idx % self._pat_hop == 0:
            try:
                hh, ww = y.shape
                deg_w = ww / max(self.px_per_deg, _EPS)      # 화면 폭의 시야각
                f_lo = 1.0 * deg_w
                f_hi = min(8.0 * deg_w, min(hh, ww) / 3.0)
                pairs, period_px, _th, conc = _PP._dominant_freq(
                    y, fmin=f_lo, fmax=max(f_lo + 1.0, f_hi))
                sig = 0.0
                if (period_px > 1.5 and conc >= _PP.CONCENTRATION_MIN
                        and f_lo <= pairs <= f_hi):
                    ksz = int(max(3, min(31, round(period_px) | 1)))
                    ker = _CV2.getStructuringElement(_CV2.MORPH_ELLIPSE,
                                                     (ksz, ksz))
                    hi_b = _CV2.dilate(y, ker)
                    lo_b = _CV2.erode(y, ker)
                    mich = (hi_b - lo_b) / (hi_b + lo_b + _EPS)
                    sig = float(np.where(mich >= MICH_FLOOR, mich, 0.0).mean())
                self._mich_last = sig
            except Exception:
                pass
            c["mich"].append(self._mich_last)

        self.idx += 1

    # ── 마감
    def summary(self) -> dict:
        if self._cur is not None and (self._cur["flash"] or self._cur["color"]):
            self._close_sec()
            self._cur = None
        if not self._sec:
            return {"score": 0.0, "mean": 0.0, "dose_per_min": 0.0,
                    "components": {}, "per_sec": [], "per_sec_components": {},
                    "note": "프레임 부족"}

        def _n(v, s):
            return min(1.0, v / s)

        scores, comp_series = [], {"flash": [], "color": [], "glare": [],
                                   "pattern": [], "chroma": []}
        for sec in self._sec:
            fn = _n(sec["flash"], FLASH_SCALE)
            cn = _n(sec["color"], COLOR_SCALE)
            gn = _n(sec["glare"], GLARE_SCALE)
            # 패턴 = 두 신호의 최댓값 — 1/f 이탈(구성 무관 일반 지표)과
            # Wilkins 대역 Michelson(저대비 줄무늬 특화) 중 강한 쪽.
            # 합산이 아니라 max 인 이유: 같은 자극을 두 번 세지 않기 위해.
            pn = max(_n(sec["pattern"], PATTERN_SCALE),
                     _n(sec.get("mich", 0.0), MICH_SCALE))
            hn = _n(sec.get("chroma", 0.0), CHROMA_SCALE)
            scores.append(100.0 * min(1.0, W_FLASH * fn + W_PATTERN * pn
                                      + W_COLOR * cn + W_CHROMA * hn
                                      + W_GLARE * gn))
            comp_series["flash"].append(round(fn, 4))
            comp_series["color"].append(round(cn, 4))
            comp_series["glare"].append(round(gn, 4))
            comp_series["pattern"].append(round(pn, 4))
            comp_series["chroma"].append(round(hn, 4))

        a = np.asarray(scores)
        comps = {k: round(float(np.mean(v)), 4) for k, v in comp_series.items()}
        return {
            # p90 — 쇼츠는 잠잠한 구간이 평균을 희석한다. "가장 자극적인 구간"이
            # 체감을 지배하므로 상위 눈금을 대표값으로 쓴다. mean 도 같이 낸다.
            "score": round(float(np.percentile(a, 90)), 1),
            "mean": round(float(a.mean()), 1),
            "dose_per_min": round(float(a.sum()) / max(len(a) / 60.0, _EPS)
                                  / 60.0, 1),   # 초당 점수 합의 분당 평균
            "components": comps,
            "per_sec": [round(float(x), 1) for x in scores],
            "per_sec_components": comp_series,
            "note": "점수는 상대 비교용 v0.2 — 규격 판정 아님. 눈금 재보정 필요.",
        }


# ══════════════════════════════════════════════ 자가 검증 (합성 5클립)
if __name__ == "__main__":
    import json

    FPS, SEC, W, H = 30.0, 5, 320, 240
    N = int(FPS * SEC)
    rng = np.random.default_rng(0)

    def run(frames):
        s = Stream(FPS)
        for f in frames:
            s.push(f)
        return s.summary()

    def solid(v):
        return [np.full((H, W, 3), v, np.uint8) for _ in range(N)]

    def shallow_flicker(hz=10, amp=6):
        """PSE 관문 미달 얕은 플리커 — 회색 128±amp (ΔY≈수 cd, Michelson≈0.04)"""
        out = []
        for i in range(N):
            ph = 1 if int(2 * hz * i / FPS) % 2 == 0 else -1
            out.append(np.full((H, W, 3), 128 + ph * amp, np.uint8))
        return out

    def blue_strobe(hz=3):
        """청↔흑 — 휘도 기여 0.072 라 휘도 축 관문 미달. 색 지속+플리커."""
        blue = np.zeros((H, W, 3), np.uint8); blue[..., 0] = 255
        blk = np.zeros((H, W, 3), np.uint8)
        return [blue if int(2 * hz * i / FPS) % 2 == 0 else blk
                for i in range(N)]

    def stripes3():
        x = np.arange(W) / 32.0
        row = (127.5 + 127.5 * np.sin(2 * np.pi * 3 * x)).astype(np.uint8)
        img = np.dstack([np.tile(row, (H, 1))] * 3)
        return [img] * N

    def natural():
        f = np.fft.fftfreq(256)
        fr = np.hypot(f[:, None], f[None, :]); fr[0, 0] = 1
        sp = (rng.standard_normal((256, 256))
              + 1j * rng.standard_normal((256, 256))) / fr
        img = np.fft.ifft2(sp).real
        img = ((img - img.min()) / (np.ptp(img) + 1e-9) * 255).astype(np.uint8)
        img = np.dstack([img[:H, :W]] * 3)
        return [img] * N

    def stripes3_low(contrast=0.15):
        """저대비 3cpd — v0.2 Michelson 신호 검증 (1/f 이탈만으로는 회색과
        2~3점 차였던 사각지대, compare_migraine_comfort.py 실측)."""
        x = np.arange(W) / 32.0
        wave = 0.5 * (1.0 + contrast * np.sign(np.sin(2 * np.pi * 3 * x)))
        row = (np.power(wave, 1 / 2.4) * 255).astype(np.uint8)
        img = np.dstack([np.tile(row, (H, 1))] * 3)
        return [img] * N

    def rb_alternate(hz=7.5):
        """적↔청 교대 — v0.2 chroma 성분 검증 (color 머무름과 구분되는 축)."""
        red = np.zeros((H, W, 3), np.uint8); red[..., 2] = 255
        blue = np.zeros((H, W, 3), np.uint8); blue[..., 0] = 255
        return [red if int(2 * hz * i / FPS) % 2 == 0 else blue
                for i in range(N)]

    tests = [("정지 회색", solid(128)),
             ("자연풍 정지", natural()),
             ("얕은 10Hz 플리커(관문미달)", shallow_flicker()),
             ("청색 3Hz 스트로브", blue_strobe()),
             ("정지 3cpd 줄무늬", stripes3()),
             ("저대비 3cpd 줄무늬(15%)", stripes3_low()),
             ("적↔청 7.5Hz 교대", rb_alternate())]

    print("── pse_comfort v0.2 자가 검증 ──")
    res = {}
    for name, frames in tests:
        r = run(frames)
        res[name] = r
        print(f"  {name:22s} score {r['score']:5.1f}  mean {r['mean']:5.1f}  "
              + " ".join(f"{k}:{v:.2f}" for k, v in r["components"].items()))

    base = res["정지 회색"]["score"]
    assert all(res[n]["score"] > base + 5 for n in
               ["얕은 10Hz 플리커(관문미달)", "청색 3Hz 스트로브", "정지 3cpd 줄무늬"]), \
        "자극 클립이 정지 회색보다 충분히 높아야 한다"
    assert res["청색 3Hz 스트로브"]["components"]["color"] == \
        max(r["components"].get("color", 0) for r in res.values()), "청색 클립의 color 최고"
    assert res["정지 3cpd 줄무늬"]["components"]["pattern"] == \
        max(r["components"].get("pattern", 0) for r in res.values()), "줄무늬의 pattern 최고"
    # ── v0.2 병합 검증
    assert res["저대비 3cpd 줄무늬(15%)"]["score"] > base + 5, \
        "저대비 줄무늬가 회색과 갈려야 한다 (Michelson 신호)"
    assert res["정지 3cpd 줄무늬"]["score"] > res["저대비 3cpd 줄무늬(15%)"]["score"], \
        "고대비 > 저대비 단조 유지"
    assert res["적↔청 7.5Hz 교대"]["components"]["chroma"] == \
        max(r["components"].get("chroma", 0) for r in res.values()), "교대 클립의 chroma 최고"
    assert res["청색 3Hz 스트로브"]["components"].get("chroma", 0) < \
        res["적↔청 7.5Hz 교대"]["components"]["chroma"], \
        "chroma 는 머무름(color)이 아니라 교대를 재야 한다"
    pw5 = preset_warn(res["저대비 3cpd 줄무늬(15%)"], "t5")
    pw4 = preset_warn(res["저대비 3cpd 줄무늬(15%)"], "t4")
    assert pw5["warn"] and not pw4["warn"], \
        "저대비 패턴: t5(보수) 발동·t4(기본) 미발동이 프리셋 의도"
    assert not preset_warn(res["정지 회색"], "t5")["warn"], "회색은 t5 에서도 무발동"
    print("순서 검증 통과 — 자극 ≫ 자연풍·정지, 성분 귀속·프리셋 정상 (v0.2)")

    # 판정 오염 없음: 얕은 플리커·청색 스트로브는 규격 '적합' 그대로여야 한다
    try:
        import pse_bt1702 as BT
        for name in ["얕은 10Hz 플리커(관문미달)", "청색 3Hz 스트로브"]:
            frames = dict(tests)[name]
            r = BT.analyze(iter(frames), fps=FPS, with_pattern=False,
                           with_cut=False, with_comfort=True)
            print(f"  통합: {name} → compliant={r['compliant']} "
                  f"comfort={r['comfort']['score']}")
            assert r["compliant"], "컴포트 점수가 판정을 오염시키면 안 된다"
    except TypeError:
        print("  (pse_bt1702 에 with_comfort 훅이 아직 없음 — 단독 검증만 수행)")
