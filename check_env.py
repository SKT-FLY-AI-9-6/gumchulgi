# -*- coding: utf-8 -*-
"""check_env.py — 측정을 시작해도 되는 환경인지 10초 안에 확인한다."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time

ok_all = True


def line(name, ok, detail="", fatal=True):
    """fatal=False 는 '없어도 되는 것' — GPU 관련은 전부 여기 해당."""
    global ok_all
    if fatal:
        ok_all = ok_all and ok
    tag = "OK" if ok else ("NG" if fatal else "--")
    print(f"  [{tag}] {name:<26} {detail}")


print("환경 점검\n")

# ── 파이썬 / numpy / opencv
print(f"  python {sys.version.split()[0]}")
try:
    import numpy as np
    line("numpy", True, np.__version__)
except ImportError:
    line("numpy", False, "pip install numpy")
    sys.exit(1)
try:
    import cv2
    line("opencv", True, f"{cv2.__version__}  threads={cv2.getNumThreads()}")
except ImportError:
    line("opencv", False, "pip install opencv-python-headless")
    sys.exit(1)

line("cpu cores", True, str(os.cpu_count()))
try:
    import pseenv as ENV
    line("pseenv", True, f"임시폴더 {ENV.tmpdir()}")
except Exception as e:
    line("pseenv", False, repr(e))

# ── ffmpeg
ff = shutil.which("ffmpeg")
line("ffmpeg", ff is not None, ff or "설치 필요 (apt install ffmpeg)")

# ── FFV1 무손실 왕복  ← 이게 깨지면 이후 측정이 전부 무의미
if ff:
    try:
        import rawmeasure as RM
        rng = np.random.default_rng(0)
        fr = [rng.integers(0, 256, (64, 96, 3), dtype=np.uint8) for _ in range(8)]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.mkv")
            RM.write_lossless(fr, p, 24)
            n, bad = RM.verify_roundtrip(fr, p)
        line("FFV1 무손실 왕복", n == 8 and bad == 0, f"{n}프레임 불일치 {bad}")
    except Exception as e:
        line("FFV1 무손실 왕복", False, repr(e))

# ── 프로젝트 모듈
for m in ("psecore", "pselive3"):
    try:
        __import__(m)
        line(m, True)
    except Exception as e:
        line(m, False, repr(e))

# ── 코퍼스
import glob
n_clip = len(glob.glob("synth/*.mp4")) + len(glob.glob("genre/*.mp4")) \
    + (1 if os.path.exists("run3/seg6.mp4") else 0)
line("검증 코퍼스", n_clip >= 27, f"{n_clip}클립 (기대 27)")

# ── torch / CUDA
try:
    import torch
    line("torch", True, torch.__version__, fatal=False)
    if torch.cuda.is_available():
        p = torch.cuda.get_device_properties(0)
        bw = p.memory_clock_rate * 2 * (p.memory_bus_width / 8) / 1e6 \
            if hasattr(p, "memory_clock_rate") else None
        line("CUDA", True,  f"{p.name}  {p.total_memory/2**30:.1f} GiB  "
                           f"SM {p.multi_processor_count}"
                           + (f"  ~{bw:.0f} GB/s" if bw else ""))
        a = torch.randn(4096, 4096, device="cuda")
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(20):
            b = a * 1.0001
        torch.cuda.synchronize()
        dt = (time.perf_counter() - t0) / 20
        gbs = a.numel() * 4 * 2 / dt / 1e9
        line("GPU 실효 대역폭", gbs > 50, f"{gbs:.0f} GB/s (원소별 곱 기준)", fatal=False)
        print(f"\n  참고: 1080p 정확 경로는 프레임당 약 370 MB 를 왕복합니다.")
        print(f"        {gbs:.0f} GB/s 이면 이론상 {370/gbs:.2f} ms/frame "
              f"= {1000/max(370/gbs,1e-9):.0f} fps 가 상한입니다.")
    elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        line("MPS (Apple)", True, "동작하지만 CUDA 만큼의 이득은 기대하지 마세요", fatal=False)
    else:
        line("가속 장치", False, "GPU 를 못 찾았습니다 — 1·2단계까지만 유효합니다", fatal=False)
except ImportError:
    line("torch", False, "GPU 를 쓸 때만 필요합니다 (없어도 1·2단계는 됩니다)", fatal=False)

try:
    import pseenv as ENV
    d = ENV.pick_device("auto")
    print(f"\n  선택된 장치: {d}\n  {ENV.device_note(d)}")
except Exception:
    pass

print(f"\n{'준비 완료 — README.md 1절(F5)로' if ok_all else 'NG 항목부터 해결하세요 (-- 는 없어도 되는 것)'}")
sys.exit(0 if ok_all else 1)
