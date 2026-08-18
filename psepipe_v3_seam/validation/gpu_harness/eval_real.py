# -*- coding: utf-8 -*-
"""실사 전체 코퍼스 평가 — 악화 0 확인 + 성능 측정.

209편 (유튜브 24 + 인스타 185). GPU 판만 돌린다 — CPU 는 편당 100ms/frame 이라
전수에 몇 시간이 더 걸리고, 합성 27클립에서 CPU/GPU 판정이 완전히 일치하는 것을
이미 확인했다.

절대 조건: 안전한 원본(원본 위반 0)을 위반으로 만들지 않을 것.
"""
import os, sys, glob, csv, time
sys.path.insert(0, os.getcwd())
import cv2, numpy as np
import psecore as PC, pseenv as ENV, pselive3 as P3, rawmeasure as RM
import psegpu_full as PGF

DIRS = sys.argv[1:] or ["_yt", "_ig_viol", "_ig_safe"]


def read_all(p):
    cap = cv2.VideoCapture(p); fps = cap.get(cv2.CAP_PROP_FPS) or 30.0; fr = []
    while True:
        ok, f = cap.read()
        if not ok: break
        fr.append(f)
    cap.release(); return fr, fps


def judge(frames, fps, tag):
    p = ENV.tmp(f"er_{tag}.mkv")
    RM.write_lossless(frames, p, fps)
    r = PC.analyze(p, PC.PROFILES["bt1702"])
    os.remove(p)
    return sum(r.channel_seconds().values())


files = []
for d in DIRS:
    files += [(d, f) for f in sorted(glob.glob(os.path.join(d, "*.mp4")))]
print(f"실사 {len(files)}편 평가 시작\n", flush=True)

rows, worse, n_viol, rem_sum, t0 = [], [], 0, 0.0, time.time()
for i, (d, f) in enumerate(files, 1):
    try:
        fr, fps = read_all(f)
        if len(fr) < 10:
            continue
        v0 = judge(fr, fps, "0")
        rg, og = PGF.run(f, P3.Cfg(), PGF.OptF(), warmup=2)
        v1 = judge(og, fps, "g")
    except Exception as e:
        print(f"  [{i}/{len(files)}] {os.path.basename(f)} 오류 {type(e).__name__}", flush=True)
        continue
    is_worse = v1 > v0 + 1e-9
    rem = (1 - v1 / v0) * 100 if v0 > 1e-9 else None
    if v0 > 1e-9:
        n_viol += 1; rem_sum += rem
    if is_worse:
        worse.append((os.path.basename(f), v0, v1))
    rows.append({"dir": d, "clip": os.path.basename(f), "before": round(v0, 2),
                 "after": round(v1, 2), "removed_pct": None if rem is None else round(rem, 1),
                 "cuts": rg["cuts"], "mask": round(rg["mean_mask_area"], 3),
                 "ms": round(rg["ms_per_frame"], 1), "worse": int(is_worse)})
    if is_worse or i % 10 == 0:
        el = time.time() - t0
        mark = "  <<< 악화" if is_worse else ""
        print(f"  [{i}/{len(files)}] {os.path.basename(f)[:22]:<24}"
              f"{v0:>7.2f} -> {v1:>7.2f}"
              f"{'' if rem is None else f'  제거 {rem:3.0f}%'}"
              f"   경과 {el/60:.0f}분  악화누적 {len(worse)}{mark}", flush=True)

    if i % 25 == 0 or i == len(files):
        with open("validation/eval_real_all.csv", "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)

print(f"\n{'='*60}")
print(f"실사 {len(rows)}편 평가 완료  ({(time.time()-t0)/60:.0f}분)")
print(f"  위반 원본 {n_viol}편  평균 제거율 {rem_sum/max(n_viol,1):.1f}%")
print(f"  **악화 {len(worse)}편**")
for n, a, b in worse:
    print(f"     {n}  {a:.2f} -> {b:.2f}")
print("CSV -> validation/eval_real_all.csv")
