# -*- coding: utf-8 -*-
"""소형/대형 광원 점멸 합성 클립 생성 (PoC1).

관례: testclips 와 동일 — 360x640(세로), 30fps, FFV1 yuv444p, .mkv
차이: 8초(240프레임), 점멸은 프레임 60~186 (4.2초, 4Hz) — 5초지속 회피.
배경은 어두운 회색(70/255). σ32 누수는 국소 평균(blur32 분모)이 정적
성분을 가져야 재현되므로 완전 검정 배경은 쓰지 않는다(비 곱셈불변).
"""
import subprocess
import sys

import numpy as np

W, H, FPS, N = 360, 640, 30, 240
BLINK_A, BLINK_B = 60, 186          # 점멸 구간 [A, B)
HZ = 4.0
BG = 70          # 배경 sRGB
ON_V = 252       # 전구 켜짐
OFF_V = 78       # 거의 꺼짐 (배경보다 살짝 밝게)
AA = 1.2         # 경계 안티에일리어싱 폭(px)


def place_bulbs(n, rmin, rmax, seed, margin_x=20, margin_y=50, max_try=40000):
    """무작위 배치 + 최소거리(겹침 금지). 규칙 격자를 피해 패턴 오탐 방지."""
    rng = np.random.default_rng(seed)
    bulbs = []
    tries = 0
    while len(bulbs) < n and tries < max_try:
        tries += 1
        r = rng.uniform(rmin, rmax)
        x = rng.uniform(margin_x + r, W - margin_x - r)
        y = rng.uniform(margin_y + r, H - margin_y - r)
        ok = all((x - bx) ** 2 + (y - by) ** 2 >= (r + br + 3.0) ** 2
                 for bx, by, br in bulbs)
        if ok:
            bulbs.append((x, y, r))
    return bulbs


def alpha_map(bulbs):
    """전구 합성 알파(0~1) 한 장 — 프레임마다 값만 바꿔 합성한다."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    a = np.zeros((H, W), np.float32)
    for x, y, r in bulbs:
        d = np.sqrt((xx - x) ** 2 + (yy - y) ** 2)
        a = np.maximum(a, np.clip((r - d) / AA, 0.0, 1.0))
    return a


def bulb_on(n):
    if not (BLINK_A <= n < BLINK_B):
        return True                       # 점멸 구간 밖은 켜진 채 정지
    ph = (n - BLINK_A) * HZ * 2.0 / FPS   # 초당 2*HZ 회 전환
    return int(ph) % 2 == 0


def write_clip(path, bulbs):
    a = alpha_map(bulbs)
    cov = float((a > 0.5).mean())
    print(f"{path}: bulbs={len(bulbs)} coverage={cov:.3f}")
    p = subprocess.Popen(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS),
         "-i", "-", "-c:v", "ffv1", "-level", "3", "-pix_fmt", "yuv444p", path],
        stdin=subprocess.PIPE)
    for n in range(N):
        v = ON_V if bulb_on(n) else OFF_V
        f = BG + a * (v - BG)
        frame = np.repeat(np.clip(f, 0, 255).astype(np.uint8)[..., None], 3, axis=2)
        p.stdin.write(np.ascontiguousarray(frame).tobytes())
    p.stdin.close()
    p.wait()
    return cov


if __name__ == "__main__":
    out12, out13 = sys.argv[1], sys.argv[2]
    n12 = int(sys.argv[3]) if len(sys.argv) > 3 else 30
    rmin = float(sys.argv[4]) if len(sys.argv) > 4 else 8.0
    rmax = float(sys.argv[5]) if len(sys.argv) > 5 else 11.0
    if out12 != "-":
        b12 = place_bulbs(n12, rmin, rmax, seed=12)
        write_clip(out12, b12)
    if out13 != "-":
        b13 = [(W * 0.5, H * 0.28, 62.0), (W * 0.3, H * 0.62, 60.0),
               (W * 0.72, H * 0.66, 61.0)]
        write_clip(out13, b13)
