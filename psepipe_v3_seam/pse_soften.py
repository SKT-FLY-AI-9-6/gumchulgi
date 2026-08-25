# -*- coding: utf-8 -*-
"""pse_soften.py — 정적 패턴(줄무늬) 대비 감쇠 작동기   [편두통 고유 축, T4/T5 전용]

왜 필요한가
  T4 플래시 강화 실측(validation/tier_real3.csv)의 교훈: 플래시 공유축을
  조여도 콘텐츠의 편두통 부담이 다른 축(패턴·색·글레어)에서 오면 comfort
  선량이 안 내려간다(pinkvenom 0%). 통합 티어 표 v2 가 설계한 대로 T4/T5
  의 본체는 **고유 축 작동기**고, 이것이 그 첫 번째 — Wilkins 대역
  (1–4 cpd, 저대비 10%+) 정적 줄무늬의 Michelson 대비를 티어 임계 아래로
  낮춘다.

설계 원칙 (기존 경로와의 충돌 방지)
  · **독립 패스** — pselive3/psepipe 를 수정하지 않는다. 티어 필터 뒤에
    체인하는 별도 모듈이고, 출력은 반드시 pse_bt1702 재판정을 거친다.
  · **검출은 pse_migraine M1 과 같은 정의** — pse_pattern._dominant_freq
    (FFT 지배 주파수·방향 선택도) + dilate/erode 국소 극값 Michelson.
    두 코드가 다른 것을 재는 사고를 원천 차단.
  · **미검출이면 완전 항등** — 엔벨로프가 1 로 돌아오면 원본 프레임을
    바이트 그대로 내보낸다. detail_sigma 의 tex 클리핑이 "무개입인데
    항등이 깨져" 악화를 만든 판례(지뢰)를 반복하지 않기 위해서다.
  · **시간 엔벨로프** — 감쇠 강도 k 는 attack 0.3s / release 0.6s 일차
    완화로만 움직인다. 검출이 프레임마다 켜졌다 꺼졌다 해도 출력이
    펌핑(정지 화소 흔들림)하지 않는다. 정적 패턴이 대상이라 느려도 된다.

감쇠 방식 — 2층 분해 (결정론적)
  low  = G(σ=0.6·주기)   : 패턴보다 굵은 구조 (보존)
  out  = in − (1−k)·α·(in − low)
  k 는 측정 대비(마스크 내 p90)를 티어 임계×0.85 로 내리는 비율,
  α 는 패턴 화소 마스크(페더링·lit 게이트 포함). 패턴 주기 이상(以上)의
  전 대역을 k 배 하므로 마스크 안의 미세 질감도 함께 부드러워진다 —
  3층(band 만 감쇠)을 먼저 시도했으나 1–4cpd 의 주기가 화소 단위로
  작아(3cpd@360px ≈ 4.8px) 가우시안 전달률 때문에 감쇠가 26% 에
  그쳤다(실측). 정적 줄무늬 영역의 미세 질감 손실은 감수한다.

고조파 관문
  굵은 고대비 줄무늬(PSE 패턴 축, 예: 0.4cpd 10쌍)는 사각파 홀수
  고조파(3f, 5f…)가 1–4cpd 대역에 떨어져 오검출된다(합성 04/10 실측
  — 120/120 프레임 오개입). **전역 지배 주파수가 대역 하한보다 낮으면
  고조파로 보고 개입하지 않는다** — 그 영역은 작동기 B(PSE 패턴)의
  소관이다. pse_migraine M1 에도 같은 고조파 노출이 있다(팀 공유 사항).

한계 (정직)
  · 임계는 [가설]·[문헌] 등급 — 설문 검증 전까지 WARN 축과 같은 지위.
  · 콘텐츠의 합법적 줄무늬(옷·블라인드)도 부드러워진다 — T4/T5 를 켠
    민감 사용자에게만 적용하는 선택제 전제.
"""
from __future__ import annotations

import argparse
import subprocess
import sys

import cv2
import numpy as np

import pse_migraine as PM
import pse_pattern
from pse_bt1702 import luminance_cd

K_MIN = 0.15              # 감쇠 하한 (대비를 0 으로 만들지 않는다 — 구도 보존)
K_IDENTITY = 0.995        # 이보다 크면 완전 항등 passthrough
TARGET_FRAC = 0.85        # 목표 대비 = 티어 mich_min × 이 값 (임계 바로 아래 여유)
MASK_FRAC = 0.6           # 마스크 포함 문턱 = mich_min × 이 값
ATTACK_S = 0.3
RELEASE_S = 0.6


