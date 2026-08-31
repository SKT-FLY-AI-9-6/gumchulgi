# -*- coding: utf-8 -*-
"""원본 | BASE(sigma2) | STRONG(sigma32+gate) 3패널 비교영상 (라벨은 cv2 로 각인)."""
import os, subprocess, sys
import cv2, numpy as np

S = "/tmp/claude-0/-home-user-gumchulgi/8b6ecb4d-7f89-5d01-9d46-550dce056d9c/scratchpad"
UP = "/root/.claude/uploads/8b6ecb4d-7f89-5d01-9d46-550dce056d9c"
OUT = f"{S}/ai_poc/compare"; os.makedirs(OUT, exist_ok=True)
CLIPS = {"cera_khin": f"{UP}/5cb50f8a-cera_khin.mp4",
         "pinkvenom": f"{UP}/1a6ccb54-pinkvenom.mp4",
         "travis_fein": f"{UP}/b2876855-travis_fein.mp4"}
LABELS = ["ORIGINAL", "BASE (sigma 2)", "STRONG (sigma 32 + gate)"]
PW = 440

def label(img, text):
    cv2.rectangle(img, (6, 6), (6 + 11 * len(text) + 14, 40), (0, 0, 0), -1)
    cv2.putText(img, text, (14, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2, cv2.LINE_AA)
    return img

for name, src in CLIPS.items():
    paths = [src, f"{S}/real_out/{name}_sigma2.mp4", f"{S}/real_out/{name}_strong.mp4"]
    caps = [cv2.VideoCapture(p) for p in paths]
    fps = caps[0].get(cv2.CAP_PROP_FPS) or 30
    h0, w0 = int(caps[0].get(4)), int(caps[0].get(3))
    ph = int(round(h0 * PW / w0)) // 2 * 2
    dst = f"{OUT}/{name}_3panel.mp4"
    q = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                          "-s", f"{PW*3}x{ph}", "-r", str(fps), "-i", "-", "-i", src,
                          "-map", "0:v:0", "-map", "1:a:0?", "-c:a", "aac", "-shortest",
                          "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                          "-pix_fmt", "yuv420p", dst], stdin=subprocess.PIPE)
    n = 0
    while True:
        fr = []
        for c in caps:
            ok, f = c.read()
            if not ok:
                fr = None; break
            fr.append(label(cv2.resize(f, (PW, ph), interpolation=cv2.INTER_AREA), LABELS[len(fr)]))
        if fr is None:
            break
        q.stdin.write(np.ascontiguousarray(np.hstack(fr)).tobytes()); n += 1
    for c in caps:
        c.release()
    q.stdin.close(); q.wait()
    print(f"{name}: {n} frames -> {dst}", flush=True)
print("DONE")
