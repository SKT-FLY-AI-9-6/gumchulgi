# -*- coding: utf-8 -*-
"""ghost_ab_demo.py — 잔상 대책 실측 비교 + 비교영상(SBS) 제작.

"잔상을 어떤 방식으로 잡을 수 있나"를 합성 클립 2개로 눈과 수치 양쪽에서 보인다.
클립은 잔상이 가장 심하게 나오는 두 상황을 겨냥한다:

  v_ghost_strobe  스트로브 아래 움직이는 피사체 (점멸 + 움직임이 같은 곳에서
                  동시에 — Kim&Moon 이 "게이트로는 못 가른다"고 결론낸 그 상황)
  v_ghost_spin    점멸 없는 핀휠 회전+피사체 움직임 (원본 적합 — 필터가 움직임을
                  플래시로 오인해 불필요 개입하는지, 순방향 관문이 막는지)
  v_ghost_cuts    초당 4~6회 비주기 컷 연타 (화면전환 위반 — 게인 필터가
                  원리상 못 고치고, 컷 리셋 경계에 잔상이 남는 상황)

변형 (전부 CPU, pselive3):
  A현행       fix 브랜치 기본값 (detail_sigma 2, net_directional off)
  A+순방향     net_directional=True   [seunghoon: 헤일로 35.6->9.4, 악화 4/8->0/8]
  A+detail32  detail_sigma=32        [seunghoon: 유령 얼굴 1/6, 점멸 억제 -2%p]
  A+둘다      위 둘 동시
  디졸브5f/8f  psepipe --dissolve N   [컷 클립만 — 화면전환 축의 정공법.
              합성 극단 컷(Δ휘도 대)은 5f 로 부족하고 8f 에서 해소된다]

측정: 심판 pse_bt1702 판정(전/후) + seam 3축(펌핑/헤일로/잔상 lag·drag,
인코딩 대조군 초과분). 승자 규칙은 compare_ad 와 같은 이유로 여기서도 없다 —
판정을 지키는 변형끼리 잔상축을 비교해서 읽는다.

사용:
    python ghost_ab_demo.py [--outdir _ghost_demo] [--height 360] [--seconds 6]

출력: 비교표(stdout, markdown) + ghost_ab_demo.csv + SBS 영상 2개.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pse_bt1702 as BT
import psepipe as PP
import pselive3 as P3
import seam

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_sbs

FPS = 30
W, H = 640, 360


# ──────────────────────────────────────────────────────────── 합성 클립
def _scene(rng, mean=110, amp=60):
    """질감 있는 배경 한 장 — 장면마다 명암 파형·위상·색조가 다르게."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    fx, fy = rng.uniform(30, 150), rng.uniform(25, 120)
    px, py = rng.uniform(0, 6.28), rng.uniform(0, 6.28)
    base = mean + amp * np.sin(xx / fx + px) * np.cos(yy / fy + py)
    tex = rng.normal(0, 14, (H, W)).astype(np.float32)
    tex = cv2.GaussianBlur(tex, (0, 0), 1.2)
    g = np.clip(base + tex, 0, 255)
    tb, tg, tr = rng.uniform(0.72, 1.25, 3)
    return cv2.merge([g * tb, g * tg, g * tr]).astype(np.float32)


def _figure(rng):
    """움직이는 피사체 — 질감 있는 타원 (사람 어깨~머리 실루엣 근사)."""
    fh, fw = 140, 90
    yy, xx = np.mgrid[0:fh, 0:fw].astype(np.float32)
    mask = (((xx - fw / 2) / (fw / 2)) ** 2 + ((yy - fh / 2) / (fh / 2)) ** 2) <= 1.0
    tex = 150 + 55 * np.sin(yy / 6.0) * np.cos(xx / 9.0) \
        + rng.normal(0, 10, (fh, fw)).astype(np.float32)
    body = cv2.merge([tex * 1.05, tex * 0.85, tex * 0.7]).astype(np.float32)
    return body, mask


