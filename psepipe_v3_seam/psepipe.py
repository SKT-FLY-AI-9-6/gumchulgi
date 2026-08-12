# -*- coding: utf-8 -*-
"""
psepipe.py — **규격 게이트 기반 선택적 보정 파이프라인**
================================================================================
원칙 하나: **명시된 기준을 넘는 부분만 고친다.**

  · 영상 전체가 적합이면  -> 한 화소도 안 건드린다
  · 일부 규칙·일부 구간만 위반이면 -> **그 규칙, 그 구간에만** 작동기를 건다
  · 우리가 못 고치는 규칙은 -> 고치는 척하지 않고 **방안을 제시하고 넘긴다**

판정은 `pse_bt1702.py` 하나로 한다 (2026 가이드북이 인용한 BT.1702 조항).
「화면 전환도 플래시와 동일하게 초당 3회 초과 시 위반」 포함.

--------------------------------------------------------------------------------
작동기는 두 개다 — 규칙마다 물리가 다르기 때문
--------------------------------------------------------------------------------
**A. 시간 조명장** (psefield)      플래시 · 적색 · 5초지속 · 프레임간격
    out = in·g(x,t) + a(x,t),  g·a 는 공간·시간 저역.
    과거 프레임의 화소값이 출력에 들어갈 경로가 없다 -> 잔상 구조적 불가.

**B. 공간 대비 축소** (이 파일)     패턴
    시간 필터는 패턴을 **원리적으로 못 고친다.** 정지 줄무늬는 시간 변화가
    없어서 ref = L, 즉 u = 0 이 되어 A 가 아무 일도 하지 않는다. (dn 을 아무리
    올려도 같다 — dn 은 '어둡게 할 수 있는 한도'지 '어둡게 하라'가 아니다.)
    그래서 프레임 **안에서** 줄무늬 대비만 낮춘다:

        base = blur(Y, 줄무늬 주기)
        Y'   = base + kappa·(Y − base),   kappa = min(1, 19 / p2t)
        out  = in · (Y'/Y)                 <- 휘도비 게인이라 색도는 보존

    프레임 간 참조가 **아예 없으므로** 잔상은 물론이고 시간축 부작용도 없다.
    kappa 가 자기제한적이다 — 명암차 p2t 가 20 cd/m² 미만인 곳에서는 1 이 되어
    아무 일도 안 한다.

**C. 화면 전환** — 게인장으로도 대비축소로도 **원천 불가**. §방안 참조.

--------------------------------------------------------------------------------
시간 마스크 — "그 구간만" 을 안전하게 구현하는 법
--------------------------------------------------------------------------------
위반 구간에만 보정을 걸면 보정이 켜지고 꺼지는 **그 자체가 새 플래시**가 될 수
있다. 그래서 마스크를 박스카로 만든 뒤 **조명장과 같은 Hann FIR** 로 평활한다.
그러면 마스크에 fc 위 성분이 없으므로 마스크 전이가 플래시 조건을 만들 수 없다.
경험적 페이드 시간을 고르는 게 아니라 구조적으로 보장되는 것이다.

--------------------------------------------------------------------------------
전달함수 (EOTF) 를 심판과 맞춘다
--------------------------------------------------------------------------------
pse_bt1702 는 감마 2.4(BT.1886), psecore/psefield 기본은 sRGB 구간함수다.
어두운 쪽에서 값이 크게 다르다 — 8bit 10 에서 sRGB 0.00304 vs 감마2.4 0.00042,
**7배**. 심판과 다른 광 공간에서 최적화하면 안 되므로 `psefield.set_eotf`
로 맞춘다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import cv2
import numpy as np

sys.path.append("..")                     # psefield / psecore 는 상위 폴더
import pse_bt1702 as BT
import pse_cut as CUT
import pse_pattern as PAT
import psefield as PF

__version__ = "1.1.0"

W_Y_BGR = np.array([0.0722, 0.7152, 0.2126], np.float32)


def make_u_luma(L, REF, cfg):
    """**휘도비 스칼라 게인.** 세 채널에 같은 배율을 곱하므로 선형광에서 색도가
    정확히 보존된다 -> H·S 가 안 움직인다.

    왜 기본이어야 하는가 — 채널별 게인이 컷 검출을 흔든다(실측):

        27_anime_cuts_10ps   채널별 15→ 6컷  ΔH 8.22  ΔS 39.01
                             휘도비 15→15컷  ΔH 1.36  ΔS  1.16   <- 완전 보존
        08_red_black         채널별  8→ 3컷 (소실)  / 휘도비 8→8
        09_red_gray          채널별  8→13컷 (생성) / 휘도비 8→8
                             ↑ 09 는 채널별이 **원본에 없던 화면전환 위반을 만들었다**

    pse_cut 은 블록별 H·S 히스토그램 거리로 판정한다(V 는 안 본다). 채널별
    게인은 채도를 크게 움직여 그 거리를 무너뜨린다. 휘도만 바꾸면 안 흔들린다.

    대가: **색 규칙(②)은 휘도비로 못 고친다** — 03/08/09 가 적색 위반으로 남는다.
    그래서 ② 가 실패할 때만 채널별로 올린다.
    """
    yL = (np.exp(L.astype(np.float32)) * W_Y_BGR).sum(-1)
    yR = (np.exp(REF.astype(np.float32)) * W_Y_BGR).sum(-1)
    u = np.clip(np.log(np.maximum(yR, 1e-6) / np.maximum(yL, 1e-6)),
                -cfg.dn_max, cfg.up_max)
    return np.repeat(u[..., None], 3, axis=-1).astype(np.float16)

# ── 규칙 -> 작동기.  "없음" 은 우리 구조로 못 고치는 것.
ACTUATOR = {
    "플래시":   "A",   # 시간 조명장, fc 를 낮춘다
    "적색":     "A",   # 시간 조명장 + 가산항 (곱셈은 0을 못 들어올린다)
    "5초지속":  "A",
    "프레임간격": "A",
    "패턴":     "B",   # 공간 대비 축소
    "화면전환": "없음",
}
UNFIXABLE = {r for r, a in ACTUATOR.items() if a == "없음"}


# ══════════════════════════════════════════════════════════════ 시간 마스크
def time_mask(T, fps, segments, fc, pad_s=0.5):
    """위반 구간 -> [0,1] 시간 가중치. 조명장과 같은 FIR 로 평활한다."""
    w = np.zeros(T, np.float32)
    for s in segments:
        a = max(0, int(round((s[0] - pad_s) * fps)))
        b = min(T, int(round((s[1] + pad_s) * fps)) + 1)
        w[a:b] = 1.0
    if w.max() <= 0:
        return None                       # 구간 정보가 없으면 전체 적용
    h = PF.fir_half(fps, fc)
    k = np.hanning(2 * h + 1).astype(np.float32)
    k /= k.sum()
    p = np.concatenate([w[:1].repeat(h), w, w[-1:].repeat(h)])
    return np.convolve(p, k, mode="valid").astype(np.float32)


def space_time_mask(T, fps, segs, grids, fc, pad_s=0.5, sigma_cells=4.0,
                    floor=0.0):
    """(T, gh, gw) 공간·시간 가중치. **시간 구간 x 그 구간에서 실제로 검출된 화소.**

    시간 마스크만 쓰면 위반 구간 동안 화면 전체를 손댄다. 검출기는 어느 화소가
    번쩍였는지 이미 알고 있으므로(Counter.masks) 그걸 곱하면 안 번쩍인 곳은
    원본이 남는다. 다만 **딱딱한 경계는 그 자체가 자극**이라 두 번 뭉갠다:

      · 공간 — 마스크격자 셀 4개 크기의 가우시안. σ 스윕 실측(local40_pan,
        seam.py): σ1.5 헤일로 +16.9 / σ4 +14.0 / σ8 +11.5, 만지는 면적은
        32.5→44.6→65.9%. σ4 가 균형점 — 펌핑은 공간게이트 수준(+1.3, 시간만은
        +3.3), 헤일로는 시간만(+12.9)에 근접, 면적 절반 이하.
      · 시간 — 조명장과 **같은 한 커널**(fir_half(fps, fc)). 마스크가 켜지고
        꺼지는 순간이 새 플래시 엣지가 되지 않게 하려면 마스크의 상승/하강도
        차단주파수 아래여야 한다.
    """
    if not segs or not grids:
        return None
    gh, gw = next(iter(grids.values())).shape[1:]
    W = np.zeros((T, gh, gw), np.float32)
    for key, seg_list in segs.items():
        g = grids.get(key)
        if g is None or not seg_list:
            continue
        for a_s, b_s in seg_list:
            a = max(0, int(round((a_s - pad_s) * fps)))
            b = min(T, int(round((b_s + pad_s) * fps)) + 1)
            if b <= a:
                continue
            np.maximum(W[a:b], g[a:b].astype(np.float32), out=W[a:b])
    if W.max() <= 0:
        return None
    k = int(max(3, round(sigma_cells * 3) | 1))
    for t in range(T):
        if W[t].max() > 0:
            W[t] = cv2.GaussianBlur(W[t], (k, k), sigma_cells)
    h = PF.fir_half(fps, fc)
    ker = np.hanning(2 * h + 1).astype(np.float32); ker /= ker.sum()
    # 시간축 = 행 방향. 대칭 커널이라 상관=합성곱, BORDER_REPLICATE = 끝값 패딩.
    flat = np.ascontiguousarray(W.reshape(T, -1))
    W = cv2.filter2D(flat, -1, ker.reshape(-1, 1),
                     borderType=cv2.BORDER_REPLICATE).reshape(T, gh, gw)
    if floor > 0:
        W = floor + (1.0 - floor) * W
    return np.clip(W, 0.0, 1.0).astype(np.float32)

def merge_events(diag, gap_s=0.15, grids=None, fps=30.0, T=0):
    """규칙별 위반 구간을 **하나의 위험 이벤트 타임라인**으로 합친다.

    ChatGPT v3 (`_merge_intervals`) 에서 가져온 발상. 규칙 6개가 각자 구간을
    뱉으면 편집자는 같은 장면을 6번 본다. 겹치거나 gap_s 이내로 붙은 구간을
    한 이벤트로 묶고 어느 규칙들이 걸렸는지 목록으로 준다. **판정은 안 바꾼다** —
    보고용이다. 필터는 규칙별 마스크를 써야 하므로 합친 걸 쓰면 안 된다
    (합치면 플래시 구간에 패턴용 블러까지 걸린다).
    """
    items = sorted(({"a": float(x["start_s"]), "b": float(x["end_s"]),
                     "r": x["rule"]} for x in diag["violation_segments"]),
                   key=lambda x: (x["a"], x["b"]))
    ev = []
    for x in items:
        if not ev or x["a"] > ev[-1]["end_s"] + gap_s:
            ev.append({"start_s": round(x["a"], 2), "end_s": round(x["b"], 2),
                       "rules": [x["r"]]})
        else:
            ev[-1]["end_s"] = round(max(ev[-1]["end_s"], x["b"]), 2)
            if x["r"] not in ev[-1]["rules"]:
                ev[-1]["rules"].append(x["r"])
    if grids and T:
        for e in ev:
            i = max(0, int(e["start_s"] * fps)); j = min(T, int(np.ceil(e["end_s"] * fps)))
            u = None
            for rn in e["rules"]:
                g = grids.get(rn)
                if g is None or j <= i:
                    continue
                m = np.asarray(g[i:j], np.float32).max(0)
                u = m if u is None else np.maximum(u, m)
            if u is None:
                continue
            b = u > 0.05
            e["mask_area_pct"] = round(float(b.mean()) * 100, 1)
            if b.any():
                ys, xs = np.where(b)
                gh, gw = b.shape
                e["bbox_pct"] = [round(float(xs.min()) / gw * 100, 1),
                                 round(float(ys.min()) / gh * 100, 1),
                                 round(float(xs.max() + 1) / gw * 100, 1),
                                 round(float(ys.max() + 1) / gh * 100, 1)]
    return ev

# ══════════════════════════════════════════════════════════════ 작동기 B
class PatternFix:
    """공간 대비 축소. 프레임 간 참조가 없다 — 시간축 부작용 0."""

    def __init__(self, periods, target=19.0, min_k=0.25):
        self.periods = periods            # 프레임별 지배 줄무늬 주기(px, 분석해상도)
        self.target = target              # cd/m², 임계 20 아래로
        self.min_k = min_k

    def apply(self, lin, t, scale):
        per = self.periods[min(t, len(self.periods) - 1)]
        if per <= 1.5:
            return lin
        k = int(max(3, min(99, round(per * scale)))) | 1
        Y = (lin[..., 2] * 0.2126 + lin[..., 1] * 0.7152 + lin[..., 0] * 0.0722)
        Ycd = Y * BT.SDR_PEAK
        ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        p2t = cv2.dilate(Ycd, ker) - cv2.erode(Ycd, ker)
        kap = np.clip(self.target / np.maximum(p2t, 1e-3), self.min_k, 1.0)
        base = cv2.blur(Y, (k, k), borderType=cv2.BORDER_REFLECT101)
        Yn = base + kap * (Y - base)
        g = np.clip(Yn / np.maximum(Y, 1e-5), 0.0, 4.0)[..., None]
        return np.clip(lin * g, 0.0, 1.0)


def _passthrough(src, dst):
    """원본을 그대로 내보낸다. **컨테이너가 다르면 -c copy 가 실패한다** —
    FFV1(.mkv) 을 .mp4 로 복사하려다 'Could not find tag for codec ffv1' 로
    죽는다(실측, 코퍼스 sweep 에서 발견). 확장자가 같을 때만 스트림 복사하고
    아니면 재인코딩한다."""
    import subprocess
    same = os.path.splitext(src)[1].lower() == os.path.splitext(dst)[1].lower()
    enc = (["-c", "copy"] if same else
           ["-c:v", "libx264", "-preset", "medium", "-crf", "16",
            "-pix_fmt", "yuv420p"])
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src] + enc + [dst],
                       capture_output=True, text=True)
    if r.returncode != 0:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src,
                        "-c:v", "libx264", "-preset", "medium", "-crf", "16",
                        "-pix_fmt", "yuv420p", dst], check=False)
    return dst


# ══════════════════════════════════════════════════════════════ 여백
def axes(rep):
    """규칙별 **축마다** (측정, 한도) 를 뽑는다.

    규격은 축들의 AND 다 — 한 축만 밑이면 통과한다. 그래서 '통과'가 곧
    '안전 여유가 있다'는 뜻이 아니다. 실측(cera.mp4): 플래시 면적이 한도의
    **247%** 인데 빈도가 2회/s(한도 3)라 통과한다. 플래시가 초당 한 번만 더
    있으면 뒤집힌다. 그런 상태를 '적합'으로 끝내면 안 된다.
    """
    out = []
    R = rep["rules"]
    for key, tag in (("flash", "①"), ("red", "②")):
        c = (R.get(key) or {}).get("co_axes")
        if c:
            out.append((tag + "빈도", c["per_sec"], 3.0, "A"))
            out.append((tag + "면적", c["area_pct"], 25.0, "A"))
    p = R.get("pattern") or {}
    c = p.get("co_axes")
    if p.get("pass") is not None and c:
        out.append(("③쌍수", c["pairs"], c["need_pairs"], "B"))
        out.append(("③면적", c["area_pct"], c["need_area_pct"], "B"))
    fs = rep.get("frame_separation") or {}
    if fs.get("observed_min_frames"):
        # 간격은 클수록 안전하므로 뒤집어 잰다
        out.append(("⑥간격", fs["required_frames"] / max(fs["observed_min_frames"], 1e-9),
                    1.0, "A"))
    return out


def over_axes(rep, factor=1.0, actuators="AB"):
    return [(n, m, l) for n, m, l, a in axes(rep)
            if a in actuators and l > 0 and m > l * factor]


# ══════════════════════════════════════════════════════════════ 사다리
def plan_ladder(failed, margin=False):
    """**실패한 규칙이 쓸 수 있는 레버만** 사다리에 넣는다. 헛도는 라운드가 없다.

    단은 (fc, a_max, dn_max, cells, gain_mode) 다.
      gain_mode "luma" = 휘도비 스칼라. 색도 보존 -> 컷 검출을 안 흔든다. **기본**
                "chan" = 채널별. 색 규칙을 고칠 수 있지만 컷을 흔든다(실측 참조)
    색 규칙(②)은 휘도비로 못 고치므로 그때만 chan 으로 올린다.
    """
    f = set(failed)
    need_t = bool({"플래시", "프레임간격", "5초지속"} & f) or margin
    need_c = "적색" in f
    rungs = [(3.0, 0.00, 2.0, 8, "luma")]
    if need_t:
        rungs += [(2.0, 0.00, 2.0, 8, "luma"), (1.5, 0.00, 2.0, 8, "luma")]
    if margin:
        # 실측(cera): 여백을 만드는 건 fc 다. ①면적 61.8 -> fc3.0 32.6 -> fc1.0 22.3.
        rungs += [(1.0, 0.00, 2.0, 8, "luma"), (0.7, 0.00, 2.0, 8, "luma")]
    # 여기서부터 채널별 — 색 규칙용이거나 휘도비로 안 될 때의 후퇴
    # 실측: a 나 dn 단독으로는 안 넘어간다. 같이 올려야 한다.
    # **휘도 플래시에도 필요하다** — 전면 백↔흑(28_flash_only_5hz)은 골짜기가
    # 0 이라 곱셈으로 못 들어올린다. fc 만 낮추면 영원히 안 넘어간다(실측).
    rungs += [(3.0, 0.00, 2.0, 8, "chan"), (3.0, 0.05, 3.0, 8, "chan"),
              (3.0, 0.15, 4.0, 8, "chan"), (2.0, 0.15, 4.0, 16, "chan")]
    if margin:
        rungs += [(1.0, 0.15, 4.0, 8, "chan"), (0.5, 0.30, 4.5, 8, "chan")]
    out, seen = [], set()
    for r in rungs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


# ══════════════════════════════════════════════════════════════ 적용 스트림
def apply_stream(src, U, REF, shape_hw, fps, cfg, wt=None, patfix=None,
                 out_path=None, audio_src=None, yield_ana=None):
    """A(조명장) + B(대비축소) 를 한 번의 디코드로 적용하며 흘려보낸다."""
    import subprocess
    H, W = shape_hw
    q = None
    if out_path:
        ve = (["-c:v", "ffv1", "-level", "3", "-pix_fmt", "gbrp"]
              if out_path.lower().endswith(".mkv") else
              ["-c:v", "libx264", "-preset", "medium", "-crf", "16",
               "-pix_fmt", "yuv420p", "-movflags", "+faststart"])
        extra = (["-i", audio_src, "-map", "0:v:0", "-map", "1:a:0?",
                  "-c:a", "copy", "-shortest"]
                 if audio_src and not out_path.lower().endswith(".mkv") else [])
        q = subprocess.Popen(
            ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
             "-s", f"{W}x{H}", "-r", str(fps), "-i", "-"] + extra + ve + [out_path],
            stdin=subprocess.PIPE)

    cap = cv2.VideoCapture(src)
    n = len(U) if U is not None else 10 ** 9
    t = 0
    try:
        while t < n:
            ok, f = cap.read()
            if not ok:
                break
            if wt is None:
                wt_t = 1.0
            elif wt.ndim == 1:                     # 시간만
                wt_t = float(wt[t])
            else:                                  # 시간 x 공간 (T, gh, gw)
                wt_t = (0.0 if float(wt[t].max()) <= 1e-4 else
                        cv2.resize(wt[t], (W, H), interpolation=cv2.INTER_LINEAR)[..., None])
            if np.max(wt_t) <= 1e-4:
                bgr = f
            else:
                lin = PF.LIN[f]
                if U is not None:
                    g = np.exp(wt_t * cv2.resize(U[t].astype(np.float32), (W, H),
                                                 interpolation=cv2.INTER_LINEAR))
                    np.minimum(g, 1.0 / np.maximum(lin, 1e-4), out=g)
                    o = lin * g
                    if cfg.a_max > 0 and np.max(wt_t) > 0:
                        rl = np.exp(cv2.resize(REF[t].astype(np.float32), (W, H),
                                               interpolation=cv2.INTER_LINEAR))
                        o += np.clip(rl - o, 0.0, cfg.a_max * wt_t)
                else:
                    o = lin
                if patfix is not None:
                    o2 = patfix.apply(o, t, W / 320.0)
                    o = o + wt_t * (o2 - o)          # 마스크로 세기 조절
                idx = (np.clip(o, 0.0, 1.0) * (len(PF.OET) - 1) + 0.5).astype(np.int32)
                bgr = np.ascontiguousarray(PF.OET[idx])
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


def _drain(g):
    for _ in g:
        pass


# ══════════════════════════════════════════════════════════════ 파이프라인
def dissolve_cuts(src, out_path, n_frames, cut_times, fps, verbose=True):
    """하드컷을 n_frames 디졸브로 바꾼다. **전체 프레임을 메모리에 올린다** —
    컷 앞뒤 프레임이 필요해서다. 긴 영상에는 구간 단위로 나눠 쓸 것."""
    import subprocess
    cap = cv2.VideoCapture(src)
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fr = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        fr.append(f.astype(np.float32))
    cap.release()
    out = [f.copy() for f in fr]
    for t in cut_times:
        c = int(round(t * fps))
        a = max(0, c - 1)
        b = min(len(fr) - 1, c + n_frames - 1)
        A, B = fr[a], fr[b]
        for k in range(a, b + 1):
            w = (k - a) / max(b - a, 1)
            out[k] = (1 - w) * A + w * B
    ve = (["-c:v", "ffv1", "-level", "3", "-pix_fmt", "gbrp"]
          if out_path.lower().endswith(".mkv") else
          ["-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p"])
    q = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo",
                          "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps),
                          "-i", "-"] + ve + [out_path], stdin=subprocess.PIPE)
    for f in out:
        q.stdin.write(np.clip(f, 0, 255).astype(np.uint8).tobytes())
    q.stdin.close()
    q.wait()
    if verbose:
        print(f"      디졸브 {n_frames}f x {len(cut_times)}개 -> {out_path}")
    return out_path


def run(src, dst=None, width=320, eotf="bt1886", pad_s=0.5, verbose=True,
        max_rounds=9, dissolve=0, margin=0.0, min_seg=1, cut_src="judge",
        spatial=True):
    t0 = time.time()
    PF.set_eotf(eotf)

    # ── 1. 진단 (전체 1회)
    if verbose:
        print(f"[1/4] 진단  {src}")
    diag = BT.analyze(src, width=width, keep_masks=spatial)
    fps = diag["fps"]
    T = diag["frames"]
    cut_cached = diag["rules"].get("cut")     # 게인장으로 안 변한다 -> 재사용
    pat0 = diag["rules"].get("pattern")
    failed = list(diag["failed_rules"])
    if verbose:
        print(f"      {diag['duration_s']}s @ {fps:.0f}fps  "
              f"판정 {'적합' if diag['compliant'] else '위반 — ' + ', '.join(failed)}")

    cap = cv2.VideoCapture(src)
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    ana = PF.ana_size(W, H, width)

    base_out = {"src": src, "res": f"{W}x{H}", "frames": T, "fps": round(fps, 3),
                "eotf": eotf, "before_compliant": diag["compliant"],
                "before_failed": failed}

    # ── 적합하면 손대지 않는다 (margin 모드에서 넘는 축이 있으면 계속한다)
    over0 = over_axes(diag, margin) if margin else []
    if over0 and verbose:
        print("      여백 없음: " + ", ".join(
            f"{n} {m:.1f}/{l:.0f}({m/l*100:.0f}%)" for n, m, l in over0))
    if diag["compliant"] and not over0:
        if verbose:
            print("      원본이 이미 적합 — 손대지 않습니다")
        if dst:
            _passthrough(src, dst)
        return {**base_out, "untouched": True, "after_compliant": True,
                "after_failed": [], "unfixable": [], "dst": dst,
                "sec_total": round(time.time() - t0, 1)}

    # ── 컷 전처리 (옵션) — A/B 보다 **먼저** 하고 다시 진단한다
    if dissolve > 0 and "화면전환" in failed and cut_cached and cut_cached.get("pass") is False:
        import pse_cut as _CUT
        cr = _CUT.analyze(src, width=width)
        tmp = os.path.splitext(dst or src)[0] + "_dis.mkv"
        dissolve_cuts(src, tmp, dissolve, cr["cut_times"], fps, verbose)
        src = tmp
        diag = BT.analyze(src, width=width, keep_masks=spatial)
        cut_cached = diag["rules"].get("cut")
        pat0 = diag["rules"].get("pattern")
        failed = list(diag["failed_rules"])
        base_out["dissolve_frames"] = dissolve
        if verbose:
            print(f"      디졸브 후 재진단: "
                  f"{'적합' if diag['compliant'] else '위반 — ' + ', '.join(failed)}")
        if diag["compliant"]:
            if dst:
                import subprocess
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src,
                                "-c:v", "libx264", "-preset", "medium", "-crf", "16",
                                "-pix_fmt", "yuv420p", dst])
            return {**base_out, "untouched": False, "after_compliant": True,
                    "after_failed": [], "fixed": ["화면전환"], "unfixable": [],
                    "actuators": "C", "touched_time_pct": 100.0,
                    "fc_hz": 0, "a_max": 0, "dn_max": 0, "cells": 0,
                    "sec_total": round(time.time() - t0, 1),
                    "x_realtime": round((T / fps) / max(time.time() - t0, 1e-9), 2),
                    "dst": dst}

    fixable = [r for r in failed if r not in UNFIXABLE]
    unfix = [r for r in failed if r in UNFIXABLE]

    # ── ⑥ 이 **컷이 만든 플래시쌍**이면 A 로 못 고친다 — 시작 전에 가려낸다.
    # 게인장은 컷을 보호하도록 설계됐다(컷에서 세그먼트 분할). 컷 자체가 플래시
    # 엣지로 계수된 타이트쌍은 그래서 구조상 불가고, 억지로 누르면 컷 검출만
    # 흔들어 **원본에 없던 화면전환 위반**을 만든다. 실측(Db2D03pxZjy):
    # 14단 전부 실패 + 새 위반 -> 원본복귀, 346초 낭비. 타이트쌍 전부에 판정
    # 컷이 겹칠 때만 발동한다 (플래시 규칙도 위반이면 사다리는 어차피 필요).
    if "프레임간격" in fixable and "플래시" not in failed:
        sep_segs = (diag["rules"].get("_sep") or {}).get("segments") or []
        ctimes = ((cut_cached or {}).get("cut_times") or [])
        if sep_segs and ctimes and            all(any(a <= t <= b for t in ctimes) for a, b in sep_segs):
            fixable.remove("프레임간격")
            unfix.append("프레임간격(컷유발)")
            if verbose:
                print("      ⑥ 타이트쌍이 전부 컷과 일치 — 컷유발로 분류, 편집 방안으로")
    if margin:      # 넘는 축이 있으면 그 축의 작동기를 켠다
        for n, m, l in over0:
            act = dict((a[0], a[3]) for a in axes(diag))[n]
            if act == "A" and "플래시" not in fixable:
                fixable.append("플래시")
            if act == "B" and "패턴" not in fixable:
                fixable.append("패턴")
    need_A = any(ACTUATOR[r] == "A" for r in fixable)
    need_B = any(ACTUATOR[r] == "B" for r in fixable)
    if verbose:
        print(f"[2/4] 라우팅  A(시간조명장) {need_A}  B(대비축소) {need_B}"
              f"  불가 {unfix or '-'}")

    # ── 2. 시간 마스크 — 고칠 수 있는 규칙의 구간만
    segs = [(s["start_s"], s["end_s"]) for s in diag["violation_segments"]
            if s["rule"] not in UNFIXABLE]
    if margin:
        # **넘는 축의 위치도 마스크에 넣는다.** 빈도 축이 안 넘어 '적합'이어도
        # 면적 축은 넘을 수 있다. 실측(cera): ⑥ 위반 구간만 덮었더니 fc 를
        # 아무리 낮춰도 ①면적이 38.5% 에서 안 내려갔는데, 면적 축 위치를 마스크에
        # 넣자 같은 fc 에서 32.6%, fc1.0 에서 22.3% 로 내려갔다.
        for key in ("flash", "red"):
            segs += [tuple(x) for x in
                     (diag["rules"].get(key) or {}).get("area_segments", [])]
        # 패턴(③)은 위치를 모르므로 **B 만** 전역으로 돌린다. B 는 자기제한적이라
        # (p2t < 20 cd/m² 이면 kappa=1 로 무동작) 전역이어도 안 건드릴 곳은 안 건드린다.
        # A 의 마스크에는 넣지 않는다 — 넣으면 조명장까지 전역이 되어 100% 를 손댄다.

    # 규칙별로 나눠 둔다 — 공간 게이트는 "그 규칙이 검출한 화소"에만 걸어야 한다
    RULE_GRID = {"플래시": ("flash",), "5초지속": ("flash", "red"),
                 "프레임간격": ("flash", "red"), "적색": ("red",),
                 "패턴": ("pattern",)}
    segs_by_rule = {}
    for sv in diag["violation_segments"]:
        if sv["rule"] in UNFIXABLE:
            continue
        segs_by_rule.setdefault(sv["rule"], []).append((sv["start_s"], sv["end_s"]))
    if margin:
        for key, rname in (("flash", "플래시"), ("red", "적색")):
            for x in (diag["rules"].get(key) or {}).get("area_segments", []) or []:
                segs_by_rule.setdefault(rname, []).append(tuple(x))

    sp = diag.get("_spatial") if spatial else None
    grids = keyed = None
    if sp and segs_by_rule:
        grids, keyed = {}, {}
        for rname, srcs in RULE_GRID.items():
            gs = [sp[k] for k in srcs if sp.get(k) is not None]
            if not gs:
                continue
            grids[rname] = gs[0] if len(gs) == 1 else np.maximum.reduce(
                [g.astype(np.float32) for g in gs])
            keyed[rname] = segs_by_rule.get(rname, [])
        if not any(keyed.values()):
            grids = keyed = None

    def build_wt(fc, mode="공간"):
        """사다리 단마다 다시 만든다 — 마스크의 완만함은 그 단의 fc 에 묶인다.

        mode="공간" 은 검출 화소만, "시간" 은 구간 전체(구버전). **공간이 항상
        낫지는 않다** — 실측(burst.mkv): 공간 게이트를 걸면 같은 단에서 ⑥ 를
        못 잡아 사다리가 chan 까지 올라갔고, 결과가 위반(PSNR 19.6)이었다.
        시간 마스크로 두면 0단 luma 에서 적합(PSNR 21.4)이었다. 그래서 마스크
        폭도 사다리의 한 축으로 둔다 — 좁은 쪽 먼저, 안 되면 넓힌다."""
        if mode == "공간" and grids:
            w = space_time_mask(T, fps, keyed, grids, fc, pad_s)
            if w is not None:
                return w
        return time_mask(T, fps, segs, fc, pad_s) if segs else None

    events = merge_events(diag, 0.15, grids, fps, T)
    if verbose and events:
        print(f"      통합 위험 이벤트 {len(events)}개")
    wt = build_wt(3.0)
    space_pct = (float((wt > 1e-3).mean()) * 100
                 if wt is not None and wt.ndim == 3 else None)
    mask_modes = ["공간", "시간"] if (grids and space_pct is not None) else ["시간"]
    cover = float((wt.reshape(T, -1).max(1) if wt is not None and wt.ndim == 3
                   else wt).mean()) if wt is not None else 1.0
    if verbose:
        extra = f"  화면공간의 {space_pct:.1f}%" if space_pct is not None else ""
        print(f"      보정 구간 {len(segs)}개  화면시간의 {cover*100:.1f}%{extra}")

    # ── 3. 작동기 준비
    patfix = None
    if need_B:
        pr = PAT.analyze(src, width=width, verbose=False)
        patfix = PatternFix([s["period"] for s in pr["_series"]])

    L = REF = None
    cfg = PF.CfgF()
    col_cells = cfg.cells                 # 지금 L 이 어떤 칸수로 수집됐나
    if need_A:
        L, fps_c, (H, W), (fh, fw), sg, sd = PF.collect(src, cfg)
        cuts = sorted(set(PF.find_cuts(sg, sd, cfg) + PF.find_level_cuts(L, fps_c, cfg)))
        fsegs = PF.segments(cuts, L.shape[0], cfg.min_seg)

    # ── 4. 폐루프 — 실패한 규칙이 쓸 수 있는 레버만
    ladder = (plan_ladder(fixable, margin=bool(margin)) if need_A
              else [(3.0, 0.0, 2.0, 8, "luma")])
    best = None
    if verbose:
        print(f"[3/4] 보정  사다리 {len(ladder)}단 x 마스크 {len(mask_modes)}종")
    rungs = [(fc, a, d, c, g, mm) for (fc, a, d, c, g) in ladder
             for mm in mask_modes]
    for r, (fc, a_max, dn, cells, gmode, mmode) in enumerate(rungs[:max_rounds * 2]):
        if need_A:
            if cells != col_cells:
                cfg.cells = col_cells = cells
                L, fps_c, (H, W), (fh, fw), sg, sd = PF.collect(src, cfg)
                fsegs = PF.segments(cuts, L.shape[0], cfg.min_seg)
            cfg.cells = cells
            cfg.a_max, cfg.dn_max = a_max, dn
            REF = PF.zero_phase(L, fps_c, fsegs, cfg, fc)
            U = (make_u_luma(L, REF, cfg) if gmode == "luma"
                 else PF.make_u(L, REF, cfg))
            wt_r = build_wt(fc, mmode)
        else:
            U = REF = None
            wt_r = build_wt(3.0, mmode)

        stream = apply_stream(src, U, REF, (H, W), fps, cfg, wt=wt_r,
                              patfix=patfix, yield_ana=ana)
        pat_arg = pat0 if not need_B else None       # B 를 걸었으면 다시 재야 한다
        rep = BT.analyze(stream, width=width, fps=fps,
                         cut_result=cut_cached, pattern_result=pat_arg)
        still = [x for x in rep["failed_rules"] if x not in UNFIXABLE]
        ov = over_axes(rep, margin) if margin else []
        if verbose:
            ovs = ("  넘는축 " + ",".join(f"{n}{m/l*100:.0f}%" for n, m, l in ov)) if ov else ""
            print(f"      [{r}] {gmode:<4}/{mmode} fc{fc:.1f} a{a_max:.2f} dn{dn:.1f} "
                  f"-> {'적합' if rep['compliant'] else '위반 ' + ','.join(rep['failed_rules'])}{ovs}")
        score = (len(still), len(ov),
                 sum(s["violation_seconds"] for s in rep["rules"].values()
                     if isinstance(s.get("violation_seconds"), (int, float))))
        if best is None or score < best[0]:
            best = (score, fc, a_max, dn, cells, rep, gmode, mmode)
        if not still and not ov:
            break

    score, fc, a_max, dn, cells, rep, gmode, mmode = best
    after_fail = list(rep["failed_rules"])

    # **무해 보장** — 원본에 없던 위반 규칙이 생겼으면 내보내지 않는다.
    new_bad = [x for x in after_fail if x not in failed]
    if new_bad:
        if verbose:
            print(f"      !! 원본에 없던 위반이 생겼습니다({', '.join(new_bad)}) — 원본 유지")
        if dst:
            _passthrough(src, dst)
        return {**base_out, "untouched": True, "harmed": True,
                "after_compliant": diag["compliant"], "after_failed": failed,
                "fixed": [], "unfixable": unfix, "actuators": "-",
                "touched_time_pct": 0.0, "fc_hz": 0, "a_max": 0, "dn_max": 0,
                "cells": 0, "sec_total": round(time.time() - t0, 1),
                "x_realtime": 0.0, "dst": dst}

    # ── 5. 최종 출력
    if dst:
        if need_A:
            cfg.a_max, cfg.dn_max, cfg.cells = a_max, dn, cells
            if cells != col_cells:
                # **best 단과 마지막 수집의 칸수가 다르면 L 이 낡았다.** 재수집
                # 없이 렌더하면 폐루프가 판정한 것과 다른 파일이 나간다
                # (실측 burst2: 보고 '프레임간격만 위반' vs 파일 '플래시 5회/s').
                cfg.cells = col_cells = cells
                L, fps_c, (H, W), (fh, fw), sg, sd = PF.collect(src, cfg)
                fsegs = PF.segments(cuts, L.shape[0], cfg.min_seg)
            REF = PF.zero_phase(L, fps_c, fsegs, cfg, fc)
            U = (make_u_luma(L, REF, cfg) if gmode == "luma"
                 else PF.make_u(L, REF, cfg))
            # **폐루프에서 판정에 쓴 마스크와 같은 것으로 렌더해야 한다.**
            # 여기서만 다른 마스크를 만들면 "적합" 판정이 내보낸 파일과 무관해진다.
            wt_r = build_wt(fc, mmode)
        else:
            U = REF = None
            wt_r = build_wt(3.0, mmode)
        if verbose:
            print(f"[4/4] 렌더  {dst}")
        _drain(apply_stream(src, U, REF, (H, W), fps, cfg, wt=wt_r, patfix=patfix,
                            out_path=dst, audio_src=src))
        # ── **출력 파일 재판정** — 보고하는 판정은 스트림이 아니라 파일의 것.
        # 스트림 판정과 파일이 어긋나는 버그가 두 번 있었다(마스크 상이, L 낡음).
        # 인코딩 손실도 판정을 뒤집을 수 있다. 파일을 재는 것만이 정직하다.
        rep_f = BT.analyze(dst, width=width)
        mismatch = list(rep_f["failed_rules"]) != list(rep["failed_rules"])
        if verbose and mismatch:
            print(f"      !! 스트림 판정과 파일 판정 불일치: "
                  f"스트림 {rep['failed_rules']} vs 파일 {rep_f['failed_rules']}")
        rep = rep_f
        after_fail = list(rep["failed_rules"])
        new_bad2 = [x for x in after_fail if x not in failed]
        if new_bad2:
            # **누구 탓인지 가른다.** 원본을 그냥 재인코딩만 해도 같은 위반이
            # 생기면 필터 탓이 아니라 원본이 한도 경계에 걸쳐 있는 것이다.
            # 실측(Db2D03pxZjy): 원본 3컷/s(한도=3, 여백 0) -> crf10 재인코딩만
            # 해도 4컷/s. 어느 쪽이든 원본을 유지한다 — 우리가 만드는 어떤
            # 출력도 위반 파일이 되므로 안 내보내는 것이 맞다.
            ctrl = os.path.splitext(dst)[0] + "_encctrl.mp4"
            import subprocess as _sp
            cap2 = cv2.VideoCapture(src)
            q2 = _sp.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo",
                            "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps),
                            "-i", "-", "-c:v", "libx264", "-preset", "medium",
                            "-crf", "16", "-pix_fmt", "yuv420p", ctrl],
                           stdin=_sp.PIPE)
            while True:
                ok2, f2 = cap2.read()
                if not ok2:
                    break
                q2.stdin.write(f2.tobytes())
            cap2.release(); q2.stdin.close(); q2.wait()
            ctrl_failed = BT.analyze(ctrl, width=width)["failed_rules"]
            os.remove(ctrl)
            enc_bad = [x for x in new_bad2 if x in ctrl_failed]
            reason = ("인코딩경계" if enc_bad == new_bad2 else
                      "필터유해" if not enc_bad else "혼합")
            if verbose:
                why = {"인코딩경계": "재인코딩만 해도 생긴다 (원본이 한도 경계)",
                       "필터유해": "필터가 만들었다",
                       "혼합": "일부는 인코딩, 일부는 필터"}[reason]
                print(f"      !! 파일에서 원본에 없던 위반({', '.join(new_bad2)}) — "
                      f"{why} — 원본 유지")
            _passthrough(src, dst)
            return {**base_out, "untouched": True, "harmed": True,
                    "harm_reason": reason, "harm_rules": new_bad2,
                    "after_compliant": diag["compliant"], "after_failed": failed,
                    "fixed": [], "unfixable": unfix, "actuators": "-",
                    "touched_time_pct": 0.0, "fc_hz": 0, "a_max": 0, "dn_max": 0,
                    "cells": 0, "sec_total": round(time.time() - t0, 1),
                    "x_realtime": 0.0, "dst": dst}

    el = time.time() - t0
    return {**base_out,
            "untouched": False,
            "after_compliant": bool(rep["compliant"]),
            "after_failed": after_fail,
            "fixed": [r for r in failed if r not in after_fail],
            "unfixable": unfix,
            "actuators": ("A" if need_A else "") + ("B" if need_B else "") or "-",
            "touched_time_pct": round(cover * 100, 1),
            "touched_space_pct": (None if space_pct is None else round(space_pct, 1)),
            "spatial_gate": bool(space_pct is not None),
            "mask_mode": mmode,
            "events": events,
            "fc_hz": fc, "a_max": a_max, "dn_max": dn, "cells": cells,
            "gain_mode": gmode, "min_seg": cfg.min_seg, "cut_src": cut_src, "n_segs": len(fsegs) if need_A else 0,
            "sec_total": round(el, 1),
            "x_realtime": round((T / fps) / max(el, 1e-9), 2),
            "dst": dst}


# ══════════════════════════════════════════════════════════════ 컷 방안
CUT_PLAYBOOK = """
화면 전환(컷) — 우리 구조로는 못 고친다. 왜, 그리고 무엇이 가능한가
────────────────────────────────────────────────────────────────────────
왜 불가능한가
  매끄러운 곱셈 게인 out = in·g 는 장면 전환을 만들지도 없애지도 못한다.
  컷은 in 자체의 내용이 바뀌는 사건이고 g 는 밝기 배율일 뿐이다.
  공간 대비 축소(B)도 마찬가지 — 프레임 안의 연산이라 프레임 사이 사건에
  손댈 수 없다. (이 성질 덕에 최적화는 하나 얻는다: **컷 판정은 보정 라운드마다
  다시 잴 필요가 없다.** 한 번 재서 캐시한다.)

