# -*- coding: utf-8 -*-
"""overlay_diff.py — 두 검출기가 **다르게 판정한** 영상을 나란히 오버레이한다.

    python overlay_diff.py --outdir out                # compare19.json 의 불일치 전부
    python overlay_diff.py --outdir out --clip Db4xxxx # 한 편만

왼쪽 = pse_bt1702 가 검출한 화소, 오른쪽 = psecore 가 검출한 화소.
오른쪽 패널에 **두 검출기의 기준(규칙·임계·전처리)** 과 실측값을 같이 적고,
아래 타임라인에 어느 구간에서 갈렸는지 표시한다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# ─────────────────────────────────────────────────────────── 레이아웃 / 색
W, H = 1408, 1024
PANE_W, PANE_H = 330, 560
PANE_Y = 92
PANE_AX, PANE_BX = 20, 366
PANEL_X, PANEL_W = 716, 676
TL_Y = PANE_Y + PANE_H + 48          # 타임라인 트랙 상단
BG = (24, 24, 28)
FG = (235, 235, 240)
DIM = (150, 150, 160)
OK_C = (120, 210, 120)
BAD_C = (70, 70, 240)
WARN_C = (60, 190, 250)

# 채널 색 (BGR)
C_FLASH = (60, 60, 255)      # 빨강   — 휘도 플래시
C_RED = (255, 60, 220)       # 자홍   — 채도 적색
C_PATTERN = (255, 220, 60)   # 하늘   — 패턴
C_RB = (60, 230, 255)        # 노랑   — 적청 교대
C_RGB = (180, 180, 180)      # 회색   — RGB 채널별(warn)
C_CUT = (120, 255, 160)      # 연두   — 화면전환

FONT_PATH = r"C:\Windows\Fonts\malgun.ttf"
FONT_BD = r"C:\Windows\Fonts\malgunbd.ttf"
_FCACHE: dict = {}
_TCACHE: dict = {}


def font(size: int, bold: bool = False):
    k = (size, bold)
    if k not in _FCACHE:
        try:
            _FCACHE[k] = ImageFont.truetype(FONT_BD if bold else FONT_PATH, size)
        except Exception:  # noqa: BLE001
            _FCACHE[k] = ImageFont.load_default()
    return _FCACHE[k]


def text_rgba(s: str, size: int, color, bold: bool = False):
    """작은 텍스트 스프라이트(BGR, alpha) — 프레임마다 캔버스 전체를 PIL 로
    왕복하지 않기 위해 캐시한다."""
    k = (s, size, color, bold)
    if k in _TCACHE:
        return _TCACHE[k]
    f = font(size, bold)
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    box = d.textbbox((0, 0), s, font=f)
    w, h = max(1, int(box[2]) + 2), max(1, int(box[3]) + 3)
    img = Image.new("L", (w, h), 0)
    ImageDraw.Draw(img).text((0, 0), s, font=f, fill=255)
    a = np.asarray(img, np.float32) / 255.0
    col = np.zeros((h, w, 3), np.float32)
    col[:] = np.array(color, np.float32)
    _TCACHE[k] = (col, a[..., None])
    return _TCACHE[k]


def put(canvas, s, x, y, size=15, color=FG, bold=False):
    """캔버스에 텍스트를 알파 합성. y 는 윗변."""
    if not s:
        return y + size + 4
    col, a = text_rgba(s, size, color, bold)
    h, w = a.shape[:2]
    if y + h > canvas.shape[0] or x + w > canvas.shape[1] or x < 0 or y < 0:
        w = min(w, canvas.shape[1] - x)
        h = min(h, canvas.shape[0] - y)
        if w <= 0 or h <= 0:
            return y + size + 4
        col, a = col[:h, :w], a[:h, :w]
    roi = canvas[y:y + h, x:x + w].astype(np.float32)
    canvas[y:y + h, x:x + w] = (roi * (1 - a) + col * a).astype(np.uint8)
    return y + h + 3


def pane_boxes(fw, fh):
    """영상 비율에 맞춘 A/B 상자. 가로 영상이면 위아래로 쌓는다."""
    if fw / max(fh, 1) > 1.2:
        w = PANEL_X - 60
        h = (PANE_H - 34) // 2
        return (20, PANE_Y, w, h), (20, PANE_Y + h + 34, w, h)
    return (PANE_AX, PANE_Y, PANE_W, PANE_H), (PANE_BX, PANE_Y, PANE_W, PANE_H)


def fit(frame, bw, bh):
    """상자 안에 비율 유지로 넣는다. (이미지, x오프셋, y오프셋) 반환."""
    h, w = frame.shape[:2]
    s = min(bw / w, bh / h)
    nw, nh = max(2, int(w * s)), max(2, int(h * s))
    im = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
    return im, (bw - nw) // 2, (bh - nh) // 2


def tint(pane, mask, color, alpha=0.55):
    """마스크 화소를 색으로 물들이고 윤곽선을 그린다."""
    if mask is None or not mask.any():
        return
    m = mask.astype(np.uint8)
    if m.shape[:2] != pane.shape[:2]:
        m = cv2.resize(m, (pane.shape[1], pane.shape[0]),
                       interpolation=cv2.INTER_NEAREST)
    b = m.astype(bool)
    pane[b] = (pane[b].astype(np.float32) * (1 - alpha)
               + np.array(color, np.float32) * alpha).astype(np.uint8)
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(pane, cnts, -1, color, 1)


# ─────────────────────────────────────────────── 기준 표 (두 검출기의 차이)
def bt_rows(bt: dict):
    """[라벨, 실측, 한도, 상태] — pse_bt1702"""
    R = bt.get("rules", {})
    f, rd = R.get("flash", {}), R.get("red", {})
    out = [
        ("① 플래시(휘도)",
         f"{f.get('max_per_sec',0)}회/s · 면적 {f.get('max_area_pct',0):.0f}%",
         "3회/s 초과 & 25% 이상", f.get("pass")),
        ("② 채도 적색",
         f"{rd.get('max_per_sec',0)}회/s · 면적 {rd.get('max_area_pct',0):.0f}%",
         "R/(R+G+B)≥0.8 & Δu'v'≥0.2", rd.get("pass")),
    ]
    if "pattern" in R:
        p = R["pattern"]
        out.append(("③ 패턴",
                    (f"{p.get('max_pairs',0):.0f}쌍 · 면적 {p.get('max_area_pct',0):.0f}%"
                     if p.get("pass") is not None else f"측정불가 {p.get('error','')[:20]}"),
                    "줄무늬 ≥5쌍 & 25% 이상", p.get("pass")))
    out.append(("④ 5초 지속",
                f"최장 {max(f.get('longest_run_s',0) or 0, rd.get('longest_run_s',0) or 0):.1f}s",
                "5초 이상 지속 금지", not bt.get("sustained_over_5s")))
    if "cut" in R:
        c = R["cut"]
        out.append(("⑤ 화면전환",
                    (f"{c.get('max_per_sec',0)}컷/s · 총 {c.get('total_cuts',0)}컷"
                     if c.get("pass") is not None else "측정불가"),
                    f"{c.get('limit_per_sec','3')}컷/s 초과", c.get("pass")))
    fs = bt.get("frame_separation", {})
    obs = fs.get("observed_min_frames")
    out.append(("⑥ 프레임 간격(참고)",
                f"최소 {obs if obs is not None else '-'}f / 필요 {fs.get('required_frames','-')}f",
                "허용 문언 · 판정 제외", None))
    supp = bt.get("supplementary", {}).get("rb", {})
    if supp:
        out.append(("(보조) 적청 교대",
                    f"{supp.get('max_per_sec',0)}회/s · 면적 {supp.get('max_area_pct',0):.0f}%",
                    "규격 밖 · 판정 제외", None))
    return out


PC_LABEL = {"LUM": "휘도 LUM", "RGB": "RGB 채널별", "RED": "채도 적색 RED",
            "RB": "적청 교대 RB"}
PC_CRIT = {"LUM": "Δ 상대휘도 ≥0.10 & 3회/s & 25%",
           "RGB": "채널별 excursion ≥0.10 (warn 전용)",
           "RED": "R/(R+G+B)≥0.8 & Δu'v'≥0.2",
           "RB": "적청 축 투영 ≥0.20 (규격 밖·FAIL 반영)"}


def pc_rows(pc: dict):
    cs = pc.get("channel_seconds", {})
    failed = set(pc.get("failed_channels", []))
    warned = set(pc.get("warn_channels", []))
    best = {}
    for v in pc.get("violations", []) + pc.get("warnings", []):
        m = v["measured"]
        b = best.setdefault(v["channel"], [0, 0.0])
        b[0] = max(b[0], m["flashes_per_sec"])
        b[1] = max(b[1], m["area_ratio"])
    out = []
    for ch in ("LUM", "RED", "RB", "RGB"):
        st = False if ch in failed else ("warn" if ch in warned else True)
        n, ar = best.get(ch, [0, 0.0])
        out.append((PC_LABEL[ch],
                    f"{n}회/s · 면적 {ar*100:.0f}% · {cs.get(ch,0):.1f}s",
                    PC_CRIT[ch], st))
    out.append(("③ 패턴 / ⑤ 화면전환", "채널 없음", "미구현 — 통과시킴", None))
    return out


def diff_reason(bt: dict, pc: dict):
    """왜 갈렸는지 — 실측값을 넣어 자동 진단."""
    bf = set(bt.get("failed_rules", []))
    pf = set(pc.get("failed_channels", []))
    R = bt.get("rules", {})
    cs = pc.get("channel_seconds", {})
    L = []
    bt_bad = bt.get("verdict") == "위반"

    def segtxt(segs, n=2):
        return ", ".join(f"{a:.1f}~{b:.1f}s" for a, b in (segs or [])[:n]) or "-"

    if bt_bad and not pf:
        if "화면전환" in bf:
            c = R.get("cut", {})
            L.append(f"A 만 위반 ⑤화면전환: 최대 {c.get('max_per_sec','?')}컷/s "
                     f"(한도 {c.get('limit_per_sec','3')}) · 위반 {c.get('violation_seconds',0)}s "
                     f"[{segtxt(c.get('segments'))}]. psecore 에는 화면전환 채널이 "
                     f"아예 없어 무조건 통과한다.")
        if "패턴" in bf:
            p = R.get("pattern", {})
            L.append(f"A 만 위반 ③패턴: 최대 {p.get('max_pairs',0):.0f}쌍 · 면적 "
                     f"{p.get('max_area_pct',0):.0f}% · {p.get('violation_seconds',0)}s. "
                     f"psecore 에는 패턴 채널이 없다.")
        if "5초지속" in bf:
            L.append("A 만 위반 ④5초지속: psecore 의 bt1702 프로파일에는 누적 지속 "
                     "조항이 없다(strict 모드 전용).")
        if "플래시" in bf:
            f = R.get("flash", {})
            L.append(f"A 만 위반 ①플래시: {f.get('max_per_sec','?')}회/s · 최대면적 "
                     f"{f.get('max_area_pct',0):.0f}% · {f.get('violation_seconds',0)}s "
                     f"[{segtxt(f.get('segments'))}] — 같은 구간을 psecore 휘도 LUM 은 "
                     f"{cs.get('LUM',0)}s 로 봤다. psecore 는 위상상관 전역 움직임 보상으로 "
                     f"컷·팬의 이동 성분을 먼저 빼고, peak-valley 상태기가 50ms 유효지속을 "
                     f"요구해 짧은 컷 점멸을 '전환'으로 세지 않는다.")
        if "적색" in bf:
            rd = R.get("red", {})
            L.append(f"A 만 위반 ②적색: {rd.get('max_per_sec','?')}회/s · 면적 "
                     f"{rd.get('max_area_pct',0):.0f}%. 임계는 같지만 전환 계수 방식이 "
                     f"다르다(프레임간 이진 마스크 차 vs 히스테리시스 상태기).")
    if not bt_bad and pf:
        best = {}
        for v in pc.get("violations", []):
            m = v["measured"]
            b = best.setdefault(v["channel"], [0, 0.0, v["start"], v["end"]])
            b[0] = max(b[0], m["flashes_per_sec"])
            b[1] = max(b[1], m["area_ratio"])
        if "LUM" in pf:
            n, ar, s0, s1 = best.get("LUM", [0, 0, "-", "-"])
            f = R.get("flash", {})
            L.append(f"B 만 위반 휘도 LUM: {s0[3:]}~{s1[3:]} 에서 {n}회/s · 면적 "
                     f"{ar*100:.0f}% (한도 3회/s & 25%). 같은 영상을 A 는 최대면적 "
                     f"{f.get('max_area_pct',0):.0f}% 로 재서 통과시켰다 — A 는 시퀀스 "
                     f"화소 교집합이 25% 아래로 떨어지면 시퀀스를 끊어 '같은 화소가 "
                     f"번쩍인 면적'만 인정하고, psecore 는 20ms 동기화 그룹 안의 전환 "
                     f"화소를 합산한다(분석 해상도도 320px vs 짧은변 240px 로 다르다).")
        if "RB" in pf:
            n, ar, s0, s1 = best.get("RB", [0, 0, "-", "-"])
            supp = bt.get("supplementary", {}).get("rb", {})
            L.append(f"B 만 위반 적청 교대 RB: {n}회/s · 면적 {ar*100:.0f}%. 이 축은 "
                     f"BT.1702 규격에 없다 — pse_bt1702 는 같은 축을 보조 지표로만 재고"
                     f"(실측 {supp.get('max_per_sec',0)}회/s · "
                     f"{supp.get('max_area_pct',0):.0f}%) 판정에 넣지 않는다. "
                     f"psecore 는 chroma_mode=fail 로 판정에 반영한다.")
        if "RED" in pf:
            n, ar, s0, s1 = best.get("RED", [0, 0, "-", "-"])
            rd = R.get("red", {})
            L.append(f"B 만 위반 채도 적색 RED: {n}회/s · 면적 {ar*100:.0f}%. A 의 "
                     f"②적색은 {rd.get('max_per_sec','?')}회/s · "
                     f"{rd.get('max_area_pct',0):.0f}% 로 통과했다.")
        if "RGB" in pf:
            L.append("B 만 위반 RGB 채널별: 표준 밖 축이다(pse_bt1702 에는 없다).")
    if not L:
        L.append("규칙 단위로는 같은 축이 걸렸지만 임계 근처에서 갈렸다.")
    return L


# ────────────────────────────────────────────────────────── 정적 패널 렌더
def build_panel(canvas, bt, pc, clip):
    x = PANEL_X
    y = PANE_Y
    put(canvas, "판정 기준 비교", x, y, 20, FG, True)
    y += 30
    cv2.line(canvas, (x, y), (x + PANEL_W - 8, y), (70, 70, 80), 1)
    y += 8

    def block(title, sub, rows, y):
        y = put(canvas, title, x, y, 16, (250, 200, 120), True)
        y = put(canvas, sub, x, y, 12, DIM)
        y += 3
        for lab, meas, crit, st in rows:
            c = {True: OK_C, False: BAD_C, "warn": WARN_C}.get(st, DIM)
            mark = {True: "적합", False: "위반", "warn": "주의"}.get(st, "—")
            put(canvas, lab, x + 4, y, 13, FG)
            put(canvas, meas, x + 168, y, 13, c)
            put(canvas, mark, x + PANEL_W - 40, y, 13, c, True)
            y = put(canvas, crit, x + 168, y + 15, 11, DIM) - 12
            y += 8
        return y + 6

    y = block(f"검출기 A · pse_bt1702  →  {bt.get('verdict','?')} ({bt.get('tier','')})",
              "ITU-R BT.1702 정본 · 분석폭 320px · 움직임보상 없음 · 화소동일성(교집합 25%) · 시퀀스 334/360ms 분할",
              bt_rows(bt), y)
    cv2.line(canvas, (x, y), (x + PANEL_W - 8, y), (70, 70, 80), 1)
    y += 10
    y = block(f"검출기 B · psecore v2.0  →  {pc.get('verdict','?')}",
              "bt1702 프로파일 · 짧은변 240px · 전역 움직임보상 ON · peak-valley 상태기(유효 50ms) · 동기화 20ms · 갭예외 334ms",
              pc_rows(pc), y)
    return y


def draw_reasons(canvas, bt, pc, y):
    """왜 갈렸나 — 타임라인 아래 전폭으로."""
    x = 24
    cv2.line(canvas, (x, y - 10), (W - 24, y - 10), (70, 70, 80), 1)
    y = put(canvas, "왜 갈렸나 — 두 검출기의 규칙 집합이 다르다", x, y, 15,
            (250, 200, 120), True)
    for s in diff_reason(bt, pc):
        for j, line in enumerate(wrap(s, 106)):
            y = put(canvas, ("• " if j == 0 else "   ") + line, x + 4, y, 12, FG)
        y += 2
    return y


def wrap(s, n):
    out, cur = [], ""
    for w in s.split(" "):
        if len(cur) + len(w) + 1 > n:
            out.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        out.append(cur)
    return out


def build_timeline(canvas, bt, pc, dur):
    """두 검출기의 위반 구간을 트랙으로 그린다. 트랙 y 좌표 목록을 돌려준다."""
    x0, x1 = 24, W - 24
    y = TL_Y
    put(canvas, "위반 구간 타임라인  (A = pse_bt1702, B = psecore)", x0, y - 48,
        15, FG, True)
    tracks = []

    def track(label, segs, color, y):
        put(canvas, label, x0, y - 1, 12, DIM)
        bx0 = x0 + 150
        cv2.rectangle(canvas, (bx0, y), (x1, y + 14), (48, 48, 56), -1)
        for a, b in segs:
            xa = int(bx0 + (x1 - bx0) * min(max(a / dur, 0), 1))
            xb = int(bx0 + (x1 - bx0) * min(max(b / dur, 0), 1))
            cv2.rectangle(canvas, (xa, y), (max(xb, xa + 2), y + 14), color, -1)
        tracks.append((y, bx0, x1))
        return y + 20

    R = bt.get("rules", {})
    y = track("A ① 플래시", R.get("flash", {}).get("segments", []) or [], C_FLASH, y)
    y = track("A ② 적색", R.get("red", {}).get("segments", []) or [], C_RED, y)
    if "pattern" in R:
        y = track("A ③ 패턴", R["pattern"].get("segments", []) or [], C_PATTERN, y)
    if "cut" in R:
        y = track("A ⑤ 화면전환", R["cut"].get("segments", []) or [], C_CUT, y)
    y += 6
    bych: dict = {}
    for v in pc.get("violations", []):
        bych.setdefault(v["channel"], []).append(
            (_sec(v["start"]), _sec(v["end"])))
    for ch, col in (("LUM", C_FLASH), ("RED", C_RED), ("RB", C_RB)):
        y = track(f"B {PC_LABEL[ch]}", bych.get(ch, []), col, y)
    return tracks, x0 + 150, x1


def _sec(tc: str) -> float:
    h, m, s = tc.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


# ─────────────────────────────────────────────────────────────────── 본체
def make_overlay(clip, row, outdir, width=320, max_sec=None):
    import pse_bt1702 as BT
    import psecore as PC

    src = row["path"]
    if not os.path.exists(src):
        src = os.path.join(HERE, row["path"])
    bt, pc = row["bt"], row["pc"]

    print(f"  · 마스크 재계산 (BT)…", flush=True)
    rb = BT.analyze(src, width=width, keep_masks=True)
    sp = rb.get("_spatial") or {}
    print(f"  · 마스크 재계산 (psecore)…", flush=True)
    rep, pmask = PC.analyze(src, PC.PROFILES["bt1702"], profile_name="bt1702",
                            want_masks=True)

    cap = cv2.VideoCapture(src)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n_bt = int(sp.get("flash").shape[0]) if sp.get("flash") is not None else 0
    n_pc = len(pmask["LUM"])
    dur = max(bt.get("duration_s", 0), n_pc / fps)

    # 정적 캔버스
    base = np.full((H, W, 3), BG, np.uint8)
    put(base, f"{clip}", 20, 16, 22, FG, True)
    put(base, f"두 검출기 판정 불일치  —  A(pse_bt1702) {bt.get('verdict')}  vs  "
              f"B(psecore) {pc.get('verdict')}", 20, 48, 15, (120, 200, 255))
    put(base, f"{int(dur)}s · {fps:.0f}fps", W - 130, 20, 13, DIM)
    build_panel(base, bt, pc, clip)
    tracks, tx0, tx1 = build_timeline(base, bt, pc, max(dur, 0.001))
    draw_reasons(base, bt, pc, TL_Y + 20 * len(tracks) + 28)

    # 화면 패널 상자 (영상 비율에 맞춤)
    okf, f0 = cap.read()
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    fh, fw = f0.shape[:2] if okf else (16, 9)
    boxA, boxB = pane_boxes(fw, fh)
    put(base, "A · pse_bt1702 가 검출한 화소", boxA[0], boxA[1] - 22, 14,
        (120, 200, 255), True)
    put(base, "B · psecore 가 검출한 화소", boxB[0], boxB[1] - 22, 14,
        (120, 255, 200), True)

    # 범례 — 타임라인 제목 아래 줄, 왼쪽 정렬(오른쪽 기준표와 겹치지 않게)
    lx, ly = 24, TL_Y - 26
    for lab, col in [("① 플래시/휘도", C_FLASH), ("② 적색", C_RED),
                     ("③ 패턴", C_PATTERN), ("⑤ 화면전환", C_CUT),
                     ("RB 적청", C_RB), ("RGB(warn)", C_RGB)]:
        cv2.rectangle(base, (lx, ly + 3), (lx + 10, ly + 12), col, -1)
        put(base, lab, lx + 14, ly, 11, DIM)
        lx += 22 + text_rgba(lab, 11, DIM)[0].shape[1]
    put(base, "  (진한 색 = 지금 위반에 기여 중 · 옅은 색 = 검출은 됐지만 한도 미달)",
        lx, ly, 11, (110, 110, 120))

    outp = os.path.join(outdir, f"overlay_{clip}.mp4")
    vw = cv2.VideoWriter(outp, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    if not vw.isOpened():
        raise IOError("VideoWriter 를 열 수 없습니다")

    still_saved = False
    cv = base
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if max_sec and i / fps > max_sec:
            break
        cv = base.copy()
        t = i / fps

        # ── A 패널.  **판정에 실제로 기여 중인** 규칙만 진하게, 나머지는 옅게.
        #    (⑥프레임간격은 BT.1702 허용 문언이라 위반 표시에서 뺀다)
        pa, ax, ay = fit(frame, boxA[2], boxA[3])
        a_act = [r["rule"] for r in bt.get("violation_segments", [])
                 if r["start_s"] <= t <= r["end_s"] and r["rule"] != "프레임간격"]
        if i < n_bt:
            tint(pa, np.asarray(sp["flash"][i], np.float32) > 0.05, C_FLASH,
                 0.55 if "플래시" in a_act else 0.20)
            tint(pa, np.asarray(sp["red"][i], np.float32) > 0.05, C_RED,
                 0.55 if "적색" in a_act else 0.20)
            if sp.get("pattern") is not None and i < len(sp["pattern"]):
                tint(pa, np.asarray(sp["pattern"][i], np.float32) > 0.05, C_PATTERN,
                     0.45 if "패턴" in a_act else 0.16)
        _place(cv, pa, boxA[0] + ax, boxA[1] + ay, a_act, (120, 200, 255))

        # ── B 패널
        pb, bx, by = fit(frame, boxB[2], boxB[3])
        b_ch = {v["channel"] for v in pc.get("violations", [])
                if _sec(v["start"]) <= t <= _sec(v["end"])}
        if i < n_pc:
            tint(pb, pmask["RGB"][i], C_RGB, 0.16)
            tint(pb, pmask["RB"][i], C_RB, 0.45 if "RB" in b_ch else 0.18)
            tint(pb, pmask["RED"][i], C_RED, 0.55 if "RED" in b_ch else 0.20)
            tint(pb, pmask["LUM"][i], C_FLASH, 0.55 if "LUM" in b_ch else 0.20)
        b_act = [PC_LABEL[c] for c in ("LUM", "RED", "RB", "RGB") if c in b_ch]
        _place(cv, pb, boxB[0] + bx, boxB[1] + by, b_act, (120, 255, 200))

        # ── 재생 헤드
        px = int(tx0 + (tx1 - tx0) * min(t / max(dur, 1e-6), 1.0))
        cv2.line(cv, (px, TL_Y - 6), (px, TL_Y + 20 * len(tracks) + 14),
                 (255, 255, 255), 1)
        put(cv, f"{t:6.2f}s", W - 130, 44, 13, FG)

        vw.write(cv)
        if not still_saved and (a_act or b_act) and bool(a_act) != bool(b_act):
            cv2.imwrite(os.path.join(outdir, f"overlay_{clip}_still.png"), cv)
            still_saved = True
        i += 1
    cap.release()
    vw.release()
    if not still_saved:
        cv2.imwrite(os.path.join(outdir, f"overlay_{clip}_still.png"), cv)
    return outp


def _place(canvas, pane, x, y, active, col):
    h, w = pane.shape[:2]
    canvas[y:y + h, x:x + w] = pane
    if active:
        cv2.rectangle(canvas, (x - 2, y - 2), (x + w + 1, y + h + 1), col, 3)
        put(canvas, " / ".join(dict.fromkeys(active))[:34], x + 4, y + 4, 13, col, True)
    else:
        cv2.rectangle(canvas, (x - 2, y - 2), (x + w + 1, y + h + 1), (70, 70, 80), 1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="out")
    ap.add_argument("--clip", default=None, help="특정 클립만")
    ap.add_argument("--width", type=int, default=320)
    ap.add_argument("--max-sec", type=float, default=None)
    a = ap.parse_args()

    agg = os.path.join(a.outdir, "compare19.json")
    if os.path.exists(agg):
        rows = json.load(open(agg, encoding="utf-8"))
    else:   # 아직 집계 전이면 개별 json 을 모은다
        import glob as _g
        rows = [json.load(open(p, encoding="utf-8"))
                for p in sorted(_g.glob(os.path.join(a.outdir, "json", "*.json")))]
    tgt = [r for r in rows if r.get("agree") is False]
    if a.clip:
        tgt = [r for r in rows if r["clip"] == a.clip]
    if not tgt:
        print("불일치 영상이 없습니다.")
        raise SystemExit(0)
    print(f"불일치 {len(tgt)}편: " + ", ".join(r["clip"] for r in tgt))
    for r in tgt:
        print(f"── {r['clip']}", flush=True)
        p = make_overlay(r["clip"], r, a.outdir, a.width, a.max_sec)
        print(f"   -> {p}", flush=True)
