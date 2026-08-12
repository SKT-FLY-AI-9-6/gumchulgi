# -*- coding: utf-8 -*-
"""
pse_bt1702.py — ITU-R BT.1702 규격 준수 판정기  [단일 판정]
============================================================
질문 하나에만 답한다: **이 영상이 기준을 위반하는가.**

구현 범위 — 「광과민성 발작 예방 종합 가이드북 2026」이 인용한 BT.1702 조항 그대로.

  ① 플래시      1초 동안 3회 초과 + 화면 1/4 이상 + 휘도차 20cd/m² 이상
  ② 색상        강렬한 빨간색 플래시 (동일한 빈도·면적 기준)
  ③ 패턴        줄무늬·바둑판·고대비 무늬. 빠르게 깜빡이거나 1/4 이상 걸쳐 나타남
  ④ 지속·누적   플래시·패턴이 5초 이상 지속
  ⑤ 화면 전환   빨리 바뀌는 화면(빠른 컷)도 플래시 기준과 동일하게 간주
  ⑥ 프레임 간격 50Hz 9프레임 / 60Hz 10프레임 이상 떨어져야 허용

의도적으로 **뺀 것** — 원추 대립축(RG / BY / RB)
  등휘도 색 점멸을 잡는 채널이고 Parra 2007 등 임상 근거도 있지만, **BT.1702
  규격에 없다.** 게다가 그 임계값(RG 0.10 / BY 0.20)은 우리가 실측 스윕으로
  정한 경험값이라 근거가 없다 — 프로젝트 문서도 "임상 근거 없는 추정치"라고
  적어 두었다. 규격 준수를 증명하는 도구에 근거 없는 임계를 섞으면
  "왜 이게 위반인가"에 답할 수 없게 된다. 그래서 여기서는 제외했다.
  색 채널이 필요하면 `pse_analyze.py` 를 별도로 쓸 것 — 다만 그 결과는
  "규격 위반"이 아니라 "규격 밖 추가 위험"으로 따로 보고해야 한다.

⑥ 프레임 간격 — **별도 조항이 맞다** (2026-08-10 정정)
  처음에는 숫자가 겹쳐서(334ms ≈ 1/3초) ① 의 3Hz 한도를 프레임으로 바꿔 쓴
  것이라고 판단했다. **틀렸다.** Jordan, "Evaluating Conformance of Video Safety
  Tools for Photosensitive Epilepsy", HCII 2025 원문:

      "ITU-R 과 Ofcom 표준에는 추가 단서가 있다 — 선행엣지가 334ms 넘게 떨어진
       플래시는 안전한 것으로 본다. 다른 표준에는 이런 단서가 없다."

  즉 **시퀀스를 나누는 규칙**이다. 예를 들어 t=0.00/0.05/0.10 에 몰린 버스트
  뒤 t=0.95 에 하나가 더 있으면, 1초 창에는 4회라 WCAG·ISO·NAB-J 는 위반이지만
  ITU-R·Ofcom 은 마지막이 334ms 넘게 떨어져 새 시퀀스가 되므로 통과한다.
  → ITU-R/Ofcom 이 이 지점에서 **더 관대**하다. `sequence_rule=False` 로 끄면
    WCAG/ISO/NAB-J 동작이 된다.

화소 동일성 — 같은 화소가 관여해야 한다 (2026-08-10 추가)
  같은 논문: "화면의 25% 가 번쩍인 뒤 **다른** 25% 가 번쩍이면 방송 기준상
  안전으로 본다. 위험 시퀀스의 모든 플래시는 면적 임계를 넘을 만큼 겹쳐야 한다."
  그래서 시퀀스를 이어갈 때 관여 화소 마스크의 교집합을 누적하고, 교집합이
  25% 아래로 떨어지면 시퀀스를 끊는다.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import cv2
import numpy as np

# ---------------------------------------------------------------- BT.1702 상수
SDR_PEAK = 200.0            # cd/m², NOTE 3 (SDR peak white)
EOTF_GAMMA = 2.4            # BT.1886
DARK_LUM_THR = 160.0        # cd/m², 이 아래는 절대 휘도차, 위는 Michelson
LUM_DIFF_THR = 20.0         # cd/m², "플래시 밝기 차이가 20cd/m² 이상"
MICHELSON_THR = 1.0 / 17.0
AREA_THR = 0.25             # "화면의 1/4 이상"
MAX_PER_SEC = 3             # "1초 동안 3회 초과"
SUSTAIN_SEC = 5.0           # "5초 이상 지속되는 경우를 피하도록 권고"
SEQ_GAP_S_60 = 0.334        # 60Hz 계열 (30/60fps) — 10프레임 @30fps
SEQ_GAP_S_50 = 0.360        # 50Hz 계열 (25/50fps) —  9프레임 @25fps

def seq_gap_s(fps):
    return SEQ_GAP_S_50 if (24 <= fps <= 26 or 49 <= fps <= 51) else SEQ_GAP_S_60
MASK_W = 40                 # 화소 동일성 검사용 마스크 폭 (축소 저장)
COLOR_W = 96                # 색 채널(적색·적청) 분석 폭.
                            # 색 판정은 면적 비율만 쓰고 마스크도 40px 로 줄여
                            # 저장하므로 320px 로 돌릴 이유가 없다. CIE 변환이
                            # 프레임당 비용의 절반을 먹고 있어 여기서 줄인다.
RED_RATIO = 0.80            # 강렬한 빨간색: R/(R+G+B)
RED_MIN_V = 0.25
DUV_THR = 0.20              # CIE 1976 UCS 색차 임계.
                            # 근거: Jordan & Vanderheiden, ACM TACCESS 2024 —
                            # 적색 플래시는 채도 조건 R/(R+G+B) >= 0.8 만으로
                            # 부족하고 비적색 상태와 Δu'v' >= 0.2 를 함께 요구한다.
                            # ISO 9241-391 / WCAG 에만 상세가 있는 조항.


def decode_linear(bgr: np.ndarray) -> np.ndarray:
    rgb = bgr[..., ::-1].astype(np.float32) / 255.0
    return np.power(rgb, EOTF_GAMMA, dtype=np.float32)


COHERENCE_FRAC = 0.05     # 국소 평균 창 크기 (프레임 폭 대비). 아래 주석 참조


def luminance_cd(bgr: np.ndarray, coherent: bool = True) -> np.ndarray:
    """화면 휘도(cd/m²). coherent=True 면 국소 평균을 취한다.

    규격의 플래시는 "화면이 밝아졌다/어두워졌다"는 **공간적으로 일관된** 변화다.
    화소별 차이를 그대로 쓰면 빠른 팬(whip pan)에서 오탐이 난다 — 카메라가 휙
    돌면 화소마다 휘도가 크게 요동치지만 화면이 밝아진 것은 아니다. 실측에서
    노이즈 배경을 초당 260px 로 팬하는 클립이 플래시 위반으로 잡혔다.

    국소 평균을 취하면 팬의 화소 단위 요동은 상쇄되고, 넓은 영역이 함께
    밝아지는 진짜 플래시는 그대로 남는다. 창 크기는 프레임 폭의 5% — 규격의
    면적 기준(25%)보다 훨씬 작아 국소 점멸 판정에는 영향이 없다.
    """
    lin = decode_linear(bgr)
    y = 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]
    y = (y * SDR_PEAK).astype(np.float32)
    if coherent:
        k = max(3, int(round(y.shape[1] * COHERENCE_FRAC)) | 1)
        y = cv2.blur(y, (k, k))
    return y


# sRGB 원색의 CIE 1976 UCS 좌표 (적↔청 축 정의용)
UV_RED = np.array([0.4507, 0.5229], np.float32)
UV_BLUE = np.array([0.1755, 0.1579], np.float32)
_RB_AXIS = (UV_RED - UV_BLUE)
_RB_AXIS = _RB_AXIS / np.linalg.norm(_RB_AXIS)
_RB_MID = (UV_RED + UV_BLUE) / 2.0


def uv_prime(bgr: np.ndarray) -> np.ndarray:
    """8bit BGR -> CIE 1976 UCS (u', v'). 반환 shape (...,2)."""
    lin = decode_linear(bgr)
    r, g, b = lin[..., 0], lin[..., 1], lin[..., 2]
    X = 0.4124 * r + 0.3576 * g + 0.1805 * b
    Y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    Z = 0.0193 * r + 0.1192 * g + 0.9505 * b
    d = X + 15.0 * Y + 3.0 * Z + 1e-6
    return np.stack([4.0 * X / d, 9.0 * Y / d], axis=-1).astype(np.float32)


RB_NEAR = 0.15            # u'v' 상에서 원색까지 이 거리 안이면 '적 계열'/'청 계열'
RB_MIN_V = 40             # 8bit 최대 채널이 이 값 미만이면 색도가 무의미 (검정 배제)


def rb_sides(bgr: np.ndarray, uv: np.ndarray):
    """적 계열 / 청 계열 마스크.

    축 위 부호(중점 기준)로 가르면 안 된다 — 실측상 **노랑이 적색 쪽으로,
    검정이 청색 쪽으로** 투영돼 오탐이 났다. 원색까지의 거리로 판정한다.

        적(255,0,0) 0.000 · 적 탈채도 0.063
        청(0,0,255) 0.000 · 청 탈채도 0.068
        황 0.249 · 백/회 0.259 · 녹 0.328 · 흑 0.236(청까지)

    적·청 계열은 0.068 이하, 나머지는 0.236 이상이라 0.15 로 깨끗이 갈린다.
    검정은 u'v' 가 분모 0 근처라 값 자체가 무의미하므로 밝기로 따로 막는다.
    """
    lit = bgr.max(axis=2) >= RB_MIN_V
    dr = np.linalg.norm(uv - UV_RED, axis=-1)
    db = np.linalg.norm(uv - UV_BLUE, axis=-1)
    return (dr < RB_NEAR) & lit, (db < RB_NEAR) & lit


def saturated_red(bgr: np.ndarray) -> np.ndarray:
    f = bgr.astype(np.float32) / 255.0
    b, g, r = f[..., 0], f[..., 1], f[..., 2]
    tot = r + g + b + 1e-6
    return (r / tot >= RED_RATIO) & (r >= RED_MIN_V)


# ══════════════════════════════════════════ 검출 화소 -> 격자 마스크
MASK_GRID_W = 64          # 게인장 셀(짧은변/8)보다 촘촘하되 메모리는 무시할 수준

def _grid(mask, gw: int, gh: int) -> np.ndarray:
    """불리언 검출 마스크를 격자 커버리지(0~1)로 줄인다. INTER_AREA = 면적비."""
    return cv2.resize(mask.astype(np.float32), (gw, gh),
                      interpolation=cv2.INTER_AREA)


def grid_from_counter(counter, T: int, gw: int, gh: int) -> np.ndarray:
    """Counter 가 **이미 갖고 있는** 플래시별 화소 마스크를 프레임축에 편다.

    두 번째 디코드가 필요 없다 — push() 가 대립쌍이 완성될 때마다 교집합
    마스크를 self.masks 에 쌓아두기 때문이다. 각 플래시는 계수 창(1초) 동안
    '지금 여기가 번쩍인다'는 뜻이므로 [edge, edge+win) 에 최댓값으로 얹는다.
    """
    acc = np.zeros((T, gh, gw), np.float16)
    for e, m in zip(counter.edges, counter.masks):
        g = _grid(m, gw, gh).astype(np.float16)
        lo, hi = max(0, e), min(T, e + counter.win)
        if hi > lo:
            np.maximum(acc[lo:hi], g, out=acc[lo:hi])
    return acc

class Counter:
    """대립 전환쌍 = 플래시 1회. 같은 시퀀스 안에서 1초에 3회 초과면 위반.

    시퀀스가 끊기는 조건이 둘 있다 (Jordan, HCII 2025 기준):

      · **334ms 규칙** — ITU-R / Ofcom 에만 있는 조항. 선행엣지가 334ms 넘게
        떨어진 플래시는 같은 시퀀스로 묶지 않는다. WCAG·ISO·NAB-J 에는 이
        단서가 없어서, 같은 영상이라도 ITU-R 은 통과하고 WCAG 는 위반일 수 있다.
        (예: t=0.00/0.05/0.10 버스트 뒤 t=0.95 하나 → 1초 창엔 4회지만
         마지막이 334ms 넘게 떨어져 새 시퀀스가 되므로 ITU-R 은 통과)

      · **화소 동일성** — "화면의 25%가 번쩍인 뒤 **다른** 25%가 번쩍이면
        방송 기준상 안전"(Jordan 2025). 한 시퀀스의 플래시들은 겹치는 영역이
        면적 임계를 넘어야 한다. 그래서 시퀀스가 이어질 때마다 마스크 교집합을
        누적하고, 교집합이 임계 아래로 떨어지면 거기서 시퀀스를 끊는다.
    """

    def __init__(self, name: str, fps: float, sequence_rule: bool = True):
        self.name = name
        self.fps = fps
        self.win = max(1, int(round(fps)))
        self.sequence_rule = sequence_rule
        self.gap_frames = seq_gap_s(fps) * fps
        self.pending: tuple[int, int, np.ndarray] | None = None
        self.edges: list[int] = []              # 플래시 선행엣지 프레임
        self.masks: list[np.ndarray] = []       # 그 플래시에 관여한 화소 마스크
        self.areas: list[float] = []            # 프레임별 순 방향 면적(보고용)
        self.n_frames = 0

    def push(self, idx: int, mask_up: np.ndarray, mask_dn: np.ndarray) -> None:
        # **순 방향성으로 판정한다.** 규격의 "화면의 1/4 이상 동시에 플래시"는
        # 그 면적이 **같은 방향으로** 변했다는 뜻이다. 밝아진 면적과 어두워진
        # 면적을 각각 따로 보면 모션이 걸린다 — 실측에서 휙 돌리기는
        # 밝아짐 0.239 / 어두워짐 0.237 로 양쪽 다 25% 근처였다.
        # 차이를 취하면 모션은 상쇄되고(0.089) 진짜 점멸만 남는다(1.000).
        au = float(mask_up.mean())
        ad = float(mask_dn.mean())
        net = au - ad
        self.areas.append(abs(net))
        self.n_frames = idx + 1

        tr = 0
        if net > AREA_THR:
            tr, mask = +1, mask_up
        elif -net > AREA_THR:
            tr, mask = -1, mask_dn
        else:
            return

        if self.pending is not None and self.pending[1] == -tr:
            # 플래시 1회 완성 — 관여 화소는 두 전환의 교집합
            self.edges.append(self.pending[0])
            self.masks.append(self.pending[2] & mask)
            self.pending = None
        else:
            self.pending = (idx, tr, mask)

    # ---------- 시퀀스 분할 (334ms 규칙 + 화소 동일성)
    def sequences(self) -> list[list[int]]:
        seqs: list[list[int]] = []
        cur: list[int] = []
        inter: np.ndarray | None = None
        for k, (e, m) in enumerate(zip(self.edges, self.masks)):
            if not cur:
                cur, inter = [k], m.copy()
                continue
            gap_ok = True
            if self.sequence_rule:
                gap_ok = (e - self.edges[cur[-1]]) <= self.gap_frames
            cand = inter & m
            overlap_ok = float(cand.mean()) > AREA_THR
            if gap_ok and overlap_ok:
                cur.append(k)
                inter = cand
            else:
                seqs.append(cur)
                cur, inter = [k], m.copy()
        if cur:
            seqs.append(cur)
        return seqs

    def _counts(self) -> np.ndarray:
        """프레임별 '같은 시퀀스 안에서 직전 1초의 플래시 수' 최대값."""
        c = np.zeros(max(self.n_frames, 1), int)
        for seq in self.sequences():
            es = [self.edges[k] for k in seq]
            for e in es:
                for f in range(e, min(e + self.win, len(c))):
                    n = sum(1 for x in es if f - self.win < x <= f)
                    if n > c[f]:
                        c[f] = n
        return c

    def viol_array(self) -> np.ndarray:
        return self._counts() > MAX_PER_SEC

    def min_separation(self) -> int | None:
        if len(self.edges) < 2:
            return None
        return int(min(b - a for a, b in zip(self.edges, self.edges[1:])))

    def tight_pairs(self, need: int) -> list:
        """**어디서** 간격이 모자랐는지. 이게 있어야 그 구간만 보정할 수 있다.
        ① 의 '초당 3회'는 짧은 고주파 버스트를 놓친다 — 2프레임 간격 쌍은
        15Hz 이고 그게 임상 최고 위험대역(15~20Hz)이다. ⑥ 이 그걸 잡는다."""
        out = []
        for a, b in zip(self.edges, self.edges[1:]):
            if b - a < need:
                out.append([round(a / self.fps, 2), round((b + self.win) / self.fps, 2)])
        return out

    def sustained(self) -> tuple[bool, float]:
        need = max(1, int(round(SUSTAIN_SEC * self.fps)))
        run = longest = 0
        for c in self._counts():
            run = run + 1 if c >= MAX_PER_SEC else 0
            longest = max(longest, run)
        return bool(longest >= need), round(longest / self.fps, 2)

    def segments(self) -> list:
        v = self.viol_array()
        segs, st = [], None
        for i, x in enumerate(v):
            if x and st is None:
                st = i
            elif not x and st is not None:
                segs.append([round(st / self.fps, 2), round(i / self.fps, 2)]); st = None
        if st is not None:
            segs.append([round(st / self.fps, 2), round(len(v) / self.fps, 2)])
        return segs

    def area_segments(self) -> list:
        """면적 축이 한도를 넘은 **프레임 구간**. 빈도 축이 안 넘어 '적합'이어도
        면적은 넘을 수 있다 — 여백 모드가 그 위치를 알아야 거기만 보정한다."""
        out, st = [], None
        for i, a in enumerate(self.areas):
            if a > AREA_THR and st is None:
                st = i
            elif a <= AREA_THR and st is not None:
                out.append([round(st / self.fps, 2), round(i / self.fps, 2)])
                st = None
        if st is not None:
            out.append([round(st / self.fps, 2), round(len(self.areas) / self.fps, 2)])
        return out

    def co_axes(self) -> dict:
        """**같은 프레임에서** 잰 (빈도, 면적). 축을 따로 최대화하면 서로 다른
        프레임의 값이 섞여 실제보다 아슬아슬해 보인다."""
        c = self._counts()
        n = min(len(c), len(self.areas))
        if n == 0:
            return {"per_sec": 0, "area_pct": 0.0, "closeness": 0.0}
        best, bi = -1.0, 0
        for i in range(n):
            v = min(c[i] / MAX_PER_SEC, self.areas[i] / AREA_THR)
            if v > best:
                best, bi = v, i
        return {"per_sec": int(c[bi]), "area_pct": round(self.areas[bi] * 100, 1),
                "closeness": round(float(best), 3)}

    def summary(self) -> dict:
        v = self.viol_array()
        c = self._counts()
        a = np.array(self.areas, float)
        sus, longest = self.sustained()
        return {
            "rule": self.name,
            "pass": bool(not v.any()),
            "violation_seconds": round(float(v.sum()) / self.fps, 2),
            "max_per_sec": int(c.max()) if c.size else 0,
            "limit_per_sec": MAX_PER_SEC,
            "max_area_pct": round(float(a.max()) * 100, 1) if a.size else 0.0,
            "sustained_over_5s": sus,
            "longest_run_s": longest,
            "total_events": len(self.edges),
            "n_sequences": len(self.sequences()),
            "min_separation_frames": self.min_separation(),
            "sequence_rule_applied": self.sequence_rule,
            "segments": self.segments(),
            "area_segments": self.area_segments(),
            "co_axes": self.co_axes(),
        }


def _shrink(mask: np.ndarray) -> np.ndarray:
    """화소 동일성 비교용으로 마스크를 축소한다 (블록 과반이면 참)."""
    h, w = mask.shape
    if w <= MASK_W:
        return mask
    hh = max(2, int(round(h * MASK_W / w)))
    return cv2.resize(mask.astype(np.float32), (MASK_W, hh),
                      interpolation=cv2.INTER_AREA) > 0.5


def analyze(path, width: int = 320, with_pattern: bool = True,
            with_cut: bool = True, sequence_rule: bool = True,
            verbose: bool = False, fps: float = None,
            pattern_result=None, cut_result=None, keep_masks: bool = False) -> dict:
    """path 대신 **프레임 이터러블**(BGR uint8)을 줄 수 있다. 그 경우 fps 가 필수.

    필터의 폐루프에서 쓴다 — 라운드마다 무손실로 쓰고 다시 디코드하던 왕복이
    전체 시간의 대부분이었다. 프레임을 그대로 넘기면 인코딩 자체가 없어 더
    정확하고 훨씬 빠르다. 축소도 경로 경로와 같은 INTER_AREA 로 한다.

    pattern_result / cut_result 를 주면 그 채널은 다시 계산하지 않는다.
    **컷은 매끄러운 게인장으로 절대 변하지 않으므로** 한 번 재고 재사용하면 된다
    (곱셈 게인은 장면 전환을 만들지도 없애지도 못한다).
    """
    frames_in = None
    if isinstance(path, (str, os.PathLike)):
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            raise IOError(f"영상을 열 수 없습니다: {path}")
        f_fps = cap.get(cv2.CAP_PROP_FPS)
        if not f_fps or f_fps != f_fps or f_fps <= 0 or f_fps > 240:
            f_fps = 30.0
        fps = f_fps
    else:
        if fps is None:
            raise ValueError("프레임을 직접 넘길 때는 fps 가 필요합니다")
        cap, frames_in = None, iter(path)

    flash = Counter("플래시", fps, sequence_rule=sequence_rule)
    red_c = Counter("적색", fps, sequence_rule=sequence_rule)
    rb_c = Counter("적청교대", fps, sequence_rule=sequence_rule)
    prev_lum = prev_red = prev_uv = None
    prev_r = prev_b = None
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
        if not w0 or not h0:
            break
        small = (cv2.resize(frame, (width, max(2, int(round(h0 * width / w0)))),
                            interpolation=cv2.INTER_AREA)
                 if w0 != width else frame)
        lum = luminance_cd(small)
        # 색 채널은 축소 프레임에서 (면적 비율만 필요)
        cw = min(COLOR_W, small.shape[1])
        small_c = cv2.resize(small, (cw, max(2, int(round(small.shape[0] * cw / small.shape[1])))),
                             interpolation=cv2.INTER_AREA) if cw < small.shape[1] else small
        red = saturated_red(small_c)
        uv = uv_prime(small_c)
        r_side, b_side = rb_sides(small_c, uv)

        if prev_lum is not None:
            n = lum.size
            # ① 유해 휘도 변화 — 어두운 쪽 160cd/m² 미만이면 절대차, 이상이면 Michelson
            ld = np.minimum(prev_lum, lum)
            lb = np.maximum(prev_lum, lum)
            d = lb - ld
            mich = np.where(lb + ld > 0, d / np.maximum(lb + ld, 1e-6), 0.0)
            harmful = ((ld < DARK_LUM_THR) & (d >= LUM_DIFF_THR)) | \
                      ((ld >= DARK_LUM_THR) & (mich > MICHELSON_THR))
            sg = np.sign(lum - prev_lum)
            flash.push(idx, _shrink(harmful & (sg > 0)), _shrink(harmful & (sg < 0)))

            # ② 강렬한 빨간색 전환 — 채도 조건 + **Δu\'v\' >= 0.2** (ISO/WCAG 조항)
            duv = np.linalg.norm(uv - prev_uv, axis=-1)
            big = duv >= DUV_THR
            red_c.push(idx, _shrink((red & ~prev_red) & big),
                            _shrink((prev_red & ~red) & big))

            # [보조] 적↔청 교대 — 규격 밖. Parra 2007 유발률 100% 근거.
            # 적 계열 <-> 청 계열의 실제 맞바꿈만 센다 (중점 통과가 아니라).
            rb_c.push(idx, _shrink(r_side & prev_b & big),
                           _shrink(b_side & prev_r & big))

        prev_lum, prev_red, prev_uv = lum, red, uv
        prev_r, prev_b = r_side, b_side
        idx += 1
        if verbose and idx % 300 == 0:
            print(f"    ... {idx} frames", file=sys.stderr)

    if cap is not None:
        cap.release()
    if idx == 0:
        raise IOError(f"프레임을 읽지 못했습니다: {path}")

    rules = {"flash": flash.summary(), "red": red_c.summary()}
    supplementary = {"rb": rb_c.summary()}   # 규격 밖 — 판정에 넣지 않는다

    # ③ 패턴
    if pattern_result is not None:
        rules["pattern"] = pattern_result
    elif with_pattern:
        try:
            import pse_pattern
            pr = pse_pattern.analyze(path, width=width, verbose=False,
                                     keep_masks=keep_masks)
            rules["pattern"] = {
                "rule": "패턴", "pass": bool(pr["pass"]), "co_axes": pr.get("co_axes"),
                "violation_seconds": pr["violation_seconds"],
                "max_pairs": pr["max_pairs"], "max_area_pct": pr["max_area_pct"],
                "segments": [list(s) for s in pr["segments"]],
                "_masks": pr.get("_masks"),
            }
        except Exception as exc:  # noqa: BLE001
            rules["pattern"] = {"rule": "패턴", "pass": None, "error": str(exc)}

    # ⑤ 화면 전환
    if cut_result is not None:
        rules["cut"] = cut_result
    elif with_cut:
        try:
            import pse_cut
            cr = pse_cut.analyze(path, width=width)
            rules["cut"] = {
                "rule": "화면전환", "pass": bool(not cr["verdict"]["dangerous"]),
                "violation_seconds": cr["violation_seconds"],
                "max_per_sec": cr["max_cuts_per_sec"], "limit_per_sec": cr["limit_cuts_per_sec"],
                "total_cuts": cr["total_cuts"], "cuts_per_sec_mean": cr["cuts_per_sec_mean"],
                "sustained_over_5s": cr["sustained_over_5s"],
                "segments": cr["segments"],
                "cut_times": cr.get("cut_times", []),
            }
        except Exception as exc:  # noqa: BLE001
            rules["cut"] = {"rule": "화면전환", "pass": None, "error": str(exc)}

    # ④ 5초 지속 — 플래시·적색·화면전환·패턴 중 어느 하나라도
    sustained = bool(rules["flash"]["sustained_over_5s"] or rules["red"]["sustained_over_5s"]
                     or rules.get("cut", {}).get("sustained_over_5s", False)
                     or (rules.get("pattern", {}).get("violation_seconds", 0) or 0) >= SUSTAIN_SEC)

    # ⑥ 프레임 간격
    need_sep = math.ceil(fps / MAX_PER_SEC)
    seps = [r["min_separation_frames"] for r in (rules["flash"], rules["red"])
            if r.get("min_separation_frames") is not None]
    obs_sep = min(seps) if seps else None
    sep_ok = (obs_sep is None) or (obs_sep >= need_sep)

    failed = [r["rule"] for r in rules.values() if r.get("pass") is False]
    if sustained:
        failed.append("5초지속")
    supp_failed = [r["rule"] for r in supplementary.values() if r.get("pass") is False]

    if not sep_ok:
        need_sep_f = need_sep
        for c in (flash, red_c):
            for a, b in c.tight_pairs(need_sep_f):
                rules.setdefault("_sep", {"rule": "프레임간격", "segments": []})
                rules["_sep"]["segments"].append([a, b])

    segs = []
    for key, r in rules.items():
        for s in r.get("segments", []) or []:
            segs.append({"start_s": s[0], "end_s": s[1], "rule": r["rule"]})
    segs.sort(key=lambda x: x["start_s"])

    # ── 검출 화소의 공간 위치 (선택) — 재디코드 없이 카운터에서 뽑는다
    _spatial = None
    if keep_masks:
        gw = min(MASK_GRID_W, width)
        gh = max(2, int(round(gw * lum.shape[0] / lum.shape[1])))
        _spatial = {"grid": [gh, gw],
                    "flash": grid_from_counter(flash, idx, gw, gh),
                    "red":   grid_from_counter(red_c, idx, gw, gh)}
        pm = (rules.get("pattern") or {}).get("_masks")
        if pm is not None:
            _spatial["pattern"] = np.stack([
                cv2.resize(np.asarray(x, np.float32), (gw, gh),
                           interpolation=cv2.INTER_AREA)
                for x in pm]).astype(np.float16)

    return {
        "video": str(path) if cap is not None or isinstance(path, str) else "<frames>",
        "standard": "ITU-R BT.1702 (가이드북 2026 인용 조항)",
        "fps": round(fps, 3), "frames": idx, "duration_s": round(idx / fps, 2),
        "compliant": bool(not failed),
        "failed_rules": failed,
        "rules": rules,
        # ---- 규격 밖 추가 위험. **규격 판정(compliant)에는 절대 넣지 않는다.**
        # 근거는 임상(Parra 2007: 적-청 교대 유발률 100%, 단색 적 88% / 청 72%)이고
        # 임계는 표준에서 가져왔지만(CIE 1976 UCS Δu'v' >= 0.2), 이 축 자체는
        # BT.1702 에도 WCAG 에도 없다. 그래서 "위반"이 아니라 "주의"로 보고한다.
        "supplementary": supplementary,
        "supplementary_flags": supp_failed,
        "frame_separation": {
            "required_frames": need_sep,
            "observed_min_frames": obs_sep,
            "pass": bool(sep_ok),
            "note": "이 조항은 초당 3회 한도를 프레임 수로 표현한 것 (ceil(fps/3))",
        },
        "sustained_over_5s": sustained,
        "sequence_rule": {
            "applied": sequence_rule,
            "gap_seconds": seq_gap_s(fps),
            "note": ("ITU-R/Ofcom 조항 적용 — 선행엣지 334ms 초과 시 다른 시퀀스. "
                     "WCAG/ISO/NAB-J 로 재려면 sequence_rule=False"),
        },
        "violation_segments": segs,
        "_spatial": _spatial,
    }


def report(r: dict) -> str:
    L = [f"{r['video']}  ({r['duration_s']}s @ {r['fps']:.0f}fps)"]
    L.append(f"  판정: {'적합' if r['compliant'] else '위반 — ' + ', '.join(r['failed_rules'])}")
    L.append("")
    f, rd = r["rules"]["flash"], r["rules"]["red"]
    L.append(f"  ① 플래시    {'적합' if f['pass'] else '위반'}  "
             f"{f['violation_seconds']:>5.2f}s  최대 {f['max_per_sec']}회/s (한도 {f['limit_per_sec']})  "
             f"최대면적 {f['max_area_pct']:.0f}%")
    L.append(f"  ② 적색      {'적합' if rd['pass'] else '위반'}  "
             f"{rd['violation_seconds']:>5.2f}s  최대 {rd['max_per_sec']}회/s  "
             f"최대면적 {rd['max_area_pct']:.0f}%")
    if "pattern" in r["rules"]:
        p = r["rules"]["pattern"]
        if p.get("pass") is None:
            L.append(f"  ③ 패턴      측정불가 ({p.get('error','')})")
        else:
            L.append(f"  ③ 패턴      {'적합' if p['pass'] else '위반'}  "
                     f"{p['violation_seconds']:>5.2f}s  최대 {p['max_pairs']:.0f}쌍  "
                     f"최대면적 {p['max_area_pct']:.0f}%")
    L.append(f"  ④ 5초지속   {'적합' if not r['sustained_over_5s'] else '위반'}")
    if "cut" in r["rules"]:
        c = r["rules"]["cut"]
        if c.get("pass") is None:
            L.append(f"  ⑤ 화면전환  측정불가 ({c.get('error','')})")
        else:
            L.append(f"  ⑤ 화면전환  {'적합' if c['pass'] else '위반'}  "
                     f"{c['violation_seconds']:>5.2f}s  최대 {c['max_per_sec']}컷/s (한도 {c['limit_per_sec']})  "
                     f"총 {c['total_cuts']}컷")
    fs = r["frame_separation"]
    obs = fs["observed_min_frames"]
    L.append(f"  ⑥ 프레임간격 {'적합' if fs['pass'] else '위반'}  "
             f"관측 최소 {obs if obs is not None else '-'}프레임 / 필요 {fs['required_frames']}프레임")
    sup = r.get("supplementary", {}).get("rb")
    if sup:
        L.append("")
        L.append(f"  [보조·규격밖] 적↔청 교대  {'없음' if sup['pass'] else '검출'}  "
                 f"{sup['violation_seconds']:>5.2f}s  최대 {sup['max_per_sec']}회/s  "
                 f"최대면적 {sup['max_area_pct']:.0f}%")
        if not sup["pass"]:
            L.append("     └ Parra 2007 에서 유발률 100% 인 조합. 규격에는 없는 축이라")
            L.append("       규격 판정에는 반영하지 않았다.")
    if r["violation_segments"]:
        L.append("")
        L.append("  위반 구간:")
        for s in r["violation_segments"][:12]:
            L.append(f"    {s['start_s']:>6.2f} ~ {s['end_s']:>6.2f}s   {s['rule']}")
        if len(r["violation_segments"]) > 12:
            L.append(f"    ... 외 {len(r['violation_segments'])-12}건")
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="ITU-R BT.1702 규격 준수 판정")
    ap.add_argument("srcs", nargs="+")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--brief", action="store_true", help="한 줄 요약만")
    ap.add_argument("--no-pattern", action="store_true", help="패턴 검사 생략 (빠름)")
    ap.add_argument("--no-cut", action="store_true", help="화면전환 검사 생략")
    a = ap.parse_args()
    n_bad = 0
    for p in a.srcs:
        try:
            r = analyze(p, with_pattern=not a.no_pattern, with_cut=not a.no_cut)
            if not r["compliant"]:
                n_bad += 1
            if a.json:
                print(json.dumps(r, ensure_ascii=False, indent=1))
            elif a.brief:
                tag = "적합" if r["compliant"] else "위반"
                why = "" if r["compliant"] else "  — " + ", ".join(r["failed_rules"])
                sup = "  [보조:적청]" if r.get("supplementary_flags") else ""
                print(f"[BT.1702] {tag}  {r['duration_s']:>6.1f}s  {p}{why}{sup}")
            else:
                print(report(r)); print()
        except Exception as exc:  # noqa: BLE001
            print(f"[BT.1702] ERROR {p}: {exc}", file=sys.stderr)
    if len(a.srcs) > 1 and not a.json:
        print(f"— 총 {len(a.srcs)}편 중 위반 {n_bad}편")