def _write(path, frames):
    tmp = path + ".raw.mp4"
    vw = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    for f in frames:
        vw.write(f)
    vw.release()
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp,
                    "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", path],
                   check=True)
    os.remove(tmp)
    return path


def make_strobe_clip(path, seconds):
    """전화면 5Hz 스트로브 + 가로지르는 질감 피사체."""
    rng = np.random.default_rng(7)
    bg = _scene(rng)
    body, mask = _figure(rng)
    n = seconds * FPS
    frames = []
    for t in range(n):
        f = bg.copy()
        x = int((W - 90) * (0.5 + 0.45 * np.sin(2 * np.pi * t / (2.2 * FPS))))
        y = int(H * 0.28 + 18 * np.sin(2 * np.pi * t / (0.9 * FPS)))
        roi = f[y:y + 140, x:x + 90]
        roi[mask] = body[mask]
        # 스트로브: 3프레임 점등 / 3프레임 소등 = 5Hz, 전화면 (면적 100%)
        gain = 1.0 if (t // 3) % 2 == 0 else 0.13
        frames.append(np.clip(f * gain, 0, 255).astype(np.uint8))
    return _write(path, frames)


def make_spin_clip(path, seconds):
    """점멸 없음 — 고대비 핀휠(방사 줄무늬 8개) 회전 + 피사체 이동. 화소 단위로는
    줄무늬가 지나가며 밝↔어둠이 ~2.5Hz 로 교대해 플래시의 정의를 만족하지만,
    밝아진 면적과 어두워진 면적이 맞먹어 순방향(net) 관점에서는 상쇄된다.
    심판(pse_bt1702)은 net 관문으로 이걸 거르는데 필터(psecore)에는 그 관문이
    없다 — seunghoon 이 실사 릴스에서 잡은 '움직임을 플래시로 오인' 상황의
    합성 재현이다. 전역 평행이동 보상(위상상관)은 회전을 못 막는다."""
    rng = np.random.default_rng(23)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    theta = np.arctan2(yy - H / 2, xx - W / 2)
    body, mask = _figure(rng)
    n = seconds * FPS
    frames = []
    omega = 2 * np.pi * 0.31                        # 0.31 회전/s × 8줄 ≈ 2.5Hz 교대
    for t in range(n):
        g = 130 + 95 * np.sin(8 * theta + omega * t / FPS * 8)
        f = cv2.merge([g * 0.95, g, g * 1.02]).astype(np.float32)
        x = int((W - 90) * (0.5 + 0.42 * np.sin(2 * np.pi * t / (1.6 * FPS))))
        y = int(H * 0.3)
        roi = f[y:y + 140, x:x + 90]
        roi[mask] = body[mask]
        frames.append(np.clip(f, 0, 255).astype(np.uint8))
    return _write(path, frames)


CUT_LENS = [6, 8, 7, 6, 9, 7, 6, 8, 7, 6]   # 비주기 (평균 ~7f = 4.3컷/s > 한도 3)


def make_cuts_clip(path, seconds):
    """초당 4~6회 비주기 컷 — 샷마다 **새 장면**(밝↔어둠 교대), 자체 움직임 포함.
    같은 장면을 순환시키면 pse_cut 의 왕복 배제가 컷으로 안 세므로(설계대로)
    모든 샷을 새 장면으로 만든다. 주기 컷은 적응 기준선이 흡수하므로 비주기."""
    rng = np.random.default_rng(11)
    body, mask = _figure(rng)
    n = seconds * FPS
    frames = []
    t = 0; seg = 0
    while t < n:
        mean = 200 - 165 * (seg % 2) + rng.integers(-15, 15)   # 밝↔어둠 크게 교대
        f0 = _scene(np.random.default_rng(100 + seg), mean=mean,
                    amp=int(rng.integers(25, 70)))
        for _ in range(CUT_LENS[seg % len(CUT_LENS)]):
            if t >= n:
                break
            f = f0.copy()
            x = int((W - 90) * (0.5 + 0.4 * np.sin(2 * np.pi * (t + seg * 13) / (1.7 * FPS))))
            y = int(H * 0.3)
            roi = f[y:y + 140, x:x + 90]
            roi[mask] = body[mask]
            frames.append(np.clip(f, 0, 255).astype(np.uint8))
            t += 1
        seg += 1
    return _write(path, frames)


# ──────────────────────────────────────────────────────────── 실행/측정
def run_live(src, dst, **cfg_kw):
    c = P3.Cfg()
    for k, v in cfg_kw.items():
        setattr(c, k, v)
    rep, _ = P3.run(src, c, video_out=dst, verbose=False)
    return rep


def judge(path, width=320):
    return BT.analyze(path, width=width)["failed_rules"]


def row_measure(name, src, out, ctrl, before, sec):
    m = seam.measure(src, out)
    b = seam.measure(src, ctrl)
    return {
        "변형": name, "전": ",".join(before) or "-",
        "후": ",".join(judge(out)) or "적합",
        "펌핑+": round(max(m["pumping"] - b["pumping"], 0.0), 3),
        "헤일로+": round(max(m["halo"] - b["halo"], 0.0), 2),
        "잔상lag": round(m["ghost_lag"], 2),
        "잔상drag+": round(max(m["ghost_drag"] - b["ghost_drag"], 0.0), 3),
        "초": round(sec, 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="_ghost_demo")
    ap.add_argument("--seconds", type=int, default=6)
    ap.add_argument("--height", type=int, default=360)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    P = lambda *x: os.path.join(a.outdir, *x)

    print("── 합성 클립 생성", flush=True)
    src1 = make_strobe_clip(P("v_ghost_strobe.mp4"), a.seconds)
    src2 = make_spin_clip(P("v_ghost_spin.mp4"), a.seconds)
    src3 = make_cuts_clip(P("v_ghost_cuts.mp4"), a.seconds)

    rows = []
    for src, variants in (
        (src1, [("A현행", {}),
                ("A+순방향", {"net_directional": True}),
                ("A+detail32", {"detail_sigma": 32.0}),
                ("A+둘다", {"net_directional": True, "detail_sigma": 32.0})]),
        (src2, [("A현행", {}),
                ("A+순방향", {"net_directional": True})]),
        (src3, [("A현행", {}),
                ("디졸브5f", {"_dissolve": 5}),
                ("디졸브8f", {"_dissolve": 8})]),
    ):
        name = os.path.splitext(os.path.basename(src))[0]
        before = judge(src)
        print(f"── {name}  위반: {before}", flush=True)
        ctrl = P(name + "_ctrl.mp4")
        if not os.path.exists(ctrl):
            seam.make_control(src, ctrl)
        arms = [("ORIGINAL", src)]
        for label, kw in variants:
            out = P(f"{name}_{label}.mp4")
            t0 = time.time()
            if "_dissolve" in kw:
                PP.run(src, out, verbose=False, dissolve=kw["_dissolve"])
            else:
                run_live(src, out, **kw)
            r = row_measure(label, src, out, ctrl, before, time.time() - t0)
            r["clip"] = name
            rows.append(r)
            arms.append((label.replace("현행", " base").replace("+순방향", "+netdir")
                              .replace("+둘다", "+both")
                              .replace("디졸브5f", "DISSOLVE 5f")
                              .replace("디졸브8f", "DISSOLVE 8f"),
                         out))
            print(f"   {label:<12} 후 {r['후']:<18} 잔상 {r['잔상lag']}/{r['잔상drag+']}",
                  flush=True)
        sbs = P(name + "_sbs.mp4")
        make_sbs.build(sbs, arms, height=a.height)
        print(f"   SBS -> {sbs}", flush=True)

    cols = ["clip", "변형", "전", "후", "펌핑+", "헤일로+", "잔상lag", "잔상drag+", "초"]
    print("\n" + " | ".join(cols))
    print(" | ".join(["---"] * len(cols)))
    for r in rows:
        print(" | ".join(str(r.get(c, "-")) for c in cols))
    with open(P("ghost_ab_demo.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"\nCSV -> {P('ghost_ab_demo.csv')}")


if __name__ == "__main__":
    main()
