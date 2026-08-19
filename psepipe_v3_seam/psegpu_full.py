# -*- coding: utf-8 -*-
"""
psegpu_full.py — **전부 GPU.** 검출·움직임·컷 판정까지 올렸다.

왜 여기까지 왔나
================================================================================
4090 Laptop 실측(psegpu, 적용부만 GPU):

    1920x1080   합계 15.47 ms = 64.7 fps
                축소 1.65 | 검출CPU 4.07 | 적용GPU 9.75

적용부를 아무리 깎아도 **CPU 5.7 ms 가 바닥으로 남는다.** 그리고 프레임마다
GPU 결과를 기다렸다가(sync) CPU 로 내려서 검출하고 다시 올리므로,
비동기 실행의 이점도 대부분 잃는다.

그래서 전부 GPU 로 옮긴다. 프레임당 호스트 동기화가 **딱 한 번**(마지막 다운로드)
뿐이고, 그 사이 모든 것이 GPU 에 상주한다.

    업로드 uint8 -> [축소 · EOTF · 검출 · 마스크 · 움직임 · 적용] -> 다운로드 uint8
                     └─────────── 전부 GPU, 동기화 없음 ───────────┘

데이터 의존 분기를 없앤 방법
--------------------------------------------------------------------------------
`if cut:` / `if 움직임:` 같은 호스트 분기는 GPU 결과를 기다려야 해서 동기화를 만든다.
CUDA Graph 캡처도 불가능해진다. 그래서 **분기를 GPU 스칼라 게이트로 바꿨다.**

    prev = cut·lin + (1-cut)·warp(prev)          # 컷이면 리셋, 아니면 워프
    out  = cut·lin + (1-cut)·filtered            # 컷 프레임은 원본 통과

워프는 매 프레임 돌린다(1080p 약 1 ms). 게이트를 호스트로 내려 분기하면
동기화 비용이 그보다 크다.

위상상관을 직접 구현한 이유 — **14번 버그의 근본 해결**
--------------------------------------------------------------------------------
`cv2.phaseCorrelate` 는 주기 패턴(줄무늬)에서 다봉이라 아무 봉우리나 잡는다.
14번 클립에서 응답 0.003 인데도 ±190px 씩 워프했고, OpenCV 4.13 과 5.0 이
서로 다른 결과를 냈다(제 환경 PASS, 4090 환경 FAIL).

여기서는 응답값 대신 **봉우리 비(peak ratio)** 로 거른다.
  · 최고 봉우리 / (반경 밖 두 번째 봉우리)
  · 주기 패턴은 봉우리가 여러 개라 비가 1 에 가깝다 -> 기각
  · 진짜 평행이동은 봉우리 하나가 압도한다 -> 채택
OpenCV 버전과 무관하게 같은 판단을 한다.

**주의: GPU 없는 환경에서 작성했다. 실행 검증 안 됨.**
verify_full.py 로 CPU 기준판과 대조한 뒤에 쓸 것.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from dataclasses import dataclass

import cv2
import numpy as np

import psecore as PC
import pseenv as ENV
import pselive3 as P3

import torch
import torch.nn.functional as F

__version__ = "1.0.0"


# ══════════════════════════════════════════════════════════════════════════════
# 기본 연산
# ══════════════════════════════════════════════════════════════════════════════

def srgb_eotf(u8: torch.Tensor, dt) -> torch.Tensor:
    x = u8.to(dt) / 255.0
    return torch.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055).pow(2.4))


def gauss1d(sigma: float, device, dt) -> torch.Tensor:
    k = (int(round(sigma * 4.0)) * 2 + 1) | 1          # OpenCV ksize=0 규칙
    x = torch.arange(k, device=device, dtype=dt) - (k - 1) / 2.0
    w = torch.exp(-(x * x) / (2.0 * sigma * sigma))
    return w / w.sum()


def blur(x: torch.Tensor, k1d: torch.Tensor) -> torch.Tensor:
    c = x.shape[1]
    k = k1d.numel()
    p = k // 2
    y = F.conv2d(F.pad(x, (0, 0, p, p), mode="reflect"),
                 k1d.view(1, 1, k, 1).expand(c, 1, k, 1), groups=c)
    return F.conv2d(F.pad(y, (p, p, 0, 0), mode="reflect"),
                    k1d.view(1, 1, 1, k).expand(c, 1, 1, k), groups=c)


def dilate_cross3(m: torch.Tensor) -> torch.Tensor:
    p = F.pad(m, (1, 1, 1, 1), mode="replicate")
    return torch.maximum(
        torch.maximum(p[:, :, 1:-1, 1:-1], p[:, :, :-2, 1:-1]),
        torch.maximum(torch.maximum(p[:, :, 2:, 1:-1], p[:, :, 1:-1, :-2]),
                      p[:, :, 1:-1, 2:]))


def max_box_frac(m: torch.Tensor, w: int) -> torch.Tensor:
    """모든 w×w 창 중 최대 점유율. psecore.area_wcag 와 같은 정의(적분영상)."""
    s = m.to(torch.float32).cumsum(-1).cumsum(-2)
    s = F.pad(s, (1, 0, 1, 0))
    box = s[..., w:, w:] - s[..., :-w, w:] - s[..., w:, :-w] + s[..., :-w, :-w]
    return box.amax() / float(w * w)


# ══════════════════════════════════════════════════════════════════════════════
# 검출기 — psecore 의 torch 판
# ══════════════════════════════════════════════════════════════════════════════

class TPeakValley:
    """psecore.PeakValley 와 같은 정의. 링 안 극값 대비 전환, 극성 교번."""

    def __init__(self, shape, n_lookback, theta, device, dt):
        self.n = max(1, int(n_lookback))
        self.theta = float(theta)
        self.pol = torch.zeros(shape, dtype=torch.int8, device=device)
        self.ring: list[torch.Tensor] = []
        self.dt = dt

    def step(self, X, theta_dark, michelson):
        if not self.ring:
            self.ring.append(X.clone())
            z = torch.zeros_like(X, dtype=torch.bool)
            return z, z.clone()
        lmax = self.ring[0]
        lmin = self.ring[0]
        for r in self.ring[1:]:
            lmax = torch.maximum(lmax, r)
            lmin = torch.minimum(lmin, r)
        d_down = lmax - X
        d_up = X - lmin

        def qual(hi, lo):
            return (lo < theta_dark) | (((hi - lo) / (hi + lo).clamp_min(1e-6))
                                        > michelson)

        down = (d_down >= self.theta) & qual(lmax, X) & (self.pol != -1)
        up = (d_up >= self.theta) & qual(X, lmin) & (self.pol != 1)
        both = down & up
        pd = d_down >= d_up
        down = down & ~(both & ~pd)
        up = up & ~(both & pd)
        self.pol = torch.where(down, torch.tensor(-1, dtype=torch.int8,
                                                  device=X.device),
                               torch.where(up, torch.tensor(1, dtype=torch.int8,
                                                            device=X.device),
                                           self.pol))
        self.ring.append(X.clone())
        if len(self.ring) > self.n:
            self.ring.pop(0)
        # 순 방향성 관문(Cfg.net_directional)이 하강분을 쓴다. CPU 판의
        # PeakValley 는 (up, delta, down|up) 을 주는데 여기서는 (up, down) 으로
        # 직접 돌려준다 — down 은 both 해소 뒤라 up 과 서로소다.
        return up, down


class TFlashCounter:
    """gap 을 안 쓰는 사용처(gap=1e9, counts(False))라 링 합만 유지하면 된다."""

    def __init__(self, shape, window_frames, device):
        self.wf = max(1, int(window_frames))
        self.win = torch.zeros(shape, dtype=torch.int16, device=device)
        self.ring: list[torch.Tensor] = []

    def push(self, flash):
        f = flash.to(torch.int16)
        self.win += f
        self.ring.append(f)
        if len(self.ring) > self.wf:
            self.win -= self.ring.pop(0)

    def counts(self):
        return self.win


# ══════════════════════════════════════════════════════════════════════════════
# 위상상관 — 봉우리 비로 신뢰도를 판단한다
# ══════════════════════════════════════════════════════════════════════════════

def phase_corr(a: torch.Tensor, b: torch.Tensor, excl: int = 3):
    """a -> b 로의 전역 평행이동 추정. (dx, dy, peak_ratio) 를 **GPU 스칼라**로 반환.

    수학:
        b(x) = a(x - t)  ->  A·conj(B) 정규화의 역변환이 x = -t 에서 봉우리.
        따라서 t = -(부호 있는 봉우리 위치).

    peak_ratio = 최고봉 / (반경 excl 밖 최고봉).
    주기 패턴은 봉우리가 여러 개라 1 에 가깝다 -> 신뢰 못 함.
    """
    H, W = a.shape[-2:]
    A = torch.fft.rfft2(a.float())
    B = torch.fft.rfft2(b.float())
    R = A * B.conj()
    R = R / R.abs().clamp_min(1e-12)
    c = torch.fft.irfft2(R, s=(H, W))

    flat = c.reshape(-1)
    idx = torch.argmax(flat)
    py = torch.div(idx, W, rounding_mode="floor")
    px = idx - py * W
    peak = flat[idx]

    # 두 번째 봉우리 (반경 excl 밖)
    yy = torch.arange(H, device=a.device).view(-1, 1)
    xx = torch.arange(W, device=a.device).view(1, -1)
    dy_ = torch.minimum((yy - py).abs(), H - (yy - py).abs())
    dx_ = torch.minimum((xx - px).abs(), W - (xx - px).abs())
    far = (dy_ > excl) | (dx_ > excl)
    second = torch.where(far, c, torch.full_like(c, -1e30)).amax()
    ratio = peak / second.clamp_min(1e-12)

    # 부화소 — 축별 3점 포물선
    def sub(center, axis_len, get):
        m1, p1 = get(-1), get(1)
        den = (m1 - 2 * peak + p1)
        return torch.where(den.abs() < 1e-12, torch.zeros_like(den),
                           0.5 * (m1 - p1) / den)

    cy = sub(py, H, lambda o: c[(py + o) % H, px])
    cx = sub(px, W, lambda o: c[py, (px + o) % W])

    fx = px.to(torch.float32) + cx
    fy = py.to(torch.float32) + cy
    fx = torch.where(fx > W / 2, fx - W, fx)
    fy = torch.where(fy > H / 2, fy - H, fy)
    return -fx, -fy, ratio          # t = -(부호 있는 봉우리 위치)


def translate_gpu(x, dx, dy, gate):
    """dx,dy,gate 가 **GPU 텐서**라 호스트 동기화가 없다. gate=0 이면 항등."""
    n, c, h, w = x.shape
    zero = torch.zeros((), device=x.device, dtype=torch.float32)
    one = torch.ones((), device=x.device, dtype=torch.float32)
    tx = -2.0 * (dx * gate) / max(w - 1, 1)
    ty = -2.0 * (dy * gate) / max(h - 1, 1)
    theta = torch.stack([torch.stack([one, zero, tx]),
                         torch.stack([zero, one, ty])]).unsqueeze(0)
    grid = F.affine_grid(theta.to(x.dtype), (n, c, h, w), align_corners=True)
    return F.grid_sample(x, grid, mode="bilinear", padding_mode="border",
                         align_corners=True)


def block_flow(prev_g, cur_g, radius: int, step: int, block: int, min_gain: float):
    """블록매칭 국소 움직임장. (dx, dy) 를 분석 해상도 맵으로 돌려준다.

    전역 평행이동 워프는 화면 전체가 같이 움직일 때만 맞다. 배경은 고정인데
    사람만 움직이면 그 움직임이 보상되지 않고 슬루 제한에 걸려 **잔상**이 된다.
    여기서 국소 벡터를 구해 prev 를 화소별로 끌어오면
        d = lin - warp_local(prev)
    에서 움직임 성분이 상쇄되고 점멸 성분만 남는다.

    호스트 동기화가 없어야 하므로 후보 변위를 전부 쌓아 argmin 을 취한다.
    **잘못된 벡터는 잔상보다 나쁜 아티팩트를 만든다.** 그래서 무변위 대비
    SAD 가 min_gain 이상 좋아진 블록만 채택하고 나머지는 0 으로 둔다.
    """
    h, w = prev_g.shape
    p = prev_g.view(1, 1, h, w)
    c = cur_g.view(1, 1, h, w)
    offs = list(range(-radius, radius + 1, step))
    costs, vecs = [], []
    for dy in offs:
        for dx in offs:
            sh = torch.roll(p, shifts=(dy, dx), dims=(2, 3))
            sad = F.avg_pool2d((c - sh).abs(), block, stride=block)
            costs.append(sad)
            vecs.append((dx, dy))
    C = torch.cat(costs, dim=1)                     # (1, K, hb, wb)
    best = C.argmin(dim=1, keepdim=True)
    zero_i = vecs.index((0, 0))
    cost_zero = C[:, zero_i:zero_i + 1]
    cost_best = C.gather(1, best)
    # 무변위보다 뚜렷하게 좋을 때만 신뢰한다
    ok = (cost_best < cost_zero * (1.0 - min_gain)).to(prev_g.dtype)

    dxs = torch.tensor([v[0] for v in vecs], device=prev_g.device,
                       dtype=prev_g.dtype)
    dys = torch.tensor([v[1] for v in vecs], device=prev_g.device,
                       dtype=prev_g.dtype)
    fx = dxs[best.squeeze(1)].unsqueeze(1) * ok
    fy = dys[best.squeeze(1)].unsqueeze(1) * ok
    fx = F.interpolate(fx, size=(h, w), mode="bilinear", align_corners=False)
    fy = F.interpolate(fy, size=(h, w), mode="bilinear", align_corners=False)
    return fx, fy


def warp_flow(x, fx, fy):
    """화소별 (fx, fy) 만큼 x 를 끌어온다. fx/fy 는 x 와 같은 해상도로 맞춰진다."""
    n, c, h, w = x.shape
    if fx.shape[-2:] != (h, w):
        fx = F.interpolate(fx, size=(h, w), mode="bilinear", align_corners=False)
        fy = F.interpolate(fy, size=(h, w), mode="bilinear", align_corners=False)
    ys, xs = torch.meshgrid(
        torch.arange(h, device=x.device, dtype=x.dtype),
        torch.arange(w, device=x.device, dtype=x.dtype), indexing="ij")
    gx = (xs.view(1, 1, h, w) - fx) / max(w - 1, 1) * 2.0 - 1.0
    gy = (ys.view(1, 1, h, w) - fy) / max(h - 1, 1) * 2.0 - 1.0
    grid = torch.cat([gx, gy], dim=1).permute(0, 2, 3, 1)
    return F.grid_sample(x, grid, mode="bilinear", padding_mode="border",
                         align_corners=True)


# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class OptF:
    half: bool = False
    peak_ratio_min: float = 1.35    # 이 아래면 '봉우리가 여럿' -> 워프하지 않는다
    guard: bool = False             # **미구현 플래그** — GPU 판에는 자기감시
                                    # 가드가 이식돼 있지 않다 (읽는 코드 없음).
                                    # CPU 판(pselive3._guard)은 2026-08-19 에
                                    # "입력 대규모 위반 구간에서는 후퇴 금지"
                                    # 조건이 붙었다 — GPU 이식 시 그 형태로 옮길 것.
                                    # cera 재인코딩본에서 무조건 가드가 개입을
                                    # 통째로 붕괴시킨 실측이 근거다.
    graph: bool = False


class FullFilterGPU:
    def __init__(self, fps, full_hw, cfg: P3.Cfg = None, opt: OptF = None,
                 device="cuda"):
        self.c = c = cfg or P3.Cfg()
        self.o = o = opt or OptF()
        self.dev = torch.device(device)
        self.dt = torch.float16 if o.half else torch.float32
        self.H, self.W = full_hw
        s = c.short_side / min(self.H, self.W) if min(self.H, self.W) > c.short_side else 1.0
        self.aw = max(2, int(self.W * s))
        self.ah = max(2, int(self.H * s))

        self.n_look = max(1, int(round(c.T_qualify_ms / (1000.0 / fps))))
        self.S = float(c.slew_frac) if c.slew_frac > 0 else \
            c.slew_safety * c.theta_lum / max(1, self.n_look)
        self.win_px = PC.wcag_window_px(self.aw, self.ah,
                                        PC.Cfg().wcag_field_deg, PC.Cfg().fov_h_deg)
        sh = (self.ah, self.aw)
        self.pv = [TPeakValley(sh, self.n_look, c.theta_lum, self.dev, self.dt)
                   for _ in range(3)]
        self.ctr = [TFlashCounter(sh, max(1, int(round(fps))), self.dev)
                    for _ in range(3)]
        self.hold = torch.zeros(sh, dtype=torch.int32, device=self.dev)
        self.hold_n = max(1, int(round(c.hold_s * fps)))

        self.k_det = gauss1d(c.detail_sigma, self.dev, self.dt) if c.detail_sigma > 0 else None
        self.k_fea = gauss1d(c.feather_px, self.dev, self.dt) if c.feather_px > 0 else None
        self.wY = torch.tensor([0.0722, 0.7152, 0.2126],
                               device=self.dev, dtype=self.dt).view(1, 3, 1, 1)
        # 컷 판정용 — cv2.COLOR_BGR2GRAY 와 같은 Rec.601 가중치 (BGR 순서)
        self.w601 = torch.tensor([0.114, 0.587, 0.299],
                                 device=self.dev, dtype=self.dt)
        self.OETF = torch.from_numpy(np.ascontiguousarray(P3._build_oetf())).to(self.dev)

        self.prev = None
        self.alpha_prev = torch.zeros((1, 1, self.ah, self.aw), dtype=self.dt,
                                      device=self.dev)
        self.prev_gray = None
        self.prev_ncc = None
        self.prev_flat = torch.ones((), device=self.dev, dtype=self.dt)
        self.cut_gap_n = float(max(0, int(round(c.cut_min_gap_s * fps))))
        self.since_cut = torch.full((), 1e9, device=self.dev, dtype=self.dt)
        self.n = 0
        self.stats = {"armed": 0, "warped": 0.0, "cuts": 0.0, "mean_area": 0.0,
                      "lmc_px": 0.0}

        self.h_in = torch.empty((self.H, self.W, 3), dtype=torch.uint8, pin_memory=True)
        self.h_out = torch.empty((self.H, self.W, 3), dtype=torch.uint8, pin_memory=True)
        self.d_in = torch.empty((self.H, self.W, 3), dtype=torch.uint8, device=self.dev)

    # ------------------------------------------------------------------
    def _detect(self, lin_s):
        """분석 해상도 선형광 (1,3,h,w) -> (마스크 α 원본, 위험면적)."""
        c = self.c
        hot = None
        ups, dns = [], []                     # 채널별 상승/하강 (순방향 관문용)
        for ch in range(3):
            X = lin_s[0, ch]
            f, dn = self.pv[ch].step(X, c.theta_dark, c.michelson)
            ups.append(f); dns.append(dn)
            self.ctr[ch].push(f)
            h = self.ctr[ch].counts() >= int(c.arm_count)
            hot = h if hot is None else (hot | h)
        # 면적 규칙 — 표준이 위험하다고 하는 곳에만 손댄다
        if c.arm_area > 0:
            a_hot = max_box_frac(hot.view(1, 1, self.ah, self.aw), self.win_px)
            hot = hot & (a_hot >= c.arm_area)
        # **순 방향성 관문** (seunghoon 브랜치에서 가져옴 — Cfg.net_directional)
        # 화소 단위로는 팬과 플래시가 구분되지 않는다. 팬은 한쪽에서 밝은 것이
        # 들어오고 반대쪽으로 나가므로 up 과 dn 면적이 맞먹어 상쇄된다
        # (pse_bt1702 실측 0.239/0.237 -> 0.089). 진짜 점멸은 한 방향이
        # 압도한다(1.000). 심판이 쓰는 그 관문을 필터에도 건다.
        # 순방향은 **채널별로 재서 최댓값** — CPU 판(pselive3._mask)과 같은
        # 이유: 채널 OR 로 재면 등휘도 색 점멸(같은 화소 R↑·B↓)이 상쇄돼
        # 관문이 닫히고 합성 06/07 의 적색 위반이 잔존한다. 비용은 box 필터
        # 2회 -> 6회지만 net_directional 을 켠 경우에만 든다.
        if c.net_directional:
            net = None
            for u, d in zip(ups, dns):
                au = max_box_frac(u.view(1, 1, self.ah, self.aw), self.win_px)
                ad = max_box_frac(d.view(1, 1, self.ah, self.aw), self.win_px)
                n = (au - ad).abs()
                net = n if net is None else torch.maximum(net, n)
            hot = hot & (net >= c.arm_area)
        self.hold = torch.where(hot, torch.full_like(self.hold, self.hold_n),
                                (self.hold - 1).clamp_min(0))
        return (self.hold > 0)

    def _cut_gate(self, gray8):
        """1 이면 컷. 호스트 분기 없이 스칼라 텐서로 돌려준다.

        CPU 기준판(pselive3._is_cut)은 **감마 부호화된 8비트 그레이**에서 잰다.
        여기서 선형광 루마로 재던 것이 22번(게임 HUD)·seg6 판정 불일치의 원인이었다.
        감마는 비선형이라 `/255` 환산으로는 못 메운다 — NCC 값 자체가 달라진다.
        선형광에서는 밝은 프레임의 분산이 과장돼 연속 프레임 상관이 실제보다
        낮게 나오고, 그래서 임계 0.45 에 컷이 과검출됐다(22번 55회). 컷마다
        `prev` 가 리셋되니 시간축 평활이 누적되지 않아 출력이 원본과 같아졌다.

        그래서 CPU 와 같은 도메인에서 잰다: 입력 uint8 BGR 에 Rec.601 가중치
        (cv2.COLOR_BGR2GRAY 와 동일), 0~255 스케일. 이제 `cut_thresh` 0.45 와
        `flat_sd` 6.0 이 CPU 와 같은 뜻이 된다.
        """
        c = self.c
        g = F.interpolate(gray8.view(1, 1, self.H, self.W), size=(64, 64),
                          mode="area").view(64, 64)
        g = g - g.mean()
        sd = g.std()
        flat = (sd < c.flat_sd).to(self.dt)               # CPU 와 같은 8비트 스케일
        # CPU 는 sd 가 너무 작으면 gn 을 0 으로 둔다. 그대로 맞춘다.
        gn = torch.where(sd > 1e-3, g / sd.clamp_min(1e-6), torch.zeros_like(g))
        if self.prev_ncc is None:
            cut = torch.zeros((), device=self.dev, dtype=self.dt)
        else:
            ncc = (gn * self.prev_ncc).mean()
            valid = (1.0 - flat) * (1.0 - self.prev_flat)
            cut = ((ncc < c.cut_thresh).to(self.dt)) * valid
        # 불응기 — 컷 직후 cut_gap_n 프레임은 컷을 인정하지 않는다.
        # (Cfg.cut_min_gap_s 주석 참고) 호스트 분기 없이 스칼라 텐서로 센다.
        allowed = (self.since_cut >= self.cut_gap_n).to(self.dt)
        cut = cut * allowed
        self.since_cut = (1.0 - cut) * (self.since_cut + 1.0)
        self.prev_ncc = gn
        self.prev_flat = flat
        return cut

    # ------------------------------------------------------------------
    def push(self, bgr: np.ndarray) -> np.ndarray:
        self.h_in.copy_(torch.from_numpy(np.ascontiguousarray(bgr)))
        self.d_in.copy_(self.h_in, non_blocking=True)
        out = self._step()
        self.h_out.copy_(out, non_blocking=True)
        torch.cuda.synchronize()                    # 프레임당 유일한 동기화
        return self.h_out.numpy().copy()

    # ------------------------------------------------------------------
    def _step(self):
        c = self.c
        dt = self.dt
        # 감마 부호화 0~1. 선형광과 컷 판정용 그레이가 **둘 다** 여기서 나온다 —
        # uint8->float 전해상도 변환을 두 번 하지 않으려고 중간값을 붙잡아 둔다.
        xe = self.d_in.to(dt) / 255.0
        xe3 = xe.permute(2, 0, 1).unsqueeze(0)
        lin = torch.where(xe3 <= 0.04045, xe3 / 12.92, ((xe3 + 0.055) / 1.055).pow(2.4))

        # 검출 입력은 CPU 기준판 경로를 그대로 재현한다:
        #     bgr_small = cv2.resize(bgr, INTER_AREA)   ->  PC._LIN[bgr_small]
        # 즉 **감마 도메인에서 축소한 뒤 선형화**한다. 여기서 순서를 바꾸면
        # (선형화 후 축소) 밝은 줄무늬 에너지가 더 남아 값이 커진다.
        #
        # 더 중요한 건 리샘플러다. torch 의 mode="area" 는 adaptive_avg_pool2d 라
        # **정수 경계**로 구간을 나누는데, cv2.INTER_AREA 는 0.75 배 같은 비정수
        # 배율에서 **분수 가중치**로 면적평균을 낸다. 고대비 줄무늬(14번)에서
        # 화소별 오차가 임계 theta_lum(0.10)의 2~3 배까지 벌어졌다.
        # 14번 f0 기준 CPU 대비 오차 (임계 0.10 을 넘는 화소 비율):
        #     선형 area 0.284 (3.75%) / 감마 area 0.214 (6.67%)
        #     감마 bicubic+AA 0.054 (0.00%)  <- 채택
        # 그 오차가 검출 마스크를 0.750 -> 0.875 로 부풀렸고, 안전한 원본을
        # 위반으로 만드는 데까지 갔다.
        xe_s = F.interpolate(xe3, size=(self.ah, self.aw), mode="bicubic",
                             align_corners=False, antialias=True).clamp(0, 1)
        xe_s = torch.round(xe_s * 255.0) / 255.0     # CPU 는 uint8 을 거친다
        lin_s = torch.where(xe_s <= 0.04045, xe_s / 12.92,
                            ((xe_s + 0.055) / 1.055).pow(2.4))
        gray_s = (lin_s * self.wY).sum(1, keepdim=True)[0, 0]

        # 컷 판정만 감마 도메인에서 (CPU 기준판과 같은 자). _cut_gate 주석 참고.
        cut = self._cut_gate((xe * self.w601).sum(-1) * 255.0)
        M = self._detect(lin_s)
        self.n += 1
        self.stats["mean_area"] += float(M.float().mean())

        # ---- 알파
        a = M.to(dt).view(1, 1, self.ah, self.aw)
        if c.dilate_px == 3:
            a = dilate_cross3(a)
        elif c.dilate_px > 0:
            k = int(c.dilate_px) | 1
            a = F.max_pool2d(a, k, stride=1, padding=k // 2)
        if self.k_fea is not None:
            a = blur(a, self.k_fea)
        a = a.clamp(0, 1) * float(np.clip(c.strength, 0, 1))

        # 국소 구조 게이트 — 움직임은 통과, 점멸만 누른다 (Cfg.coh_gate 주석 참고)
        #
        # 판별자는 **국소 정규화 상관(NCC)** 이다. 컷 게이트가 전역에서 하는 일을
        # 창 단위로 한다:
        #   플래시  밝기 레벨만 바뀌고 구조는 그대로  -> 정규화하면 상관 ~ 1
        #   움직임  구조 자체가 이동한다              -> 상관 낮음
        # 부호 일관성(sign(Δ) 평균)으로 먼저 해봤는데 실패했다 — 공간적으로
        # 복잡한 점멸을 움직임으로 오인해 제거율이 92.8% -> 60.0% 로 무너졌다
        # (TXeDgXiytM0 99%->0%, Y76O5wY7EcM 65%->0%).
        if c.coh_gate > 0 and self.prev_gray is not None:
            k = int(c.coh_win) | 1
            cur = gray_s.view(1, 1, self.ah, self.aw)
            pre = self.prev_gray.view(1, 1, self.ah, self.aw)

            def box(x):
                return F.avg_pool2d(x, k, stride=1, padding=k // 2)

            mc, mp = box(cur), box(pre)
            vc = (box(cur * cur) - mc * mc).clamp_min(1e-8)
            vp = (box(pre * pre) - mp * mp).clamp_min(1e-8)
            cov = box(cur * pre) - mc * mp
            ncc = (cov / (vc.sqrt() * vp.sqrt())).clamp(0.0, 1.0)
            a = a * (1.0 - c.coh_gate * (1.0 - ncc))

        a = (1 - c.alpha_smooth) * self.alpha_prev + c.alpha_smooth * a
        self.alpha_prev = a
        A = F.interpolate(a, size=(self.H, self.W), mode="bilinear",
                          align_corners=False)

        if self.prev is None:
            self.prev = lin
            self.prev_gray = gray_s
            return self.d_in

        # ---- 움직임 (봉우리 비로 게이트, 호스트 동기화 없음)
        if c.motion_comp:
            dx, dy, ratio = phase_corr(self.prev_gray, gray_s)
            sc = self.W / float(self.aw)
            ok = ((ratio > self.o.peak_ratio_min)
                  & (dx.abs() * sc < c.motion_max_px)
                  & (dy.abs() * sc < c.motion_max_px)
                  & ((dx.abs() > 0.5) | (dy.abs() > 0.5))).to(torch.float32)
            self.stats["warped"] += float(ok)
            prevw = translate_gpu(self.prev, dx * sc, dy * sc, ok)
        else:
            prevw = self.prev

        # ---- 국소 움직임 보상 (Cfg.local_mc 주석 참고)
        # 전역 워프 뒤에 남은 **국소** 움직임을 블록매칭으로 마저 걷어낸다.
        # d 에서 움직임이 빠지면 슬루 제한이 점멸 성분에만 걸려 잔상이 준다.
        if c.local_mc:
            pg = self.prev_gray
            fx, fy = block_flow(pg, gray_s, int(c.lmc_radius), int(c.lmc_step),
                                int(c.lmc_block), float(c.lmc_min_gain))
            sc2 = self.W / float(self.aw)
            prevw = warp_flow(prevw, fx * sc2, fy * sc2)
            self.stats["lmc_px"] += float((fx.abs() + fy.abs()).mean())

        self.prev_gray = gray_s

        # ---- 컷이면 리셋 (분기 대신 게이트)
        cg = cut.to(dt)
        self.stats["cuts"] += float(cg)
        base = cg * lin + (1.0 - cg) * prevw

        # ---- 변화 벡터를 스칼라 하나로
        d = lin - base
        dY = (d * self.wY).sum(1, keepdim=True)
        mchr = (d - dY).abs().amax(1, keepdim=True)
        kmax = torch.minimum(
            torch.clamp(self.S / dY.abs().clamp_min(1e-6), max=1.0),
            c.slew_chroma / mchr.clamp_min(1e-6))
        out = torch.clamp(base + (A * kmax + (1.0 - A)) * d, 0.0, 1.0)

        # ---- 질감 복원 (휘도만, 알파 안쪽만)
        if self.k_det is not None:
            Yo = (out * self.wY).sum(1, keepdim=True)
            Yi = (lin * self.wY).sum(1, keepdim=True)
            tex = torch.clamp(Yi / blur(Yi, self.k_det).clamp_min(1e-4), 0.25, 4.0)
            Yt = blur(Yo, self.k_det) * tex
            det = torch.clamp(out * (Yt / Yo.clamp_min(1e-4)), 0.0, 1.0)
            out = A * det + (1.0 - A) * out

        # 컷 프레임은 원본 그대로 통과
        out = cg * lin + (1.0 - cg) * out
        self.prev = out

        idx = (out * (self.OETF.numel() - 1)).clamp(0, self.OETF.numel() - 1).long()
        return self.OETF[idx].squeeze(0).permute(1, 2, 0).contiguous()



NVENC = None          # None = 자동 감지. True/False 로 강제 가능


def _has_nvenc():
    global NVENC
    if NVENC is None:
        import subprocess
        try:
            r = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                               capture_output=True, text=True, timeout=20,
                               errors="replace")
            NVENC = "h264_nvenc" in (r.stdout or "")
        except Exception:
            NVENC = False
    return NVENC


def _open_writer(path, src, W, H, fps, lossless):
    """**FFV1 은 MP4 컨테이너에 못 들어간다.** 확장자로 고른다.
        .mkv -> FFV1 무손실 (판정 측정용)
        그 외 -> H.264 mp4 (사람이 보는 용, 원본 오디오 통과)
    """
    import subprocess
    if lossless:
        if not path.lower().endswith(".mkv"):
            raise ValueError(f"무손실(FFV1)은 .mkv 로만 저장됩니다: {path}")
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
               "-r", str(fps), "-i", "-", "-c:v", "ffv1", "-level", "3",
               "-pix_fmt", "gbrp", path]
    else:
        # **인코딩도 GPU 로.** 긴 영상에서는 libx264(CPU) 가 필터보다 오래 걸린다.
        # 실측 환경에 h264_nvenc 가 있어서 기본으로 쓴다(없으면 자동으로 x264).
        #   cq 18 은 x264 crf 16 과 대략 같은 화질대.
        if _has_nvenc():
            venc = ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq",
                    "-rc", "vbr", "-cq", "18", "-b:v", "0"]
        else:
            venc = ["-c:v", "libx264", "-preset", "medium", "-crf", "16"]
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
               "-r", str(fps), "-i", "-",
               "-i", src, "-map", "0:v:0", "-map", "1:a:0?", "-c:a", "copy",
               "-shortest",
               "-sws_flags", "bicubic+accurate_rnd+full_chroma_int"] + venc + [
               "-pix_fmt", "yuv420p", "-colorspace", "bt709",
               "-color_primaries", "bt709", "-color_trc", "bt709",
               "-movflags", "+faststart", path]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


# ══════════════════════════════════════════════════════════════════════════════
def run(src, cfg: P3.Cfg = None, opt: OptF = None, video_out=None,
        lossless=None, device="auto", warmup=8, keep=None, progress=True):
    """keep=None 이면 자동 — video_out 이 있으면 프레임을 **모으지 않고 흘려보낸다.**

    긴 영상에서 터지지 않기 위한 것이다. 전에는 출력 프레임을 전부 리스트에
    쌓았는데, 1080p 3분짜리면 6.2MB x 4300프레임 = **27 GB** 라 OOM 이다.
    (6초 발췌로만 돌려서 여태 안 드러났다.)
    """
    cfg = cfg or P3.Cfg()
    opt = opt or OptF()
    device = ENV.pick_device(device)
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise IOError(src)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    live = FullFilterGPU(fps, (H, W), cfg, opt, device=device)

    if keep is None:
        keep = video_out is None
    ext = os.path.splitext(video_out)[1].lower() if video_out else ""
    use_ll = (lossless if lossless is not None else (ext == ".mkv")) if video_out else False

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    writer = None
    if video_out and not keep:
        writer = _open_writer(video_out, src, W, H, fps, use_ll)

    out, n, t = [], 0, 0.0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        g = live.push(f)
        torch.cuda.synchronize()
        if n >= warmup:
            t += time.perf_counter() - t0
        if writer is not None:
            writer.stdin.write(np.ascontiguousarray(g).tobytes())
        if keep:
            out.append(g)
        n += 1
        if progress and total > 400 and n % 200 == 0:
            el = t / max(1, n - warmup) * 1000
            print(f"    {n}/{total}  ({n/max(total,1)*100:4.1f}%)  {el:.2f} ms/frame",
                  flush=True)
    cap.release()
    if writer is not None:
        writer.stdin.close()
        writer.wait()
    m = max(1, n - warmup)
    ms = t / m * 1000
    rep = {"src": src, "res": f"{W}x{H}", "frames": n, "dtype": str(live.dt),
           "ms_per_frame": round(ms, 3), "max_fps": round(1000.0 / max(ms, 1e-9), 1),
           "realtime_x": round((1000.0 / fps) / max(ms, 1e-9), 2),
           "warped": int(live.stats["warped"]), "cuts": int(live.stats["cuts"]),
           "mean_mask_area": round(live.stats["mean_area"] / max(n, 1), 4),
           "latency_frames": 0}
    if video_out:
        if keep:                       # 모아 뒀으면 여기서 한 번에 쓴다
            w = _open_writer(video_out, src, W, H, fps, use_ll)
            for g in out:
                w.stdin.write(np.ascontiguousarray(g).tobytes())
            w.stdin.close()
            w.wait()
        rep["video_out"] = video_out
    return rep, out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--video", default=None)
    ap.add_argument("--half", action="store_true")
    ap.add_argument("--lossless", action="store_true",
                    help="FFV1 무손실로 저장 (.mkv 필요). 판정 측정용")
    ap.add_argument("--ratio", type=float, default=None,
                    help="봉우리 비 하한 (기본 1.35). 낮출수록 워프를 더 신뢰")
    ap.add_argument("--cut-thresh", type=float, default=None, help="컷 판정 NCC 임계. 낮출수록 컷을 덜 잡음")
    a = ap.parse_args()
    o = OptF(half=a.half)
    if a.ratio is not None:
        o.peak_ratio_min = a.ratio
    cfg = P3.Cfg()
    if a.cut_thresh is not None:
        # 예전에는 OptF 에 썼는데 _cut_gate 는 Cfg 를 읽어서 플래그가 무시됐다.
        cfg.cut_thresh = a.cut_thresh
    rep, _ = run(a.src, cfg, o, video_out=a.video,
                 lossless=True if a.lossless else None)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
