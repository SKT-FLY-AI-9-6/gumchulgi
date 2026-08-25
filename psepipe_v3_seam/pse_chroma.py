# -*- coding: utf-8 -*-
"""pse_chroma.py — M2 색상 작동기: 색도분리 제한 + 청색 지속 감쇠  [T4/T5 전용]

왜 필요한가
  티어 실측(validation/tier_real3.csv)에서 pinkvenom 은 플래시·패턴 축을
  아무리 조여도 comfort 선량이 안 움직였다(54.7 포화) — 성분 분해가 원인을
  말한다: color 0.934 지배. 통합 티어 표 v2 의 색상 축(M2) 작동기가 이것.

두 기전 (검출 정의는 pse_migraine M2 와 동일)
  ① 색도분리 플리커 제한 [T4/T5] — 휘도 보존 탈채도
     조명 색이 교대(적↔청 등)하면 프레임 대표 색도(휘도 가중 u'v' 평균)가
     큰 스텝으로 튄다 (Haigh 2019: 색도분리가 클수록 불쾌감 단조 증가).
     스텝의 EMA 가 CHROMA_STEP(0.06 [가설]) 을 넘는 동안, 프레임 전체를
     자기 휘도의 회색 방향으로 s 만큼 블렌드한다 — 교대하는 양쪽 색이
     똑같이 중립으로 끌려 스텝이 (1−s) 배로 줄고, 휘도는 보존된다.
     **함정 (전역 색도 시프트 — 폐기)**: 직전 출력 색 쪽으로 CrCb 를
     균일 시프트하는 방식을 먼저 시도했다. 교대 자극과 매 프레임 싸우며
     시프트 자체가 출렁이고, 채널 클리핑이 휘도 변화를 만들어 **PSE
     화면전환 위반을 신규 생성**했다(합성 적↔청 실측: comfort 22.9→37.3
     악화, flash 성분 0→0.41). 탈채도는 방향이 중립 하나뿐이라 이 되먹임이
     원리적으로 없다.
  ② 청색 지속 감쇠 [T5 전용]
     청색(450–480nm)이 광공포 통증 최대 (Noseda/Burstein, Brain 2016).
     근청색·lit 면적의 EMA(시상수 BLUE_SUSTAIN 1s)가 AREA_MIN(25%) 이상
     지속되면 근청색 화소를 **휘도 보존 탈채도**(자기 휘도의 회색 방향
     블렌드, BLUE_W 배 [가설, 보수적])한다. B 채널만 줄이는 방식은 함정 —
     순수 청색에서 휘도만 내려가고 색도(u'v')는 그대로라 청색 노출이
     하나도 줄지 않는다 (구현 중 실측으로 확인).

설계 원칙 (pse_soften 과 동일)
  · 독립 패스 — 기존 파일 무수정, 티어 체인 마지막 단, 출력은 pse_bt1702
    재판정 필수 (색 이동이 적색 축을 건드리지 않는지 이걸로 보증).
  · 무개입 시 완전 항등 — 스트림 카피.
  · 컷 리셋 — 장면이 바뀌면 직전 색도를 잊는다 (컷 너머로 제한하면
    새 장면 전체가 이전 장면 색으로 물든다). NCC 컷 검출은 pselive3 와
    같은 정의(64x64 그레이, 임계 0.45), 불응기 0.5s.
  · 비용은 seam 의 색충실도 축(Δu'v')으로 잰다 — 이 작동기는 의도적으로
    색을 움직이므로 duv 가 곧 개입량이고, 적색 규격 임계 0.20 대비
    어느 수준인지로 지각 크기를 가늠한다.
"""
from __future__ import annotations

import argparse
import os
import subprocess

import cv2
import numpy as np

import pse_migraine as PM
from pse_bt1702 import luminance_cd, uv_prime, UV_BLUE, RB_NEAR, RB_MIN_V

CHROMA_STEP = PM.CHROMA_STEP      # 0.06 [가설] — pse_migraine 과 단일 정의
AREA_MIN = PM.AREA_MIN            # 0.25
BLUE_W = 0.35                     # [가설] 청색 탈채도 강도 (보수적)
BLUE_ATTACK_S = 0.5
BLUE_RELEASE_S = 1.0
PEAK_TAU_S = 1.0                  # 피크 스텝의 감쇠 시상수
TARGET_FRAC = 0.85                # 목표 스텝 = CHROMA_STEP × 이 값 (여유)
DESAT_MAX = 0.85                  # 탈채도 상한 (완전 흑백은 만들지 않는다)
DESAT_ATTACK_S = 0.2
DESAT_RELEASE_S = 0.6
CUT_THRESH = 0.45
CUT_GAP_S = 0.5


