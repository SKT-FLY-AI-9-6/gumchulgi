# -*- coding: utf-8 -*-
"""tex 클램프 가설의 직접 시험 — 위반 기하는 고정, 배경 밝기만 바꾼다.

pselive3.py:513-530  tex = clip(Y_i / blur(Y_i, σ), 0.25, 4.0)
가설: 어두운 배경 위 밝은 광원은 비율이 4 를 넘어 잘려 복원이 제한되고(누수 X),
배경이 밝아 비율이 [1,4] 안에 들면 억제된 플래시가 온전히 복원돼 샌다(누수 O).
같은 전구 배치(점멸 면적 26% — 판정 문턱 초과)로 BG 만 20/70/140/190 으로 바꿔
누수 발생 여부를 본다. 가설이 틀리면 틀렸다고 기록한다.
"""
import csv, json, os, subprocess, sys
sys.path.insert(0, "/home/user/gumchulgi/psepipe_v3_seam")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import gen_clips as G
import pse_bt1702 as BT
import pselive3 as P3
from leak_probe import probe

A = os.path.dirname(os.path.abspath(__file__))
D = f"{A}/bgmatrix"; os.makedirs(D, exist_ok=True)

def write_bg(path, bulbs, bg):
    a = G.alpha_map(bulbs)
    p = subprocess.Popen(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                          "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{G.W}x{G.H}",
                          "-r", str(G.FPS), "-i", "-", "-c:v", "ffv1", "-level", "3",
                          "-pix_fmt", "yuv444p", path], stdin=subprocess.PIPE)
    off = max(bg + 8, int(bg * 1.1))
    for n in range(G.N):
        v = G.ON_V if G.bulb_on(n) else off
        f = bg + a * (v - bg)
        fr = np.repeat(np.clip(f, 0, 255).astype(np.uint8)[..., None], 3, axis=2)
        p.stdin.write(np.ascontiguousarray(fr).tobytes())
    p.stdin.close(); p.wait()
    return float((a > 0.5).mean())

def judge(p): return ",".join(BT.analyze(p)["failed_rules"]) or "적합"

if __name__ == "__main__":
    bulbs = G.place_bulbs(240, 8.0, 11.0, seed=12)
    rows = []
    for bg in (20, 70, 140, 190):
        src = f"{D}/bg{bg:03d}.mkv"
        cov = write_bg(src, bulbs, bg) if not os.path.exists(src) else -1
        row = dict(clip=f"bg{bg:03d}", bg=bg, coverage=round(cov, 3), **probe(src))
        row["judge_src"] = judge(src)
        for tag, cfg in (("base", P3.Cfg()), ("strong", P3.Cfg.strong())):
            out = f"{D}/bg{bg:03d}_{tag}.mp4"
            if not os.path.exists(out):
                P3.run(src, cfg, video_out=out, verbose=False)
            row["judge_" + tag] = judge(out)
        row["누수"] = "Y" if (row["judge_base"] == "적합" and row["judge_strong"] != "적합") else "N"
        print(json.dumps(row, ensure_ascii=False), flush=True)
        rows.append(row)
        json.dump(rows, open(f"{A}/bg_matrix.json", "w"), ensure_ascii=False, indent=1)
    with open(f"{A}/bg_matrix.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print("DONE")
