# -*- coding: utf-8 -*-
"""
make_cutclips.py — 컷 검출기 검증용 합성 클립
==============================================
컷 검출기의 진짜 시험은 "컷을 잡는가"가 아니라 **"모션을 컷으로 오해하지 않는가"**다.
숏폼에는 휙 돌리는 촬영·급격한 줌·손떨림이 흔하고, 프레임 차분만 보면 이것들이
실제 컷보다 큰 변화를 만든다. 그래서 오탐 케이스를 양성 케이스보다 많이 넣었다.

핵심 설계 — 컷 클립의 장면들은 **평균 휘도를 서로 맞춘다.**
그래야 "휘도는 안 변하는데 화면만 바뀌는" 상황, 즉 LUM 채널이 구조적으로 놓치고
컷 채널만 잡을 수 있는 상황이 재현된다. 이게 이 채널을 만든 이유다.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np

W, H = 360, 640          # 9:16 세로
FPS = 30
DUR = 4.0
TARGET_LUMA = 110.0      # 모든 장면의 평균 휘도를 여기에 맞춘다 (8bit)

rng = np.random.default_rng(20260810)


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


def _smooth_noise(h, w, scale):
    """저주파 노이즈 — 자연스러운 텍스처 느낌."""
    small = rng.random((max(2, h // scale), max(2, w // scale))).astype(np.float32)
    import cv2
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)


def match_luma(bgr: np.ndarray, target: float = TARGET_LUMA) -> np.ndarray:
    """평균 휘도를 target 으로 맞춘다 — 장면끼리 밝기를 동일하게."""
    luma = 0.114 * bgr[..., 0] + 0.587 * bgr[..., 1] + 0.299 * bgr[..., 2]
    m = float(luma.mean())
    if m < 1e-3:
        return bgr
    return np.clip(bgr.astype(np.float32) * (target / m), 0, 255).astype(np.uint8)


def make_scene(seed_shift: int, h=H, w=W) -> np.ndarray:
    """색상·구조가 뚜렷이 다른 장면 한 장. 평균 휘도는 다른 장면과 동일."""
    global rng
    rng = np.random.default_rng(20260810 + seed_shift * 977)
    base = np.stack([_smooth_noise(h, w, s) for s in (18, 26, 34)], axis=-1)
    # 채널별 이득을 다르게 줘서 색조를 확 바꾼다
    gains = rng.random(3) * 1.4 + 0.3
    img = np.clip(base * gains * 255.0, 0, 255).astype(np.uint8)
    return match_luma(img)


def cuts_at(hz: float, n_scenes: int = 12):
    """초당 hz 회로 장면을 바꾼다. 장면들의 평균 휘도는 전부 동일."""
    scenes = [make_scene(i) for i in range(n_scenes)]
    per = max(1, int(round(FPS / hz)))
    for i in range(int(FPS * DUR)):
        yield scenes[(i // per) % n_scenes]


def whip_pan(px_per_frame: int = 260):
    """휙 돌리는 촬영 — 컷은 0회. 프레임 차분은 컷보다 크다. 반드시 PASS 해야 한다."""
    pano_w = W * 8
    pano = make_scene(101, h=H, w=pano_w)
    total = int(FPS * DUR)
    for i in range(total):
        x = (i * px_per_frame) % (pano_w - W)
        yield pano[:, x:x + W]


def fast_zoom():
    """급격한 줌 인/아웃 — 컷 0회. 반드시 PASS."""
    import cv2
    big = make_scene(202, h=H * 3, w=W * 3)
    total = int(FPS * DUR)
    for i in range(total):
        t = i / total
        z = 0.35 + 0.6 * abs(np.sin(2 * np.pi * 2.0 * t))   # 초당 2회 왕복
        ch, cw = int(H * 3 * z), int(W * 3 * z)
        y0 = (H * 3 - ch) // 2
        x0 = (W * 3 - cw) // 2
        crop = big[y0:y0 + ch, x0:x0 + cw]
        yield cv2.resize(crop, (W, H), interpolation=cv2.INTER_LINEAR)


def handheld():
    """손떨림 — 컷 0회. 반드시 PASS."""
    import cv2
    pad = 60
    big = make_scene(303, h=H + 2 * pad, w=W + 2 * pad)
    total = int(FPS * DUR)
    for i in range(total):
        dx = int(round(pad * 0.8 * np.sin(2 * np.pi * 3.1 * i / FPS)))
        dy = int(round(pad * 0.8 * np.cos(2 * np.pi * 2.3 * i / FPS)))
        yield big[pad + dy:pad + dy + H, pad + dx:pad + dx + W]


def flash_only(hz=5):
    """전면 백↔흑 점멸 — 컷은 0회다(LUM 채널의 몫). 컷 채널은 PASS 해야 한다."""
    white = np.full((H, W, 3), 255, np.uint8)
    black = np.zeros((H, W, 3), np.uint8)
    per = FPS / (2.0 * hz)
    for i in range(int(FPS * DUR)):
        yield white if (int(i / per) % 2 == 0) else black


def scene_with_flash(hz=5):
    """장면은 그대로인데 흰 섬광만 삽입 — 섬광 1장이 컷 2회로 세지면 안 된다."""
    scene = make_scene(404)
    white = np.full((H, W, 3), 250, np.uint8)
    per = int(round(FPS / hz))
    for i in range(int(FPS * DUR)):
        yield white if (i % per == 0) else scene


def static_scene():
    s = make_scene(505)
    for _ in range(int(FPS * DUR)):
        yield s


def main(outdir="cutclips"):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)

    specs = [
        ("20_static",          static_scene(),      "정지 화면 — 컷 0, PASS"),
        ("21_cuts_1hz",        cuts_at(1),          "초당 1컷 — 한도 이하, PASS"),
        ("22_cuts_3hz",        cuts_at(3),          "초당 3컷 — 한도 경계, PASS"),
        ("23_cuts_6hz",        cuts_at(6),          "초당 6컷, 휘도 동일 — **FAIL 이어야 함** (LUM 이 못 잡는 경우)"),
        ("24_cuts_10hz",       cuts_at(10),         "초당 10컷 — FAIL"),
        ("25_whip_pan",        whip_pan(),          "휙 돌리는 촬영 — 컷 0, **PASS 여야 함** (오탐 시험)"),
        ("26_fast_zoom",       fast_zoom(),         "급격한 줌 — 컷 0, **PASS 여야 함** (오탐 시험)"),
        ("27_handheld",        handheld(),          "손떨림 — 컷 0, **PASS 여야 함** (오탐 시험)"),
        ("28_flash_only_5hz",  flash_only(5),       "전면 점멸만 — 컷 채널은 PASS (LUM 의 몫)"),
        ("29_scene_plus_flash", scene_with_flash(5), "장면 고정 + 섬광 삽입 — 섬광이 컷으로 세지면 안 됨"),
    ]

    for name, gen, note in specs:
        p = out / f"{name}.mkv"
        write(p, gen)
        print(f"  생성 {p.name:<24} {note}")
    print(f"\n{len(specs)}편 생성 완료 → {out.resolve()}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "cutclips")
