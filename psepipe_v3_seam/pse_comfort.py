# -*- coding: utf-8 -*-
"""pse_comfort.py — 편두통 컴포트 점수 v0.1  [판정 아님 — 점수 전용]

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

_EPS = 1e-6

# ── 눈금 (v0.1 잠정 — 합성 클립 기준. 실영상 스윕으로 재보정할 것)
FLASH_SCALE = 0.05        # 15Hz 가중 Michelson 깊이×면적의 초 평균
COLOR_SCALE = 0.40        # 청(1.0)+적(0.7) 가중 화소 비율의 초 평균
GLARE_SCALE = 0.20        # 암순응 맥락 대비 고휘도 면적의 초 평균
PATTERN_SCALE = 0.90      # pse_discomfort frame_score (3cpd 정현파 ≈ 0.98)

W_FLASH, W_PATTERN, W_COLOR, W_GLARE = 0.35, 0.25, 0.25, 0.15

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
                         "flips": 0}
            self._cur_sec = s
        return self._cur

    def _close_sec(self):
        c = self._cur
        f_hz = c["flips"] / 2.0                       # 반전 2회 = 1주기
        w = _freq_weight(f_hz)
        self._sec.append({
            "flash": float(np.mean(c["flash"]) * w) if c["flash"] else 0.0,
            "color": float(np.mean(c["color"])) if c["color"] else 0.0,
            "glare": float(np.mean(c["glare"])) if c["glare"] else 0.0,
            "pattern": float(np.mean(c["pattern"])) if c["pattern"]
                       else self._pat_last,
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
                                   "pattern": []}
        for sec in self._sec:
            fn = _n(sec["flash"], FLASH_SCALE)
            cn = _n(sec["color"], COLOR_SCALE)
            gn = _n(sec["glare"], GLARE_SCALE)
            pn = _n(sec["pattern"], PATTERN_SCALE)
            scores.append(100.0 * min(1.0, W_FLASH * fn + W_PATTERN * pn
                                      + W_COLOR * cn + W_GLARE * gn))
            comp_series["flash"].append(round(fn, 4))
            comp_series["color"].append(round(cn, 4))
            comp_series["glare"].append(round(gn, 4))
            comp_series["pattern"].append(round(pn, 4))

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
            "note": "점수는 상대 비교용 v0.1 — 규격 판정 아님. 눈금 재보정 필요.",
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

    tests = [("정지 회색", solid(128)),
             ("자연풍 정지", natural()),
             ("얕은 10Hz 플리커(관문미달)", shallow_flicker()),
             ("청색 3Hz 스트로브", blue_strobe()),
             ("정지 3cpd 줄무늬", stripes3())]

    print("── pse_comfort v0.1 자가 검증 ──")
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
    print("순서 검증 통과 — 자극 3종 ≫ 자연풍·정지, 성분 귀속 정상")

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