방안 1 — 크로스디졸브 삽입  [측정 완료. --dissolve N 으로 켠다]
  하드컷을 N프레임 디졸브로 바꾸면 "한 프레임에 80% 가 바뀐다"는 조건이
  깨져 컷으로 세지 않는다. 컷 시각은 pse_cut 이 이미 알려준다.

  **실측 (cutclips/23_cuts_6hz, 30fps)**
      원본        16컷  최대 5/s   위반
      디졸브 2f   16컷  최대 5/s   위반      <- 효과 없음
      디졸브 3f   11컷  최대 4/s   위반      <- 부족
      **디졸브 5f    0컷  최대 0/s   적합**   <- 뒤집힘. BT1702 전체도 적합
  5프레임 = 0.167초. 조명장 FIR 의 지연과 같은 값인데 우연이 아니다 —
  급변으로 안 세이려면 3Hz 한도의 반주기만큼 퍼뜨려야 한다.

  · 장점: 자동화 가능하고, 결과가 '아티팩트'가 아니라 **편집상 정당한 디졸브**다.
          디졸브가 새 플래시를 만들지도 않았다(BT1702 전체 적합).
  · **정직한 비용**: 초당 4~6컷이면 컷 간격이 5~7프레임이라 5프레임 디졸브가
    간격의 대부분을 덮는다. 결과는 '디졸브가 섞인 편집'이 아니라 **연속적으로
    뭉개지는 화면**에 가깝다. 규칙은 통과하지만 편집 의도는 크게 바뀐다.
    그래서 기본값이 아니라 옵션이다.
  · 주의: 휘도가 다른 두 샷이면 디졸브가 램프를 만든다. 램프는 완만해서
          플래시 조건에 안 걸리지만, 파이프라인이 어차피 재판정하므로 걸리면 잡힌다.