class Softener:
    def __init__(self, fps: float, tier: str = "t5",
                 view_deg: float = PM.VIEW_DEG, analysis_w: int = 320):
        self.p = PM.TIERS[tier]
        self.tier = tier
        self.view_deg = float(view_deg)
        self.aw = analysis_w
        self.k = 1.0
        self._a_att = 1.0 - float(np.exp(-1.0 / max(1.0, fps * ATTACK_S)))
        self._a_rel = 1.0 - float(np.exp(-1.0 / max(1.0, fps * RELEASE_S)))
        self.stats = {"frames": 0, "hit_frames": 0, "touched_frames": 0,
                      "k_min": 1.0, "mich_p90_max": 0.0}

    def process(self, frame: np.ndarray) -> np.ndarray:
        self.stats["frames"] += 1
        h0, w0 = frame.shape[:2]
        small = cv2.resize(frame, (self.aw, max(2, int(round(h0 * self.aw / w0)))),
                           interpolation=cv2.INTER_AREA)
        lum = luminance_cd(small, coherent=False)
        lit = lum >= PM.LUM_LIT_CD
        h, w = lum.shape
        f_lo = self.p["cpd_lo"] * self.view_deg
        f_hi = min(self.p["cpd_hi"] * self.view_deg, min(h, w) / 3.0)
        pairs, period_px, _theta, conc = pse_pattern._dominant_freq(
            lum, fmin=f_lo, fmax=max(f_lo + 1.0, f_hi))
        cpd = pairs / self.view_deg
        # 고조파 관문 (모듈 주석 참조): 전역 지배 주파수가 대역 하한 미만이면
        # 대역 내 성분은 굵은 줄무늬의 고조파다 — 개입하지 않는다.
        g_pairs, _, _, _ = pse_pattern._dominant_freq(
            lum, fmin=2.0, fmax=max(f_lo + 1.0, min(h, w) / 3.0))
        harmonic = g_pairs < f_lo * 0.9

        k_target, alpha_small, period = 1.0, None, float(period_px)
        if period_px > 1.5 and not harmonic:
            ksz = int(max(3, min(31, round(period_px) | 1)))
            ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksz, ksz))
            hi_bar = cv2.dilate(lum, ker)
            lo_bar = cv2.erode(lum, ker)
            mich = (hi_bar - lo_bar) / (hi_bar + lo_bar + 1e-6)
            core = (mich >= self.p["mich_min"]) & lit
            hit = (self.p["cpd_lo"] <= cpd <= self.p["cpd_hi"]) \
                and conc >= PM.CONC_MIN and float(core.mean()) >= PM.AREA_MIN
            if hit:
                self.stats["hit_frames"] += 1
                p90 = float(np.percentile(mich[core], 90))
                self.stats["mich_p90_max"] = max(self.stats["mich_p90_max"], p90)
                k_target = float(np.clip(self.p["mich_min"] * TARGET_FRAC
                                         / max(p90, 1e-6), K_MIN, 1.0))
                m = ((mich >= self.p["mich_min"] * MASK_FRAC) & lit).astype(np.float32)
                alpha_small = cv2.GaussianBlur(m, (0, 0), max(1.0, period_px))

        if self.stats["frames"] == 1:
            # 첫 프레임은 보호할 직전 출력이 없다 — 엔벨로프를 기다리면
            # 영상 첫 0.3s(attack) 동안 임계 초과 대비가 그대로 새어나간다
            # (합성 실측: WARN 잔존 0.7s 가 전부 이 과도구간이었다).
            self.k = k_target
        else:
            a = self._a_att if k_target < self.k else self._a_rel
            self.k += (k_target - self.k) * a
        self.stats["k_min"] = min(self.stats["k_min"], self.k)
        if self.k > K_IDENTITY or alpha_small is None:
            return frame                       # 완전 항등 — 원본 그대로

        self.stats["touched_frames"] += 1
        scale = w0 / float(self.aw)
        pf = max(2.0, period * scale)
        f32 = frame.astype(np.float32)
        low = cv2.GaussianBlur(f32, (0, 0), 0.6 * pf)
        alpha = cv2.resize(alpha_small, (w0, h0), interpolation=cv2.INTER_LINEAR)
        out = f32 - ((1.0 - self.k) * np.clip(alpha, 0.0, 1.0))[..., None] * (f32 - low)
        return np.clip(out, 0, 255).astype(np.uint8)


def run(src: str, dst: str = None, tier: str = "t5",
        view_deg: float = PM.VIEW_DEG, width: int = 320, verbose: bool = True):
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise IOError(src)
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps != fps or fps <= 0 or fps > 240:
        fps = 30.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    sf = Softener(fps, tier=tier, view_deg=view_deg, analysis_w=width)
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
        g = sf.process(f)
        if q:
            q.stdin.write(np.ascontiguousarray(g).tobytes())
    cap.release()
    if q:
        q.stdin.close()
        q.wait()
    if dst and sf.stats["touched_frames"] == 0:
        # 개입이 한 프레임도 없었으면 재인코딩 잡음조차 남기지 않는다 —
        # 원본을 스트림 카피로 교체 (완전 항등). 코덱이 컨테이너와 안 맞으면
        # (예: FFV1 -> .mp4) 조용히 파이프 출력(재인코딩본)을 유지한다.
        import os
        tmp = dst + ".copy" + os.path.splitext(dst)[1]
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src,
                            "-c", "copy", tmp])
        if r.returncode == 0:
            os.replace(tmp, dst)
        elif os.path.exists(tmp):
            os.remove(tmp)
    r = dict(sf.stats)
    r["tier"] = tier
    if verbose:
        print(f"프레임 {r['frames']}  패턴검출 {r['hit_frames']}  "
              f"개입 {r['touched_frames']}  k_min {r['k_min']:.3f}  "
              f"대비 p90 최대 {r['mich_p90_max']:.3f}")
    return r


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="정적 패턴 대비 감쇠 (편두통 T4/T5 전용, 출력은 pse_bt1702 재판정 필수)")
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--tier", choices=list(PM.TIERS), default="t5")
    ap.add_argument("--view-deg", type=float, default=PM.VIEW_DEG)
    ap.add_argument("--width", type=int, default=320)
    a = ap.parse_args()
    run(a.src, a.dst, tier=a.tier, view_deg=a.view_deg, width=a.width)
