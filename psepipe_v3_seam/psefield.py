# -*- coding: utf-8 -*-
"""
psefield.py — **오프라인 영위상 조명장 필터.**  v3.0

v2 에서 무엇이 바뀌었나 (전부 실측 근거)
================================================================================
1) **버터워스 filtfilt -> 대칭 Hann FIR.**
   filtfilt 는 영위상이지만 계단 입력에서 링잉(오버슈트)이 난다. 원본에 없던
   진동을 우리가 만들어 넣는 것이다 — genre/21(안전 계단 클립)이 0.00 -> 3.13s
   로 **나빠졌다**. 대칭 FIR 은 볼록결합이라 출력이 창의 [min,max] 를 절대
   못 벗어난다. 오버슈트가 구조적으로 불가능하다.
   실측(seg6): 위반 둘 다 0.00 PASS, 잔상 둘 다 0.017, **M_P 85.7(FIR) vs
   92.8(버터워스)** — FIR 이 연속 불편감 지표에서도 낫다.

2) **필요한 미래가 4프레임뿐이라는 것을 쟀다.**
       지연 1프레임  위반 6.21 FAIL   잔상 -0.005
       지연 2프레임  위반 6.46 FAIL   잔상  0.017
       **지연 4프레임(0.17초)  위반 0.00 PASS  잔상 0.017  M_P 85.7**
       지연 8프레임  위반 0.00 PASS   잔상 0.017  M_P 82.0
       오프라인 전체 위반 0.00 PASS   잔상 0.017  M_P 92.8
   4 는 튜닝값이 아니라 규격에서 나온다 — 초당 3회를 눌러야 하고 대칭 FIR 의
   지연은 반주기이므로  **지연 = 1/(2·fc) = 0.167초**.  24fps 면 4, 30fps 면 5.
   즉 이 구조는 원하면 0.17초 버퍼만으로 실시간에 그대로 옮길 수 있다.

3) **가산 항 도입.**  곱셈 게인은 0 인 채널을 못 들어올린다(exp(u)·0 = 0).
   검은 골짜기를 가진 색 스트로브가 그래서 안 잡혔다. 매끄럽고 거친 가산장을
   더한다 — 내용이 없으므로 잔상은 여전히 불가능하다.
       클립          a=0            a=0.05
       03 적녹등휘도  3.50 FAIL  ->  **0.00 PASS**
       04 청황등휘도  6.80 FAIL  ->  **0.00 PASS**
       08 적/흑      6.10 FAIL  ->  **0.00 PASS**
       09 적/회등휘도 6.50 FAIL  ->  **0.00 PASS**
       12 포리곤12Hz 13.80 FAIL ->  8.87 FAIL  (유일한 미해결)

4) **폐루프에서 FFV1 왕복을 없앴다.**  라운드마다 무손실로 쓰고 다시 디코드했다.
   실측 시간 분해(fein_orig 931프레임):
       판정 69.9% / 적용+무손실인코딩 18.1% / 수집 6.3% / 컷 5.7% / **필터 0.0%**
   이제 디코드->적용->분석해상도 축소를 한 번의 스트림으로 흘려서 psecore 에
   바로 먹인다. 인코딩도 재디코딩도 없고 메모리는 상수다. 판정은 **동일**하다
   (같은 uint8 프레임에 같은 INTER_AREA 축소를 쓰므로).
   **다만 이걸로도 빨라지는 건 18% 뿐이다.** 남은 벽은 psecore 판정 자체다 —
   931프레임 분석에 53.3s, 프로파일상 numpy reduce 16.0s / analyze 본문 8.2s /
   PeakValley 8.5s / 위상상관+워프 4.7s. 필터가 아니라 검출기가 병목이다.

5) **원본이 이미 PASS 면 손대지 않는다.** 보정 도구의 기본값이다.
   실측: 이 규칙이 없을 때 안전 클립 02 가 4.58dB, 11 이 4.77dB 바뀌었고
   14(흐르는 줄무늬)는 없던 잔상이 0.288 생겼다. 28 은 3.20 -> 3.20 으로
   개선 0 인데 6.22dB 를 바꿨다. --force 로 무시할 수 있다.

코퍼스 26편 (무손실 판정)
--------------------------------------------------------------------------------
    v2  21/26 PASS   (03/04/08/09/12 색 스트로브 실패)
    v3  **26/26 PASS**   안전 클립 9편은 전부 무손댐(게인편차 0.00dB)
    남은 흠: 23_letterbox 의 잔상 0.355 — 레터박스 검은 띠가 거친 조명장 셀을
             오염시킨다. 미해결.

v2 에서 이미 확립된 것 (요약)
--------------------------------------------------------------------------------
· **영위상**이라야 한다. v4 가 실패한 건 게인필드 구조가 아니라 인과 IIR 의 지연.
· **게인장은 거칠어야 한다.** 잘면 장 자체에 내용이 남아 그게 잔상이 된다.
      셀 2.8px -> 잔상 0.233 / 11.2px -> 0.108 / 16.9px -> 0.070 / 33.8px -> 0.018
· **점멸을 컷으로 오인하면 안 된다.** 조명정규화 + 이동탐색 NCC + 비인과 확인
  (t+1 에 내용이 돌아오면 컷이 아니라 섬광) + 계단형 컷 검출.
· 버린 것: BlazeBVD(STE, 6.34->9.71s 악화) / 광학흐름 정렬(왕복일관성 76%) /
  3프레임 시간중앙값(root signal 성질로 지속 스트로브 통과) / 아틀라스 재구성.

잔상이 구조적으로 불가능한 이유
--------------------------------------------------------------------------------
    out(x,t) = in(x,t)·g(x,t) + a(x,t)      g, a 는 공간·시간 저역
과거 프레임의 **화소값**이 out 에 나타날 경로가 식에 없다. g 나 a 가 틀리면
그 영역이 조금 밝거나 어두울 뿐, 두 겹으로 보이지 않는다.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from dataclasses import dataclass, replace

import cv2
import numpy as np

import psecore as PC

__version__ = "3.1.0"

# **전달함수는 심판과 같은 것을 써야 한다.**  pse_bt1702 는 감마 2.4(BT.1886),
# psecore 는 sRGB 구간함수를 쓴다. 어두운 쪽에서 값이 달라(8bit 10 에서 sRGB
# 0.0030 vs 감마2.4 0.00057, 5배 차이) 필터가 심판과 다른 공간에서 최적화된다.
# LIN/OET 를 바꿔 끼우면 psefield 전체가 그 공간으로 옮겨간다.
def set_eotf(kind="srgb"):
    global LIN, OET, EOTF_KIND
    EOTF_KIND = kind
    if kind == "bt1886":
        c = np.arange(256, dtype=np.float64) / 255.0
        LIN = (c ** 2.4).astype(np.float32)
        y = np.linspace(0.0, 1.0, 4096)
        OET = np.clip(np.round((y ** (1.0 / 2.4)) * 255.0), 0, 255).astype(np.uint8)
    else:
        LIN = PC._LIN
        # pselive3._build_oetf() 인라인 — sRGB 역변환 4096-LUT.
        # (pselive3.py 가 배포물에 없어 지연 대체. 동일한 sRGB 구간함수다.)
        y = np.linspace(0.0, 1.0, 4096)
        srgb = np.where(y <= 0.0031308, y * 12.92,
                        1.055 * np.power(y, 1.0 / 2.4) - 0.055)
        OET = np.clip(np.round(srgb * 255.0), 0, 255).astype(np.uint8)


LIN = OET = None
EOTF_KIND = "srgb"
set_eotf("srgb")
_OET = OET          # 하위호환
EPS = 1e-3


@dataclass
class CfgF:
    # ── 조명장 해상도 : **짧은변을 몇 칸으로**. 해상도에 무관한 단위다.
    #    8칸 = 셀 하나가 짧은변의 1/8. 10도 시야창이 세로의 약 0.36배라
    #    창 하나에 2.8칸 — 위반은 정의상 창의 25% 이상이라 충분히 겨냥된다.
    cells: int = 8
    cells_max: int = 32
    # ── 시간 필터
    filt: str = "fir"           # fir(대칭 Hann, 오버슈트 없음) | butter(참고용)
    fc_hz: float = 3.0          # BT.1702 허용 상한과 같다
    order: int = 4              # butter 전용
    # ── 보정 클램프 (log). up 을 풀면 어두운 위상이 들려 '회색빛'이 된다
    up_max: float = 1.00
    dn_max: float = 2.00
    a_max: float = 0.0          # 가산 항(선형광). 폐루프에서 필요할 때만 올린다
    # ── 컷
    cut_thresh: float = 0.45
    flat_sd: float = 2.0
    cut_norm_k: int = 15
    cut_search: int = 6
    level_step: float = 0.35
    return_win_s: float = 0.7
    min_seg: int = 12
    no_overshoot: bool = True   # butter 전용. fir 은 볼록결합이라 원래 불가능
    # ── 폐루프 사다리 (fc, a_max, dn_max, cells)
    rounds: int = 6             # 사다리 최대 단수
    force: bool = False         # 원본이 이미 PASS 여도 강제로 필터링
    #    레버를 하나씩 올리지 않는다 — **실측상 레버가 서로 얽혀 있어서**
    #    a 나 dn 단독으로는 안 되고 같이 올려야 넘어간다:
    #        03 적녹등휘도  a.05/dn2.0 3.50 FAIL  ->  a.05/**dn3.0** 0.00 PASS
    #        04 청황등휘도  a.05/dn2.0 10.16 FAIL ->  a.05/**dn3.0** 0.00 PASS
    #        12 포리곤12Hz  a.05/dn3.0 9.20 FAIL  ->  **a.15/dn4.0** 0.00 PASS
    #    그리고 fc 는 색 스트로브에 무력했다(13.90/13.80/13.66 @ fc 3/2/1).
    #    대부분의 클립은 1단에서 끝난다.
    ladder: tuple = ((3.0, 0.00, 2.0, 8),
                     (2.0, 0.00, 2.0, 8),
                     (3.0, 0.05, 3.0, 8),
                     (3.0, 0.15, 4.0, 8),
                     (2.0, 0.15, 4.0, 16),
                     (1.5, 0.30, 4.5, 16))


# ────────────────────────────────────────────────────────────── 1패스 수집
def _sig(bgr, k):
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    if k > 0:
        g = g / (cv2.blur(g, (k, k), borderType=cv2.BORDER_REFLECT101) + 1.0) * 128.0
    g = cv2.resize(g, (64, 64), interpolation=cv2.INTER_AREA)
    g -= g.mean()
    sd = float(g.std())
    return (g / sd if sd > 1e-3 else np.zeros_like(g)), sd


def ana_size(W, H, short_side):
    """**psecore.open_video 와 글자 그대로 같은 식.** 어긋나면 판정이 갈린다."""
    if min(W, H) <= short_side:
        return W, H
    s = short_side / min(W, H)
    return max(2, int(round(W * s))), max(2, int(round(H * s)))


def collect(src, cfg: CfgF):
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise IOError(src)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fs = int(np.clip(cfg.cells, 4, 240))
    s = fs / min(H, W)
    fw, fh = max(4, int(round(W * s))), max(4, int(round(H * s)))

    L, sigs, sds = [], [], []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        sm = cv2.resize(LIN[f], (fw, fh), interpolation=cv2.INTER_AREA)
        L.append(np.log(sm + EPS).astype(np.float16))
        a, b = _sig(f, cfg.cut_norm_k)
        sigs.append(a)
        sds.append(b)
    cap.release()
    return np.stack(L), fps, (H, W), (fh, fw), np.stack(sigs), np.array(sds)


# ────────────────────────────────────────────────────────────── 2. 컷
def _ncc(a, b, search):
    """이동에 강한 NCC. 실측: genre/26_safe_shaky 가 보정 없이는 120프레임 중
    100개가 컷으로 잡혔다(→ 구간이 부서져 필터가 아예 안 걸림). 보정 후 0개."""
    if search <= 0:
        return float((a * b).mean())
    pad = cv2.copyMakeBorder(a, search, search, search, search,
                             cv2.BORDER_CONSTANT, value=0.0)
    return float(cv2.matchTemplate(pad, b, cv2.TM_CCORR).max()) / b.size


def find_level_cuts(L, fps, cfg: CfgF):
    """계단형 장면전환. 구조는 그대로고 밝기 단만 바뀌는 컷(애니메이션)은 NCC 로
    안 잡힌다. '레벨이 바뀌고 돌아오지 않는다'로 잡는다 — 점멸은 돌아온다."""
    m = L.reshape(L.shape[0], -1).astype(np.float32).mean(axis=1)
    K = max(2, int(round(cfg.return_win_s * fps)))
    out = []
    for t in range(1, len(m)):
        if abs(m[t] - m[t - 1]) < cfg.level_step:
            continue
        back = m[t + 1:t + 1 + K]
        if len(back) and np.min(np.abs(back - m[t - 1])) < cfg.level_step * 0.5:
            continue
        out.append(t)
    return out


def find_cuts(sigs, sds, cfg: CfgF):
    """섬광·손떨림에 강한 **비인과** 컷 검출. 섬광이면 t+1 에서 t-1 의 내용이
    돌아오고, 컷이면 안 돌아온다. 오프라인이라 t+1 을 볼 수 있다."""
    T = len(sigs)
    out = []
    for t in range(1, T):
        if sds[t] < cfg.flat_sd or sds[t - 1] < cfg.flat_sd:
            continue
        if _ncc(sigs[t], sigs[t - 1], cfg.cut_search) >= cfg.cut_thresh:
            continue
        if t + 1 < T and sds[t + 1] >= cfg.flat_sd:
            if _ncc(sigs[t + 1], sigs[t - 1], cfg.cut_search) >= cfg.cut_thresh:
                continue
        out.append(t)
    return out


def segments(cuts, T, min_seg):
    b = [0] + [c for c in cuts if 0 < c < T] + [T]
    out = [b[0]]
    for x in b[1:]:
        if x - out[-1] < min_seg and x != T:
            continue
        out.append(x)
    if out[-1] != T:
        out[-1] = T
    return list(zip(out[:-1], out[1:]))


# ────────────────────────────────────────────────────────────── 3. 영위상
def fir_half(fps, fc):
    """**지연 = 반주기.** 규격(초당 3회)에서 바로 나오는 값이지 튜닝값이 아니다."""
    return max(1, int(round(fps / (2.0 * max(fc, 1e-6)))))


def zero_phase(L, fps, segs, cfg: CfgF, fc=None):
    """구간별 영위상 시간 저역통과. 기본은 대칭 Hann FIR.

    FIR 을 기본으로 두는 이유: 가중치가 전부 양수이고 합이 1 이라 출력이 창의
    [min,max] 를 못 벗어난다. **오버슈트가 구조적으로 불가능**하다. 버터워스는
    영위상이어도 계단에서 링잉을 내서 원본에 없던 진동을 만든다(genre/21 실측).
    """
    fc = cfg.fc_hz if fc is None else fc
    ref = np.empty_like(L)
    if cfg.filt == "fir":
        half = fir_half(fps, fc)
        w = np.hanning(2 * half + 1).astype(np.float32)
        w /= w.sum()
        for a, b in segs:
            seg = L[a:b].astype(np.float32)
            n = b - a
            if n == 1:
                ref[a:b] = L[a:b]
                continue
            h = min(half, n - 1)
            ww = np.hanning(2 * h + 1).astype(np.float32)
            ww /= ww.sum()
            pad = np.concatenate([seg[:1].repeat(h, 0), seg, seg[-1:].repeat(h, 0)], 0)
            o = np.zeros_like(seg)
            for i, k in enumerate(ww):
                o += k * pad[i:i + n]
            ref[a:b] = o.astype(np.float16)
        return ref

    from scipy.signal import butter, sosfiltfilt
    sos = butter(cfg.order, min(0.99, max(1e-4, fc / (fps / 2.0))),
                 btype="low", output="sos")
    need = 3 * (2 * cfg.order + 1)
    for a, b in segs:
        n = b - a
        seg = L[a:b].astype(np.float32)
        if n <= need:
            ref[a:b] = (seg.mean(axis=0, keepdims=True).astype(np.float16)
                        if n > 1 else L[a:b])
            continue
        o = sosfiltfilt(sos, seg.reshape(n, -1), axis=0,
                        padtype="odd").reshape(seg.shape)
        if cfg.no_overshoot:
            k = int(round(fps / max(fc, 1e-3))) | 1
            p = np.pad(seg, ((k // 2, k // 2),) + ((0, 0),) * (seg.ndim - 1),
                       mode="edge")
            mn = np.stack([p[i:i + k].min(0) for i in range(n)])
            mx = np.stack([p[i:i + k].max(0) for i in range(n)])
            o = np.clip(o, mn, mx)
        ref[a:b] = o.astype(np.float16)
    return ref


def make_u(L, ref, cfg):
    return np.clip(ref.astype(np.float32) - L.astype(np.float32),
                   -cfg.dn_max, cfg.up_max).astype(np.float16)


# ────────────────────────────────────────────────────────────── 4. 적용
def apply_stream(src, U, REF, shape_hw, fps, cfg: CfgF, out_path=None,
                 audio_src=None, yield_ana=None, wt=None):
    """디코드 -> 적용 -> (선택)인코딩. **분석해상도 프레임을 yield 한다.**

    폐루프가 이걸 psecore 에 바로 먹인다. 예전에는 라운드마다 FFV1 로 쓰고
    다시 디코드했는데 그게 전체 시간의 대부분이었다(인코딩 18% + 판정 안의 디코드).
    """
    H, W = shape_hw
    q = None
    if out_path:
        if out_path.lower().endswith(".mkv"):
            ve = ["-c:v", "ffv1", "-level", "3", "-pix_fmt", "gbrp"]
            extra = []
        else:
            ve = ["-c:v", "libx264", "-preset", "medium", "-crf", "16",
                  "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
            extra = (["-i", audio_src, "-map", "0:v:0", "-map", "1:a:0?",
                      "-c:a", "copy", "-shortest"] if audio_src else [])
        q = subprocess.Popen(
            ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
             "-s", f"{W}x{H}", "-r", str(fps), "-i", "-"] + extra + ve + [out_path],
            stdin=subprocess.PIPE)

    cap = cv2.VideoCapture(src)
    t = 0
    try:
        while t < len(U):
            ok, f = cap.read()
            if not ok:
                break
            lin = LIN[f]
            # 시간 마스크 — **위반 구간에만** 건다. w 는 이미 같은 FIR 로 평활돼
            # 있으므로 fc 위 성분이 없다 => 마스크가 켜지고 꺼지는 것 자체가
            # 새 플래시를 만들 수 없다(구조적 보장).
            wt_t = 1.0 if wt is None else float(wt[t])
            if wt_t <= 1e-4:
                bgr = f
                if q is not None:
                    q.stdin.write(np.ascontiguousarray(bgr).tobytes())
                if yield_ana is not None:
                    aw, ah = yield_ana
                    yield (cv2.resize(bgr, (aw, ah), interpolation=cv2.INTER_AREA)
                           if (aw, ah) != (W, H) else bgr)
                t += 1
                continue
            g = np.exp(wt_t * cv2.resize(U[t].astype(np.float32), (W, H),
                                         interpolation=cv2.INTER_LINEAR))
            # 클리핑은 색상을 돌린다 -> **채널별로** 캡한다. 최대채널 하나로 묶어
            # 캡하면 포화 화소에서 g<=1 이 되어 색도 보정이 통째로 막힌다.
            np.minimum(g, 1.0 / np.maximum(lin, 1e-4), out=g)
            o = lin * g
            if cfg.a_max * wt_t > 0:
                # 곱셈은 0 을 못 들어올린다. 목표까지 **더해서** 채운다(상한 a_max).
                rl = np.exp(cv2.resize(REF[t].astype(np.float32), (W, H),
                                       interpolation=cv2.INTER_LINEAR))
                o += np.clip(rl - o, 0.0, cfg.a_max * wt_t)
            idx = (np.clip(o, 0.0, 1.0) * (len(OET) - 1) + 0.5).astype(np.int32)
            bgr = np.ascontiguousarray(OET[idx])
            if q is not None:
                q.stdin.write(bgr.tobytes())
            if yield_ana is not None:
                aw, ah = yield_ana
                yield (cv2.resize(bgr, (aw, ah), interpolation=cv2.INTER_AREA)
                       if (aw, ah) != (W, H) else bgr)
            t += 1
    finally:
        cap.release()
        if q is not None:
            q.stdin.close()
            q.wait()


def _drain(gen):
    for _ in gen:
        pass


# ────────────────────────────────────────────────────────────── 실행
def run(src, dst=None, cfg: CfgF = None, verbose=True, keep_mkv=None,
        profile="bt1702"):
    cfg = replace(cfg or CfgF())          # 폐루프가 값을 바꾸므로 사본으로
    prof = PC.PROFILES[profile]
    t_all = time.time()
    L, fps, (H, W), (fh, fw), sigs, sds = collect(src, cfg)
    T = L.shape[0]
    cuts = sorted(set(find_cuts(sigs, sds, cfg) + find_level_cuts(L, fps, cfg)))
    segs = segments(cuts, T, cfg.min_seg)
    ana = ana_size(W, H, prof.short_side)
    if verbose:
        print(f"입력 {src}  {W}x{H}  {T}프레임 @ {fps:g}fps  ({T/fps:.1f}초)")
        print(f"조명장 {fw}x{fh} (셀 {min(H,W)/fh:.1f}px)  컷 {len(cuts)} "
              f"-> 구간 {len(segs)}  지연상당 {fir_half(fps, cfg.fc_hz)}프레임")

    base = PC.analyze(src, prof)
    v0 = sum(base.channel_seconds().values())
    if verbose:
        print(f"원본 위반 {v0:.2f}s {base.verdict}")

    # **원본이 이미 통과하면 손대지 않는다.**  고칠 게 없는데 고치면 손해만 난다 —
    # 실측(코퍼스): 안전 클립인데도 02 가 4.58dB, 11 이 4.77dB 바뀌었고,
    # 14(흐르는 줄무늬)는 잔상이 0.288 까지 생겼다. 28 은 3.20 -> 3.20 으로
    # 개선이 0 인데 6.22dB 를 바꿨다. 보정 도구의 기본값은 '위반한 것만 고친다'다.
    if base.verdict == "PASS" and not cfg.force:
        if verbose:
            print("  원본이 이미 PASS — 손대지 않고 그대로 둡니다 (--force 로 무시)")
        for p in filter(None, (dst, keep_mkv)):
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-c", "copy", p])
        return {"src": src, "res": f"{W}x{H}", "frames": T, "fps": round(fps, 3),
                "field": f"{fw}x{fh}", "cells": cfg.cells,
                "cell_px": round(min(H, W) / fh, 1),
                "cuts": len(cuts), "segs": len(segs),
                "before_s": round(v0, 2), "after_s": round(v0, 2),
                "verdict": base.verdict, "filt": cfg.filt, "fc_hz": cfg.fc_hz,
                "a_max": 0.0, "dn_max": 0.0, "gain_dev_dB": 0.0,
                "harmed": False, "untouched": True,
                "sec_total": round(time.time() - t_all, 1),
                "x_realtime": round((T / fps) / max(time.time() - t_all, 1e-9), 2),
                "dst": dst}

    best = None
    rungs = cfg.ladder[:max(1, cfg.rounds)]
    for r, (fc, a_max, dn, cells) in enumerate(rungs):
        if cells != cfg.cells:
            cfg.cells = cells
            L, fps, (H, W), (fh, fw), sigs, sds = collect(src, cfg)
            segs = segments(cuts, L.shape[0], cfg.min_seg)
        cfg.a_max, cfg.dn_max = a_max, dn
        REF = zero_phase(L, fps, segs, cfg, fc)
        U = make_u(L, REF, cfg)
        rep = PC.analyze(
            apply_stream(src, U, REF, (H, W), fps, cfg, yield_ana=ana),
            prof, fps=fps, src_hw=(H, W))
        v = sum(rep.channel_seconds().values())
        dev = float(np.abs(U.astype(np.float32)).mean()) * 8.686
        if verbose:
            bad = [k for k, x in rep.channel_seconds().items() if x > 0]
            print(f"  [{r}] 칸{cells} fc{fc:.1f} a{a_max:.2f} dn{dn:.1f}"
                  f" -> {v:.2f}s {rep.verdict}  게인편차 {dev:.2f}dB"
                  f"{'  남은채널 ' + ','.join(bad) if bad else ''}")
        if best is None or v < best[0]:
            best = (v, rep.verdict, fc, a_max, dn, cells, dev)
        if rep.verdict == "PASS":
            break

    v, verdict, fc, a_max, dn, ncell, dev = best
    # **무해 보장** — 원본보다 나쁘면 내보내지 않는다.
    harmed = v > v0 + 1e-6
    if harmed:
        if verbose:
            print(f"  !! 원본({v0:.2f}s)보다 나빠서({v:.2f}s) 원본을 그대로 둡니다")
        v, verdict = v0, base.verdict

    if dst or keep_mkv:
        if harmed:
            for p in filter(None, (dst, keep_mkv)):
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src,
                                "-c", "copy", p])
        else:
            cfg.a_max, cfg.dn_max = a_max, dn
            if ncell != cfg.cells:
                cfg.cells = ncell
                L, fps, (H, W), (fh, fw), sigs, sds = collect(src, cfg)
                segs = segments(cuts, L.shape[0], cfg.min_seg)
            REF = zero_phase(L, fps, segs, cfg, fc)
            U = make_u(L, REF, cfg)
            for p, aud in ((dst, src), (keep_mkv, None)):
                if p:
                    _drain(apply_stream(src, U, REF, (H, W), fps, cfg,
                                        out_path=p, audio_src=aud))

    el = time.time() - t_all
    return {"src": src, "res": f"{W}x{H}", "frames": T, "fps": round(fps, 3),
            "field": f"{L.shape[2]}x{L.shape[1]}", "cells": ncell,
            "cell_px": round(min(H, W) / max(L.shape[1], 1), 1),
            "cuts": len(cuts), "segs": len(segs),
            "before_s": round(v0, 2), "after_s": round(v, 2), "verdict": verdict,
            "filt": cfg.filt, "fc_hz": round(fc, 2), "a_max": round(a_max, 3),
            "dn_max": round(dn, 2), "gain_dev_dB": round(0.0 if harmed else dev, 2),
            "harmed": harmed, "untouched": False, "sec_total": round(el, 1),
            "x_realtime": round((T / fps) / max(el, 1e-9), 2), "dst": dst}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst", nargs="?", default=None)
    ap.add_argument("--filt", default="fir", choices=["fir", "butter"])
    ap.add_argument("--fc", type=float, default=3.0)
    ap.add_argument("--cells", type=int, default=8,
                    help="조명장: 짧은변을 몇 칸으로 (작을수록 거칠고 잔상이 적다)")
    ap.add_argument("--up", type=float, default=1.0)
    ap.add_argument("--dn", type=float, default=2.0)
    ap.add_argument("--a", type=float, default=0.0, help="가산 항 시작값")
    ap.add_argument("--rounds", type=int, default=6, help="사다리 최대 단수")
    ap.add_argument("--keep-mkv", default=None, help="무손실 판정본도 남긴다")
    ap.add_argument("--force", action="store_true",
                    help="원본이 이미 PASS 여도 필터를 적용한다")
    a = ap.parse_args()
    c = CfgF(filt=a.filt, fc_hz=a.fc, cells=a.cells, up_max=a.up, dn_max=a.dn,
             a_max=a.a, rounds=a.rounds, force=a.force)
    print(json.dumps(run(a.src, a.dst, c, keep_mkv=a.keep_mkv),
                     ensure_ascii=False, indent=1))
