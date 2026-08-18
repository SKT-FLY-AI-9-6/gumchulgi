# -*- coding: utf-8 -*-
"""4패널 비교 영상 + A 변화 증폭 영상.

  패널 1  ORIGINAL
  패널 2  A (ours)      <- 현재 코드 (수정 5개 반영)
  패널 3  D ste
  패널 4  D full

그리고 별도로 A 가 **무엇을 건드렸는지** 보이게 차이를 증폭한 영상을 만든다.
A 는 평균 화소차가 255 중 9 정도라 나란히 놓으면 안 보이는 게 정상이다 —
없어진 건 화면 디테일이 아니라 '깜빡임'이고 그건 재생 중에만 보인다.
"""
import os, sys, subprocess, tempfile
sys.path.insert(0, os.getcwd())
import cv2, numpy as np
import psecore as PC, pseenv as ENV, pselive3 as P3, rawmeasure as RM
import psegpu_full as PGF

NAMES = sys.argv[1:] or ["cera_khin", "travis_fein", "anime"]
OUT = "_sbs2"
os.makedirs(OUT, exist_ok=True)
AMP = 6                      # 차이 증폭 배율


def read_all(p):
    cap = cv2.VideoCapture(p); fps = cap.get(cv2.CAP_PROP_FPS) or 30.0; fr = []
    while True:
        ok, f = cap.read()
        if not ok: break
        fr.append(f)
    cap.release(); return fr, fps


def judge(frames, fps):
    q = ENV.tmp("mc.mkv"); RM.write_lossless(frames, q, fps)
    r = PC.analyze(q, PC.PROFILES["bt1702"]); os.remove(q)
    return sum(r.channel_seconds().values())


def encode(frames, path, fps):
    h, w = frames[0].shape[:2]
    tmp = os.path.join(tempfile.gettempdir(), "_mc_raw.mp4")
    vw = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for f in frames:
        vw.write(f)
    vw.release()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp, "-c:v", "libx264",
                    "-crf", "18", "-pix_fmt", "yuv420p", path], check=True)
    os.remove(tmp)


def panel(frames, label, h, w):
    out = []
    bar = 34
    for f in frames:
        p = cv2.resize(f, (w, h))
        img = np.vstack([np.full((bar, w, 3), 24, np.uint8), p])
        cv2.putText(img, label, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 2, cv2.LINE_AA)
        out.append(img)
    return out


print(f"{'릴스':<14}{'원본초':>8}{'A후':>7}{'제거초':>8}{'제거%':>7}")
summary = []
for n in NAMES:
    src = f"_dfull/{n}_360.mp4"
    fr, fps = read_all(src)
    v0 = judge(fr, fps)
    _, oa = PGF.run(src, P3.Cfg(), PGF.OptF(), warmup=2)
    v1 = judge(oa, fps)
    print(f"{n:<14}{v0:>8.2f}{v1:>7.2f}{v0-v1:>8.2f}{(1-v1/max(v0,1e-9))*100:>6.0f}%",
          flush=True)
    summary.append((n, v0, v1))

    dste, _ = read_all(f"_3way/{n}_Dste.mp4")
    dfull, _ = read_all(f"_dfull/{n}_360_Dfull.mp4")
    N = min(len(fr), len(oa), len(dste), len(dfull))
    h = 420
    w = max(2, int(round(h * fr[0].shape[1] / fr[0].shape[0])))
    cols = [panel(fr[:N], "ORIGINAL", h, w), panel(oa[:N], "A (ours)", h, w),
            panel(dste[:N], "D ste", h, w), panel(dfull[:N], "D full", h, w)]
    gap = np.full((h + 34, 4, 3), 24, np.uint8)
    rows = [np.hstack([c[i] if j == 0 else np.hstack([gap, c[i]])
                       for j, c in enumerate(cols)]) for i in range(N)]
    encode(rows, os.path.join(OUT, f"compare4_{n}.mp4"), fps)
    print(f"   -> {OUT}/compare4_{n}.mp4", flush=True)

    # A 가 건드린 것 — 차이 증폭
    dif = []
    for a, b in zip(fr[:N], oa[:N]):
        d = np.clip(np.abs(a.astype(np.int16) - b.astype(np.int16)) * AMP, 0, 255).astype(np.uint8)
        dif.append(d)
    cols2 = [panel(fr[:N], "ORIGINAL", h, w), panel(oa[:N], "A (ours)", h, w),
             panel(dif, f"DIFF x{AMP}", h, w)]
    rows2 = [np.hstack([c[i] if j == 0 else np.hstack([gap, c[i]])
                        for j, c in enumerate(cols2)]) for i in range(N)]
    encode(rows2, os.path.join(OUT, f"diff_{n}.mp4"), fps)
    print(f"   -> {OUT}/diff_{n}.mp4", flush=True)

print("\n── 제거한 위반 시간 ──")
t0 = sum(s[1] for s in summary); t1 = sum(s[2] for s in summary)
for n, a, b in summary:
    print(f"  {n:<14} {a:6.2f}초 -> {b:5.2f}초   ({a-b:.2f}초 제거)")
print(f"  {'합계':<14} {t0:6.2f}초 -> {t1:5.2f}초   ({t0-t1:.2f}초 제거, {(1-t1/max(t0,1e-9))*100:.1f}%)")
