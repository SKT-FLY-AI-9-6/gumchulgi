# -*- coding: utf-8 -*-
"""PoC3 — VMAF 안전망: base(Cfg) vs strong(Cfg.strong()) 지각 화질 + 심판 판정."""
import json, os, re, subprocess, sys, time
sys.path.insert(0, "/home/user/gumchulgi/psepipe_v3_seam")
import pse_bt1702 as BT
import pselive3 as P3

S = "/tmp/claude-0/-home-user-gumchulgi/8b6ecb4d-7f89-5d01-9d46-550dce056d9c/scratchpad"
UP = "/root/.claude/uploads/8b6ecb4d-7f89-5d01-9d46-550dce056d9c"
OUT = f"{S}/ai_poc/vmaf"; os.makedirs(OUT, exist_ok=True)

SRCS = [("cera_khin", f"{UP}/5cb50f8a-cera_khin.mp4"),
        ("pinkvenom", f"{UP}/1a6ccb54-pinkvenom.mp4"),
        ("travis_fein", f"{UP}/b2876855-travis_fein.mp4"),
        ("12_bulbs_grid", f"{S}/ai_poc/clips/12_bulbs_grid.mkv"),
        ("13_bulbs_large", f"{S}/ai_poc/clips/13_bulbs_large.mkv"),
        ("01_flash_5hz", f"{S}/testclips/01_flash_5hz.mkv"),
        ("09_local_strobe", f"{S}/testclips/09_local_strobe_10pct.mkv")]

def vmaf(dist, ref):
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-i", dist, "-i", ref, "-lavfi",
           "[0:v]setpts=PTS-STARTPTS[d0];[1:v]setpts=PTS-STARTPTS[r0];"
           "[d0][r0]scale2ref=flags=bicubic[d][r];"
           "[d][r]libvmaf=n_threads=4", "-f", "null", "-"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    m = re.search(r"VMAF score:\s*([\d.]+)", p.stderr)
    return round(float(m.group(1)), 2) if m else None

rows = []
for name, src in SRCS:
    judge_src = ",".join(BT.analyze(src)["failed_rules"]) or "적합"
    for tag, cfg in (("base", P3.Cfg()), ("strong", P3.Cfg.strong())):
        out = f"{OUT}/{name}_{tag}.mp4"
        t0 = time.time()
        if not os.path.exists(out):
            P3.run(src, cfg, video_out=out, verbose=False)
        sec = round(time.time() - t0, 1)
        judge = ",".join(BT.analyze(out)["failed_rules"]) or "적합"
        v = vmaf(out, src)
        rows.append(dict(clip=name, config=tag, judge_src=judge_src, judge=judge,
                         vmaf=v, sec=sec))
        print(f"{name:<16} {tag:<7} vmaf {v}  판정 {judge}  ({sec}s)", flush=True)
        json.dump(rows, open(f"{OUT}/vmaf_rows.json", "w"), ensure_ascii=False, indent=1)

import csv
with open(f"{S}/ai_poc/vmaf_poc.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print("DONE")
