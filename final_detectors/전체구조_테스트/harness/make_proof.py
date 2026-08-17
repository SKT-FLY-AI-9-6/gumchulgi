# -*- coding: utf-8 -*-
"""'필터가 실제로 무엇을 했는가'를 눈으로 보이게 하는 증거 영상.

A 는 화면 디테일을 안 건드리는 게 설계라 나란히 놓으면 차이가 안 보인다.
없어진 건 **깜빡임**이고 그건 시간축 현상이다. 그래서 화면 아래에
**프레임별 휘도 그래프**를 그린다 — 원본(빨강)은 톱니처럼 튀고 A(초록)는
평탄해야 한다. 그게 필터가 한 일이다.

위반이 가장 심한 구간을 골라 그 부분만 자른다.
"""
import os, sys, subprocess, tempfile
sys.path.insert(0, os.getcwd())
import cv2, numpy as np
import psecore as PC, pselive3 as P3, psegpu_full as PGF

NAMES = sys.argv[1:] or ["travis_fein", "cera_khin"]
OUT = "_proof"
os.makedirs(OUT, exist_ok=True)
SEC = 6                       # 잘라낼 길이(초)
GH = 150                      # 그래프 높이


def read_all(p):
    cap = cv2.VideoCapture(p); fps = cap.get(cv2.CAP_PROP_FPS) or 30.0; fr = []
    while True:
        ok, f = cap.read()
        if not ok: break
        fr.append(f)
    cap.release(); return fr, fps


def lum(frames):
    out = []
    for f in frames:
        lin = PC._LIN[f].astype(np.float32)
        out.append(float((lin[..., 0]*0.0722 + lin[..., 1]*0.7152
                          + lin[..., 2]*0.2126).mean()))
    return np.array(out)


def encode(frames, path, fps):
    h, w = frames[0].shape[:2]
    tmp = os.path.join(tempfile.gettempdir(), "_pf.mp4")
    vw = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for f in frames:
        vw.write(f)
    vw.release()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp, "-c:v", "libx264",
                    "-crf", "18", "-pix_fmt", "yuv420p", path], check=True)
    os.remove(tmp)


for n in NAMES:
    src = f"_dfull/{n}_360.mp4"
    fr, fps = read_all(src)
    _, oa = PGF.run(src, P3.Cfg(), PGF.OptF(), warmup=2)
    N = min(len(fr), len(oa))
    y0, y1 = lum(fr[:N]), lum(oa[:N])

    # 원본 휘도 변동이 가장 큰 구간을 고른다 = 점멸이 가장 심한 곳
    win = int(SEC * fps)
    d = np.abs(np.diff(y0, prepend=y0[0]))
    roll = np.convolve(d, np.ones(win), mode="valid")
    s = int(roll.argmax()); e = min(s + win, N)
    print(f"{n}: {N}프레임 중 {s/fps:.1f}~{e/fps:.1f}초 구간 선택 "
          f"(원본 휘도 변동 최대)", flush=True)

    h, w = fr[0].shape[:2]
    ph = 420
    pw = max(2, int(round(ph * w / h)))
    bar = 34
    frames = []
    ys0, ys1 = y0[s:e], y1[s:e]
    lo = min(ys0.min(), ys1.min()); hi = max(ys0.max(), ys1.max())
    rng = max(hi - lo, 1e-6)
    for i in range(e - s):
        a = cv2.resize(fr[s + i], (pw, ph))
        b = cv2.resize(oa[s + i], (pw, ph))
        top = []
        for img, lab in ((a, "ORIGINAL"), (b, "A (ours)")):
            t = np.vstack([np.full((bar, pw, 3), 24, np.uint8), img])
            cv2.putText(t, lab, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                        (255, 255, 255), 2, cv2.LINE_AA)
            top.append(t)
        gap = np.full((ph + bar, 4, 3), 24, np.uint8)
        row = np.hstack([top[0], gap, top[1]])
        W = row.shape[1]

        g = np.full((GH, W, 3), 18, np.uint8)
        for k in range(1, i + 1):
            for ser, col in ((ys0, (60, 60, 255)), (ys1, (80, 255, 80))):
                x0 = int((k - 1) / max(e - s - 1, 1) * (W - 1))
                x1 = int(k / max(e - s - 1, 1) * (W - 1))
                p0 = GH - 12 - int((ser[k - 1] - lo) / rng * (GH - 26))
                p1 = GH - 12 - int((ser[k] - lo) / rng * (GH - 26))
                cv2.line(g, (x0, p0), (x1, p1), col, 2, cv2.LINE_AA)
        cv2.putText(g, "frame luminance:  ORIGINAL", (8, 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (60, 60, 255), 1, cv2.LINE_AA)
        cv2.putText(g, "A (ours)", (245, 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (80, 255, 80), 1, cv2.LINE_AA)
        frames.append(np.vstack([row, g]))

    p = os.path.join(OUT, f"proof_{n}.mp4")
    encode(frames, p, fps)
    sd0, sd1 = float(np.std(np.diff(ys0))), float(np.std(np.diff(ys1)))
    print(f"   -> {p}   프레임간 휘도변동 표준편차  원본 {sd0:.5f} -> A {sd1:.5f} "
          f"({(1-sd1/max(sd0,1e-9))*100:.0f}% 감소)", flush=True)