방안 2 — 컷 빈도 자체를 낮추기  [자동화 금지]
  초당 6컷을 3컷으로 만들려면 절반의 샷을 버리고 이웃을 늘려야 한다.
  창작 의도를 정면으로 훼손한다. 도구가 임의로 하면 안 된다 — 편집자에게
  "이 구간 컷 밀도를 절반으로" 라고 **제안**하는 데까지가 한계다.

방안 3 — 전역 대비/휘도 축소  [효과 없음, 하지 말 것]
  pse_cut 은 블록별 색 히스토그램 거리로 판정한다. 밝기를 줄여도 색 분포
  차이는 그대로라 컷 수가 안 준다. 화질만 손해다.

방안 4 — 검출해서 편집자에게 넘기기  [기본값, 권장]
  위반 구간을 EDL/마커/CSV 로 내보낸다. Netflix 가 공식 권고하는 remediation
  5가지(편집 리듬 조정 / matte 격리 / 적색 채도 감소 / 면적 축소 / 애니 속도
  감속)가 **전부 수작업**이고, Harding 본사도 '사람 손 수정'을 유상으로 판다.
  즉 이 지점에서 자동화를 포기하는 것은 업계 표준과 같은 선택이다.

권장: 기본은 방안 4. 방안 1 은 --dissolve 옵션으로 두되 **측정으로 검증한 뒤**
      기본값에 넣을 것.