class ChromaLimiter:
    def __init__(self, fps: float, tier: str = "t5", analysis_w: int = 320):
        self.fps = fps
        self.blue_on = (tier == "t5")
        self.aw = analysis_w
        self.prev_uv = None            # 직전 "입력"의 대표 색도 (되먹임 없음)
        self.step_flags = []           # 최근 1초 창의 초과 전환 여부 (M2 계수 규칙)
        self.win = max(1, int(round(fps)))
        self.peak = 0.0                # 감쇠형 피크 스텝 — 강도의 근거
        self._p_decay = float(np.exp(-1.0 / max(1.0, fps * PEAK_TAU_S)))
        self.desat = 0.0
        self.blue_ema = 0.0
        self.blue_w = 0.0
        self._d_att = 1.0 - float(np.exp(-1.0 / max(1.0, fps * DESAT_ATTACK_S)))
        self._d_rel = 1.0 - float(np.exp(-1.0 / max(1.0, fps * DESAT_RELEASE_S)))
        self._b_alpha = 1.0 - float(np.exp(-1.0 / max(1.0, fps * PM.BLUE_SUSTAIN_S)))
        self._b_att = 1.0 - float(np.exp(-1.0 / max(1.0, fps * BLUE_ATTACK_S)))
        self._b_rel = 1.0 - float(np.exp(-1.0 / max(1.0, fps * BLUE_RELEASE_S)))
        self._prev_ncc = None
        self._since_cut = 10 ** 9
        self._cut_gap = max(1, int(round(fps * CUT_GAP_S)))
        self.stats = {"frames": 0, "step_limited": 0, "blue_frames": 0,
                      "max_step": 0.0, "max_shift": 0.0, "cuts": 0}

    def _is_cut(self, small_bgr):
        g = cv2.resize(cv2.cvtColor(small_bgr, cv2.COLOR_BGR2GRAY),
                       (64, 64)).astype(np.float32)
        g -= g.mean()
        sd = float(g.std())
        gn = g / sd if sd > 1e-3 else np.zeros_like(g)
        cut = False
        if self._prev_ncc is not None and sd > 1e-3:
            cut = float((gn * self._prev_ncc).mean()) < CUT_THRESH
        if cut and self._since_cut < self._cut_gap:
            cut = False
        self._since_cut = 0 if cut else self._since_cut + 1
        self._prev_ncc = gn
        if cut:
            self.stats["cuts"] += 1
        return cut

    @staticmethod
    def _rep_uv(small_bgr):
        lum = luminance_cd(small_bgr, coherent=False)
        uv = uv_prime(small_bgr)
        w = float(lum.sum()) + 1e-6
        return (uv * lum[..., None]).reshape(-1, 2).sum(axis=0) / w, lum

    def process(self, frame: np.ndarray) -> np.ndarray:
        self.stats["frames"] += 1
        h0, w0 = frame.shape[:2]
        small = cv2.resize(frame, (self.aw, max(2, int(round(h0 * self.aw / w0)))),
                           interpolation=cv2.INTER_AREA)
        if self._is_cut(small):
            self.prev_uv = None
            self.step_flags.clear()
            self.peak = 0.0
        uv_in, lum = self._rep_uv(small)
        lit = lum >= PM.LUM_LIT_CD

        out = None

        # ── ① 색도분리 플리커 → 전역 탈채도 (모듈 주석 참조)
        # 발동은 M2 와 같은 계수 규칙(1초 창의 초과 전환 CHROMA_PER_SEC 회
        # 이상), 강도는 감쇠형 피크 스텝 — 스텝 EMA 로 하면 교대 사이의
        # 무변화 프레임이 평균을 희석해 강도가 1/5 로 죽는다(실측 0.1).
        step = 0.0
        if self.prev_uv is not None:
            step = float(np.linalg.norm(uv_in - self.prev_uv))
            self.stats["max_step"] = max(self.stats["max_step"], step)
        self.prev_uv = uv_in
        self.step_flags.append(step > CHROMA_STEP)
        del self.step_flags[:-self.win]
        self.peak = max(step, self.peak * self._p_decay)
        s_t = 0.0
        if sum(self.step_flags) >= PM.CHROMA_PER_SEC and self.peak > CHROMA_STEP:
            s_t = float(np.clip(1.0 - CHROMA_STEP * TARGET_FRAC / self.peak,
                                0.0, DESAT_MAX))
        if s_t > 0.0 and self.desat < 0.05:
            # 발동 순간은 스냅 — 램프로 올리면 ① 앞단 0.5s+ 가 임계 초과로
            # 새고 ② 교대 프레임들이 매번 다른 탈채도로 나가 pse_cut 의
            # 왕복 배제(같은 샷 복귀 매칭)가 깨져 **화면전환 위반이 신규
            # 생성**된다(합성 적↔청 실측). 스냅이면 교대가 일정한 탈채도로
            # 반복돼 왕복 배제가 다시 작동한다. 해제는 램프(release) 유지.
            self.desat = s_t
        else:
            a = self._d_att if s_t > self.desat else self._d_rel
            self.desat += (s_t - self.desat) * a
        if self.desat > 0.02:
            self.stats["step_limited"] += 1
            self.stats["max_shift"] = max(self.stats["max_shift"], self.desat)
            f32 = frame.astype(np.float32)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
            out = np.clip(f32 + self.desat * (gray[..., None] - f32),
                          0, 255).astype(np.uint8)

        # ── ② 청색 지속 감쇠 (t5) — 휘도 보존 탈채도
        if self.blue_on:
            uv = uv_prime(small)
            near_blue = (np.linalg.norm(uv - UV_BLUE, axis=-1) < RB_NEAR) & lit \
                        & (small.max(axis=2) >= RB_MIN_V)
            self.blue_ema += (float(near_blue.mean()) - self.blue_ema) * self._b_alpha
            w_t = 1.0 if self.blue_ema >= AREA_MIN else 0.0
            a = self._b_att if w_t > self.blue_w else self._b_rel
            self.blue_w += (w_t - self.blue_w) * a
            if self.blue_w > 0.02:
                self.stats["blue_frames"] += 1
                base = (out if out is not None else frame).astype(np.float32)
                m = cv2.GaussianBlur(near_blue.astype(np.float32), (0, 0), 3.0)
                alpha = cv2.resize(m, (w0, h0), interpolation=cv2.INTER_LINEAR)
                gray = cv2.cvtColor(base.astype(np.uint8),
                                    cv2.COLOR_BGR2GRAY).astype(np.float32)
                s = (BLUE_W * self.blue_w * np.clip(alpha, 0.0, 1.0))[..., None]
                base += s * (gray[..., None] - base)
                out = np.clip(base, 0, 255).astype(np.uint8)

        return out if out is not None else frame


