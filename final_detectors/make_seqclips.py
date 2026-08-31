# -*- coding: utf-8 -*-
"""
make_seqclips.py — 시퀀스 규칙 검증용 클립
==========================================
Jordan, HCII 2025 가 지적한 두 조항이 실제로 작동하는지 확인한다.

  (A) 334ms 규칙 — ITU-R/Ofcom 에만 있는 조항.
      선행엣지가 334ms 넘게 떨어진 플래시는 같은 시퀀스로 묶지 않는다.
      → 같은 영상이 ITU-R 은 통과하고 WCAG 는 위반이어야 정상.

  (B) 화소 동일성 — "화면의 25%가 번쩍인 뒤 **다른** 25%가 번쩍이면 안전".
      한 시퀀스의 플래시들은 겹치는 영역이 면적 임계를 넘어야 한다.
      → 두 영역이 번갈아 번쩍이면 합산 4회/s 라도 통과여야 정상.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np

W, H = 360, 640
FPS = 30
DUR = 4.0
DARK = (30, 30, 30)
BRIGHT = (235, 235, 235)


def write(path: Path, frames):
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-c:v", "ffv1", "-pix_fmt", "yuv444p", str(path)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in frames:
        p.stdin.write(np.ascontiguousarray(f, dtype=np.uint8).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError(f"ffmpeg 실패: {path}")


def base():
    f = np.empty((H, W, 3), np.uint8)
    f[..., 0], f[..., 1], f[..., 2] = DARK[2], DARK[1], DARK[0]
    return f


def region(top_frac, height_frac):
    """세로 방향 띠. 면적 = height_frac."""
    y0 = int(H * top_frac)
    y1 = y0 + int(H * height_frac)
    return slice(y0, y1)


def pulses(times, area_slice=None, pulse_frames=2):
    """times(초)에 밝은 펄스를 넣는다. area_slice 가 없으면 전면."""
    on = set()
    for t in times:
        s = int(round(t * FPS))
        for k in range(pulse_frames):
            on.add(s + k)
    for i in range(int(FPS * DUR)):
        f = base()
        if i in on:
            if area_slice is None:
                f[:, :] = (BRIGHT[2], BRIGHT[1], BRIGHT[0])
            else:
                f[area_slice, :] = (BRIGHT[2], BRIGHT[1], BRIGHT[0])
        yield f


def two_regions(times_a, times_b, frac=0.35, pulse_frames=2):
    """겹치지 않는 두 영역이 서로 다른 시각에 번쩍인다."""
    A = region(0.02, frac)
    B = region(0.60, frac)
    on_a, on_b = set(), set()
    for t in times_a:
        s = int(round(t * FPS))
        for k in range(pulse_frames):
            on_a.add(s + k)
    for t in times_b:
        s = int(round(t * FPS))
        for k in range(pulse_frames):
            on_b.add(s + k)
    for i in range(int(FPS * DUR)):
        f = base()
        if i in on_a:
            f[A, :] = (BRIGHT[2], BRIGHT[1], BRIGHT[0])
        if i in on_b:
            f[B, :] = (BRIGHT[2], BRIGHT[1], BRIGHT[0])
        yield f


def main(outdir="seqclips"):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)

    # (A) 버스트 3회 + 0.9초에 고립 1회 → 1초 창에 4회.
    #     고립된 플래시는 앞뒤로 334ms 넘게 떨어져야 하므로 **2초 주기**로 둔다.
    #     (1초 주기로 하면 다음 주기 버스트가 0.1초 뒤라 시퀀스가 이어져 버린다 —
    #      실측으로 확인하고 고친 부분)
    #     시퀀스: [0.00,0.10,0.20] 3회 → 한도 이하 / [0.90] 1회 → 한도 이하
    #     반면 334ms 규칙이 없으면 1초 창에 4회라 위반.
    burst = []
    for cyc in range(2):
        b = cyc * 2.0
        burst += [b + 0.00, b + 0.10, b + 0.20, b + 0.90]

    # (B) 겹치지 않는 두 영역이 번갈아. 합산 4회/s 지만 각 영역은 2회/s.
    ta, tb = [], []
    for cyc in range(4):
        b = cyc * 1.0
        ta += [b + 0.00, b + 0.50]
        tb += [b + 0.25, b + 0.75]

    # (C) 대조군 — 한 영역만 4회/s. 반드시 위반이어야 한다.
    tc = []
    for cyc in range(4):
        b = cyc * 1.0
        tc += [b + 0.00, b + 0.25, b + 0.50, b + 0.75]

    specs = [
        ("30_burst_then_gap", pulses(burst),
         "버스트 3회+0.9s 뒤 1회 — ITU-R 통과 / WCAG 위반 이 정상"),
        ("31_two_regions_alt", two_regions(ta, tb),
         "겹치지 않는 두 영역 번갈아 합산 4회/s — 화소 동일성 규칙으로 통과가 정상"),
        ("32_one_region_4hz", pulses(tc, area_slice=region(0.02, 0.35)),
         "한 영역만 4회/s — 대조군, 반드시 위반"),
    ]
    for name, gen, note in specs:
        p = out / f"{name}.mkv"
        write(p, gen)
        print(f"  생성 {p.name:<24} {note}")
    print(f"\n{len(specs)}편 생성 완료 → {out.resolve()}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "seqclips")