"""


def report(r):
    L = [f"{r['src']}  {r['res']}  {r['frames']}프레임 @ {r['fps']:.0f}fps  (EOTF {r['eotf']})"]
    if r.get("untouched"):
        if r.get("harmed"):
            L.append(f"  보정 불가 — 원본 유지 (원본에 없던 위반 "
                     f"{', '.join(r.get('harm_rules', []))} 발생: {r.get('harm_reason','?')})")
        else:
            L.append("  원본이 이미 적합 — 손대지 않았습니다")
        return "\n".join(L)
    L.append(f"  전  {'적합' if r['before_compliant'] else '위반 — ' + ', '.join(r['before_failed'])}")
    L.append(f"  후  {'적합' if r['after_compliant'] else '위반 — ' + ', '.join(r['after_failed'])}")
    if r["fixed"]:
        L.append(f"  고침      {', '.join(r['fixed'])}")
    if r["unfixable"]:
        L.append(f"  구조상 불가 {', '.join(r['unfixable'])}   <- 아래 방안 참조")
    sp = r.get("touched_space_pct")
    L.append(f"  작동기 {r['actuators']}   화면시간의 {r['touched_time_pct']}% 만 보정"
             + (f"  ·  마스크 {r.get('mask_mode','시간')}"
                + (f" (시공간 화소의 {sp}%)" if sp is not None and r.get('mask_mode') == '공간' else "")))
    L.append(f"  게인 {r.get('gain_mode','-')}  fc {r['fc_hz']}Hz  a {r['a_max']}"
             f"  dn {r['dn_max']}  칸 {r['cells']}")
    L.append(f"  {r['sec_total']}s  ({r['x_realtime']}배속)")
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="규격 게이트 기반 선택적 보정")
    ap.add_argument("src")
    ap.add_argument("dst", nargs="?", default=None)
    ap.add_argument("--width", type=int, default=320)
    ap.add_argument("--eotf", default="bt1886", choices=["bt1886", "srgb"])
    ap.add_argument("--pad", type=float, default=0.5, help="위반 구간 앞뒤 여유(초)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--cut-playbook", action="store_true", help="컷 방안만 출력")
    ap.add_argument("--margin", type=float, default=0.0, metavar="X",
                    help="규격 통과에 그치지 않고 **모든 축**을 한도의 X배 아래로 "
                         "민다 (1.0 = 모든 축이 한도 아래). 기본 0 = 끔")
    ap.add_argument("--no-spatial", action="store_true",
                    help="공간 게이트 끄기 (시간 마스크만 — 구버전 동작)")
    ap.add_argument("--dissolve", type=int, default=0, metavar="N",
                    help="하드컷을 N프레임 디졸브로 (30fps 기준 5 부터 효과. "
                         "편집 의도를 크게 바꾸므로 기본 off)")
    a = ap.parse_args()
    if a.cut_playbook:
        print(CUT_PLAYBOOK)
        raise SystemExit(0)
    r = run(a.src, a.dst, width=a.width, eotf=a.eotf, pad_s=a.pad,
            dissolve=a.dissolve, margin=a.margin,
            spatial=not a.no_spatial)
    print()
    print(json.dumps(r, ensure_ascii=False, indent=1) if a.json else report(r))
    if r.get("unfixable"):
        print(CUT_PLAYBOOK)