def run(src: str, dst: str = None, tier: str = "t5", width: int = 320,
        verbose: bool = True):
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise IOError(src)
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps != fps or fps <= 0 or fps > 240:
        fps = 30.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cl = ChromaLimiter(fps, tier=tier, analysis_w=width)
    q = None
    if dst:
        q = subprocess.Popen(
            ["ffmpeg", "-y", "-v", "error",
             "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
             "-r", str(fps), "-i", "-", "-i", src,
             "-map", "0:v:0", "-map", "1:a:0?", "-c:a", "copy",
             "-c:v", "libx264", "-preset", "medium", "-crf", "16",
             "-pix_fmt", "yuv420p", dst], stdin=subprocess.PIPE)
    while True:
        ok, f = cap.read()
        if not ok:
            break
        g = cl.process(f)
        if q:
            q.stdin.write(np.ascontiguousarray(g).tobytes())
    cap.release()
    if q:
        q.stdin.close()
        q.wait()
    touched = cl.stats["step_limited"] + cl.stats["blue_frames"]
    if dst and touched == 0:
        tmp = dst + ".copy" + os.path.splitext(dst)[1]
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src,
                            "-c", "copy", tmp])
        if r.returncode == 0:
            os.replace(tmp, dst)
        elif os.path.exists(tmp):
            os.remove(tmp)
    rep = dict(cl.stats)
    rep["tier"] = tier
    if verbose:
        print(f"프레임 {rep['frames']}  스텝제한 {rep['step_limited']}  "
              f"청색감쇠 {rep['blue_frames']}  컷 {rep['cuts']}  "
              f"최대스텝 {rep['max_step']:.3f}  최대시프트 {rep['max_shift']:.1f}")
    return rep


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="M2 색상 작동기 (T4/T5 전용, 출력은 pse_bt1702 재판정 필수)")
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--tier", choices=["t4", "t5"], default="t5")
    ap.add_argument("--width", type=int, default=320)
    a = ap.parse_args()
    run(a.src, a.dst, tier=a.tier, width=a.width)
