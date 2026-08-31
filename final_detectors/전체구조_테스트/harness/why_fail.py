# -*- coding: utf-8 -*-
"""A 필터가 실사 위반 16편 중 7편에서 '손도 못 대는' 이유를 찾는다.

성공군(9편, 위반 -> 0.00)과 실패군(7편, 거의 그대로)의 지표를 나란히 놓고
무엇이 갈리는지 본다. CPU·GPU 가 똑같이 실패하므로 A 본체 문제다.
"""
import os, sys, csv
sys.path.insert(0, os.getcwd())
import cv2, numpy as np
import psecore as PC, pseenv as ENV, pselive3 as P3, rawmeasure as RM
import pse_bt1702 as BT

SRC = "_yt"

# verify_real 결과에서 가져온 분류 (원본 -> CPU/GPU 결과)
FAIL = ["523LwKMfF2I", "CIHun1gx7zU", "TXeDgXiytM0", "Y76O5wY7EcM",
        "ezm9i2nGYwQ", "xDdAHEUQ2zA", "zlmWXyIFYnM"]
OK = ["AjbrmfjJRk0", "Ben_8tA6Eyg", "M5HYGDDf6wU", "MFC0eGtaF5M",
      "PFSDW2g3D8o", "QtXx3Qubmys", "Z0NIxY7svlM", "_3-eqclZgQc", "xbawhCyMsRI"]


def read_all(p):
    cap = cv2.VideoCapture(p); fps = cap.get(cv2.CAP_PROP_FPS) or 30.0; fr = []
    while True:
        ok, f = cap.read()
        if not ok: break
        fr.append(f)
    cap.release(); return fr, fps


def judge(frames, fps):
    p = ENV.tmp("wf.mkv"); RM.write_lossless(frames, p, fps)
    r = PC.analyze(p, PC.PROFILES["bt1702"]); os.remove(p)
    return sum(r.channel_seconds().values()), r.channel_seconds()


rows = []
print(f"{'클립':<16}{'군':<5}{'전':>8}{'후':>8}{'제거%':>7}"
      f"{'마스크':>8}{'무장%':>7}{'컷':>5}{'워프':>5}{'게인':>7}  실패규칙")
for grp, names in (("실패", FAIL), ("성공", OK)):
    for n in names:
        p = os.path.join(SRC, n + ".mp4")
        if not os.path.exists(p):
            continue
        fr, fps = read_all(p)
        v0, ch0 = judge(fr, fps)
        r, out = P3.run(p, P3.Cfg(), verbose=False)
        v1, ch1 = judge(out, fps)
        rules = BT.analyze(p, width=320)["failed_rules"]
        rem = (1 - v1 / max(v0, 1e-9)) * 100
        armed = r.get("armed_frames", 0) / max(r["frames"], 1) * 100
        print(f"{n[:14]:<16}{grp:<5}{v0:>8.2f}{v1:>8.2f}{rem:>6.0f}%"
              f"{r['mean_mask_area']:>8.3f}{armed:>6.0f}%{r['cuts']:>5}"
              f"{r['warped']:>5}{r.get('gain_mean',0):>7.3f}  {','.join(rules)}",
              flush=True)
        rows.append({"clip": n, "group": grp, "before": round(v0, 2),
                     "after": round(v1, 2), "removed_pct": round(rem, 1),
                     "mask": r["mean_mask_area"], "armed_pct": round(armed, 1),
                     "cuts": r["cuts"], "warped": r["warped"],
                     "gain_mean": r.get("gain_mean", 0), "frames": r["frames"],
                     "rules": ";".join(rules),
                     **{f"ch_{k}": round(v, 2) for k, v in ch0.items()}})

with open("validation/why_fail.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader(); w.writerows(rows)

f_ = [r for r in rows if r["group"] == "실패"]
o_ = [r for r in rows if r["group"] == "성공"]
print("\n── 군 평균 ──")
for k in ["before", "removed_pct", "mask", "armed_pct", "cuts", "warped", "gain_mean"]:
    a = np.mean([r[k] for r in f_]); b = np.mean([r[k] for r in o_])
    print(f"  {k:<12} 실패 {a:>9.3f}   성공 {b:>9.3f}")
print("\nCSV -> validation/why_fail.csv")
