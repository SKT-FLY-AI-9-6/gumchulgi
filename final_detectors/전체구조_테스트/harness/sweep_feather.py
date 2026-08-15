# -*- coding: utf-8 -*-
"""페더 · 알파보정 스윕.

pselive3.py 헤더 '지뢰 6' 이 14번 악화의 원인을 페더링으로 지목한다
(페더 5px -> 5.60s, 페더 0 -> 0.26s). alpha_compensate 는 "14번엔 도움,
나머지엔 손해" 라 기본 off 로 남아 있다. 그 트레이드오프를 코퍼스 전체에서 잰다.

악화(원본보다 나빠짐)가 0 이면서 위반 제거를 가장 많이 남기는 조합을 찾는다.
"""
import os, sys, glob, itertools
sys.path.insert(0, os.getcwd())
import cv2, numpy as np
import psecore as PC, pseenv as ENV, pselive3 as P3, rawmeasure as RM

SAFE = ["synth/02_lum_safe_2.5hz.mp4", "synth/05_static.mp4",
        "synth/11_red_safe_2.5hz.mp4", "synth/13_stripes_static_10pairs.mp4",
        "synth/14_stripes_drift_10pairs.mp4", "synth/15_stripes_3pairs_safe.mp4",
        "synth/16_stripes_lowcontrast_safe.mp4",
        "synth/17_stripes_smallarea_safe.mp4", "genre/21_anime_cuts_6ps.mp4",
        "genre/25_safe_slow.mp4", "genre/26_safe_shaky.mp4"]
VIOL = ["synth/01_lum_strobe_5hz.mp4", "synth/03_isolum_redgreen_8hz.mp4",
        "synth/04_isolum_blueyellow_8hz.mp4", "synth/06_cardinal_LM_8hz.mp4",
        "synth/07_cardinal_S_8hz.mp4", "synth/08_red_black_5hz.mp4",
        "synth/09_red_gray_isolum_5hz.mp4", "synth/10_red_depth_6hz.mp4",
        "synth/12_porygon_redblue_12hz.mp4", "genre/20_bright_indoor_5hz.mp4",
        "genre/22_game_hud_7hz.mp4", "genre/23_letterbox_5hz.mp4",
        "genre/24_film24_5hz.mp4", "genre/27_anime_cuts_10ps.mp4",
        "synth/28_blue_strobe_5hz.mp4", "run3/seg6.mp4"]
CLIPS = [c for c in SAFE + VIOL if os.path.exists(c)]


def read_all(p):
    cap = cv2.VideoCapture(p); fps = cap.get(cv2.CAP_PROP_FPS) or 30.0; fr = []
    while True:
        ok, f = cap.read()
        if not ok: break
        fr.append(f)
    cap.release(); return fr, fps


def judge(frames, fps):
    p = ENV.tmp("sf_g.mkv")
    RM.write_lossless(frames, p, fps)
    r = PC.analyze(p, PC.PROFILES["bt1702"])
    os.remove(p)
    return sum(r.channel_seconds().values())


base, fpsm = {}, {}
for c in CLIPS:
    fr, fps = read_all(c)
    base[c] = judge(fr, fps); fpsm[c] = fps
print("원본 위반초:", {os.path.basename(k): round(v, 2) for k, v in base.items() if v > 0})
print()

COMBOS = [(1.5, False), (1.0, False), (0.5, False)]
print(f"{'페더':>6}{'알파보정':>9}{'악화수':>8}{'남은위반초':>11}{'제거율':>8}   악화클립")
for fea, ac in COMBOS:
    worse, left, tot0 = [], 0.0, 0.0
    for c in CLIPS:
        cfg = P3.Cfg(); cfg.feather_px = fea; cfg.alpha_compensate = ac
        _, out = P3.run(c, cfg, verbose=False)
        v = judge(out, fpsm[c])
        if v > base[c] + 1e-9:
            worse.append(f"{os.path.basename(c)[:12]}({base[c]:.2f}->{v:.2f})")
        left += v; tot0 += base[c]
    print(f"{fea:>6.1f}{str(ac):>9}{len(worse):>8}{left:>11.2f}"
          f"{(1-left/max(tot0,1e-9))*100:>7.0f}%   {', '.join(worse) or '-'}", flush=True)
