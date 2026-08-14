# -*- coding: utf-8 -*-
"""
make_testclips.py — 판정기 검증용 합성 클립 생성
================================================
정답을 알고 설계한 클립으로 두 판정기가 제대로 도는지 먼저 확인한다.
실제 숏폼 1,000편을 돌리기 전에 반드시 이걸로 sanity check 할 것.

핵심은 마지막 두 클립(05, 06)이다 — 등휘도 색 점멸.
WCAG 상대휘도가 거의 변하지 않으므로 WCAG 판정기는 통과시켜야 정상이고,
psecore 의 RG/BY/RB 채널은 잡아야 정상이다. 이 차이가 곧 우리 검출기의 추가분.

출력: FFV1 무손실 .mkv (인코딩이 판정을 흔드는 것을 배제)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np

W, H = 360, 640          # 9:16 세로 (숏폼 비율)
FPS = 30
DUR = 4.0                # s


def srgb_to_linear(v: float) -> float:
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def rel_lum(rgb255) -> float:
    r, g, b = (c / 255.0 for c in rgb255)
    return (0.2126 * srgb_to_linear(r)
            + 0.7152 * srgb_to_linear(g)
            + 0.0722 * srgb_to_linear(b))


def write(path: Path, frames_iter):
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-c:v", "ffv1", "-pix_fmt", "yuv444p", str(path)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in frames_iter:
        p.stdin.write(np.ascontiguousarray(f, dtype=np.uint8).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError(f"ffmpeg 실패: {path}")


def solid(rgb):
    f = np.empty((H, W, 3), np.uint8)
    f[..., 0], f[..., 1], f[..., 2] = rgb[2], rgb[1], rgb[0]   # BGR
    return f


def alternating(rgb_a, rgb_b, hz):
    """hz 회/초로 두 색을 교대. 교대 1회 = 플래시 1회."""
    a, b = solid(rgb_a), solid(rgb_b)
    period = FPS / (2.0 * hz)          # 한 상태 유지 프레임 수
    for i in range(int(FPS * DUR)):
        yield a if (int(i / period) % 2 == 0) else b


def stripes(pairs, moving=False):
    """세로 명암 줄무늬 pairs 쌍."""
    x = np.arange(W)
    for i in range(int(FPS * DUR)):
        phase = (i * 2.0 / FPS) if moving else 0.0
        s = (np.sin(2 * np.pi * (pairs * x / W + phase)) > 0).astype(np.uint8) * 255
        f = np.repeat(s[None, :], H, axis=0)
        yield np.dstack([f, f, f])


def local_strobe(hz, area_frac, rgb_on=(255, 255, 255), rgb_bg=(60, 60, 60)):
    """화면의 area_frac 만큼만 점멸. 무대 LED 한 벽면·화면 구석 이펙트를 모사한다.

    가이드북 체크리스트는 면적 25% 초과를 조건으로 두지만, 접근성 고시 문언에는
    면적 조건이 없다. 이 클립이 두 프로파일을 갈라놓는다.
    """
    bg = solid(rgb_bg)
    on = bg.copy()
    side = int(round((W * H * area_frac) ** 0.5))
    y0, x0 = (H - side) // 2, (W - side) // 2
    on[y0:y0 + side, x0:x0 + side] = (rgb_on[2], rgb_on[1], rgb_on[0])
    period = FPS / (2.0 * hz)
    for i in range(int(FPS * DUR)):
        yield on if (int(i / period) % 2 == 0) else bg


def calm():
    """안전 대조군 — 느린 그라데이션 이동."""
    y = np.linspace(0, 1, H)[:, None]
    x = np.linspace(0, 1, W)[None, :]
    for i in range(int(FPS * DUR)):
        t = i / (FPS * DUR)
        v = (0.25 + 0.35 * (0.5 * y + 0.5 * x + 0.15 * np.sin(2 * np.pi * (t + x))))
        g = np.clip(v * 255, 0, 255).astype(np.uint8)
        yield np.dstack([g, (g * 0.9).astype(np.uint8), (g * 0.8).astype(np.uint8)])


def iso_color(direction, target_L: float):
    """direction(각 채널 0~1 비율)의 밝기를 조절해 상대휘도를 target_L 에 맞춘다.

    direction 은 색상 방향만 지정한다. 예: (1,1,0)=노랑, (1,0.3,0.3)=탈채도 적색.
    반환은 0~255 정수 RGB.
    """
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        c = tuple(v * 255.0 * mid for v in direction)
        if rel_lum(c) < target_L:
            lo = mid
        else:
            hi = mid
    return tuple(int(round(min(255.0, v * 255.0 * lo))) for v in direction)


def red_ratio(rgb) -> float:
    r, g, b = rgb
    t = r + g + b
    return r / t if t else 0.0


def main(outdir: str = "testclips"):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)

    # 등휘도 색쌍 — WCAG 상대휘도를 청색(0,0,255) 기준으로 맞춘다
    blue = (0, 0, 255)
    L = rel_lum(blue)
    yellow = iso_color((1, 1, 0), L)          # 순수 노랑
    red_sat = iso_color((1, 0, 0), L)         # 순수 적색 — RedRatio 1.0 (WCAG 적색 규칙에 걸림)
    # 탈채도 적색 — RedRatio < 0.8 이라 WCAG 적색 규칙을 빠져나간다
    red_desat = iso_color((1, 0.30, 0.30), L)
    blue_desat = iso_color((0.30, 0.30, 1), L)
    green_iso = iso_color((0, 1, 0), L)

    print("등휘도 색쌍 (WCAG 상대휘도 기준, 목표 L=%.4f)" % L)
    for name, c in [("청", blue), ("황", yellow), ("적(채도高)", red_sat),
                    ("적(탈채도)", red_desat), ("청(탈채도)", blue_desat), ("녹", green_iso)]:
        print(f"  {name:<10} {str(c):<18} L={rel_lum(c):.4f}  RedRatio={red_ratio(c):.2f}")
    print()

    specs = [
        ("00_safe_gradient",   calm(),                                    "안전 — 양쪽 다 위반 0 이어야 함"),
        ("01_flash_5hz",       alternating((255,255,255), (0,0,0), 5),    "휘도 플래시 5Hz — 양쪽 다 FAIL"),
        ("02_flash_2hz",       alternating((255,255,255), (0,0,0), 2),    "휘도 플래시 2Hz — 한도 이하, 양쪽 다 PASS"),
        ("03_red_black_5hz",   alternating((255,0,0), (0,0,0), 5),        "적↔흑 5Hz — 양쪽 다 FAIL"),
        ("04_stripes_10pairs", stripes(10, moving=False),                 "정지 줄무늬 10쌍 — 패턴 FAIL"),
        ("05_iso_blue_yellow", alternating(blue, yellow, 8),              "등휘도 청↔황 8Hz (Parra 68%) — WCAG PASS / psecore BY FAIL 이 정상"),
        ("06_iso_red_blue_sat", alternating(red_sat, blue, 12),           "등휘도 적↔청 12Hz, 적색 채도高 — WCAG 는 적색 규칙으로 잡는다"),
        ("07_iso_red_blue_desat", alternating(red_desat, blue_desat, 12), "등휘도 적↔청 12Hz, RedRatio<0.8 (포리곤 유사) — WCAG PASS / psecore RB FAIL 이 정상"),
        ("08_iso_red_green",   alternating(red_desat, green_iso, 10),     "등휘도 적↔녹 10Hz (Parra 80%) — WCAG PASS / psecore RG FAIL 이 정상"),
        ("09_local_strobe_10pct", local_strobe(8, 0.10),                  "화면 10% 국소 점멸 8Hz — 면적 25% 기준은 통과 / 고시 문언은 위반이 정상"),
        ("10_stripes_moving",  stripes(10, moving=True),                  "이동 줄무늬 10쌍 — 이동 패턴 25% 기준 위반"),
    ]

    for name, gen, note in specs:
        path = out / f"{name}.mkv"
        write(path, gen)
        print(f"  생성 {path.name:<26} {note}")

    print(f"\n{len(specs)}편 생성 완료 → {out.resolve()}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "testclips")
