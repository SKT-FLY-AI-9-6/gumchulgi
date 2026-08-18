# -*- coding: utf-8 -*-
"""판정으로 악화 0 을 달성한 조합들을 **화질**로 가른다.

주석이 alpha_compensate 를 "나머지엔 손해"라며 꺼둔 근거가 판정이 아니라
화질이었을 수 있다. 선명도(고역 유지율)와 이질감(펌핑·헤일로)으로 잰다.
"""
import os, sys
sys.path.insert(0, os.getcwd())
import cv2, numpy as np
import pseenv as ENV, pselive3 as P3, rawmeasure as RM, seam

CLIPS = ["synth/01_lum_strobe_5hz.mp4", "genre/22_game_hud_7hz.mp4",
         "run3/seg6.mp4", "synth/14_stripes_drift_10pairs.mp4"]
COMBOS = [(5.0, False), (2.0, True), (1.0, False), (3.0, True)]
WORK = "_qf"
os.makedirs(WORK, exist_ok=True)


def read_all(p):
    cap = cv2.VideoCapture(p); fps = cap.get(cv2.CAP_PROP_FPS) or 30.0; fr = []
    while True:
        ok, f = cap.read()
        if not ok: break
        fr.append(f)
    cap.release(); return fr, fps


def hf(frames):
    v = []
    for f in frames:
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32)
        v.append(float(np.abs(g - cv2.GaussianBlur(g, (0, 0), 2.0)).mean()))
    return float(np.mean(v)) if v else 1.0


print(f"{'클립':<28}{'페더':>6}{'알파':>7}{'선명도':>9}{'펌핑+':>9}{'헤일로+':>10}")
for c in CLIPS:
    fr, fps = read_all(c)
    h0 = hf(fr)
    ctrl = os.path.join(WORK, os.path.basename(c).replace(".mp4", "_ctrl.mp4"))
    if not os.path.exists(ctrl):
        seam.make_control(c, ctrl)
    b = seam.measure(c, ctrl)
    for fea, ac in COMBOS:
        cfg = P3.Cfg(); cfg.feather_px = fea; cfg.alpha_compensate = ac
        _, out = P3.run(c, cfg, verbose=False)
        p = os.path.join(WORK, f"o_{fea}_{ac}.mp4")
        RM.write_lossless(out, p.replace(".mp4", ".mkv"), fps)
        m = seam.measure(c, p.replace(".mp4", ".mkv"))
        print(f"{os.path.basename(c)[:26]:<28}{fea:>6.1f}{str(ac):>7}"
              f"{hf(out)/max(h0,1e-9)*100:>8.0f}%"
              f"{max(m['pumping']-b['pumping'],0):>9.3f}"
              f"{max(m['halo']-b['halo'],0):>10.3f}", flush=True)
        os.remove(p.replace(".mp4", ".mkv"))
    print()
