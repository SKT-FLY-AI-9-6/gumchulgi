# -*- coding: utf-8 -*-
"""이 브랜치를 돌릴 준비가 됐는지 점검한다. 없는 것마다 할 일을 알려준다.

    python check_setup.py

이 브랜치는 **단독으로 돌지 않는다.** 검출기·이질감 자는 fix/ste-report-consistency
브랜치에 있고, 영상은 팀 규칙상 커밋하지 않는다. 무엇이 비었는지 여기서 확인한다.
"""
from __future__ import annotations

import importlib
import os
import shutil
import sys

OK, NO = "  [OK]  ", "  [--]  "
todo: list[str] = []


def head(t):
    print("\n" + t)
    print("-" * 66)


def need(cond, label, fix):
    print((OK if cond else NO) + label)
    if not cond:
        todo.append(fix)
    return cond


# ── 1. 파이썬 패키지 ────────────────────────────────────────────────────
head("1. 파이썬 패키지")
need(sys.version_info >= (3, 10),
     "Python %d.%d" % sys.version_info[:2], "Python 3.10 이상을 쓸 것")

for mod, why in (("cv2", "opencv-python"), ("numpy", "numpy"),
                 ("torch", "torch"), ("torchvision", "torchvision")):
    try:
        m = importlib.import_module(mod)
        need(True, "%s %s" % (mod, getattr(m, "__version__", "")), "")
    except ImportError:
        need(False, mod, "pip install %s" % why)

try:
    import torch
    cuda = torch.cuda.is_available()
    print((OK if cuda else NO) + "CUDA %s" % (
        torch.cuda.get_device_name(0) if cuda else "없음"))
    if not cuda:
        todo.append("GPU 판(psegpu_full)은 CUDA 가 필요하다. "
                    "CPU 판(pselive3)만 쓰려면 무시해도 된다")
except Exception:
    pass

# ── 2. ffmpeg ──────────────────────────────────────────────────────────
head("2. ffmpeg (seam 의 대조군 인코딩에 필요)")
if not need(shutil.which("ffmpeg") is not None, "ffmpeg on PATH",
            "imageio-ffmpeg 가 있으면 번들을 심으면 된다:\n"
            "       python -c \"import imageio_ffmpeg,shutil;"
            "shutil.copy(imageio_ffmpeg.get_ffmpeg_exe(),'ffmpeg.exe')\"\n"
            "       그리고 그 폴더를 PATH 앞에 붙일 것"):
    pass

# ── 3. 옆 브랜치 모듈 ───────────────────────────────────────────────────
head("3. 같은 폴더에 있어야 하는 모듈  (fix/ste-report-consistency)")
missing = []
for mod in ("psecore", "pseenv", "rawmeasure", "seam", "tier", "psepipe",
            "pse_bt1702", "pse_cut", "pse_pattern", "pse_spectrum"):
    try:
        importlib.import_module(mod)
        print(OK + mod + ".py")
    except Exception as e:
        print(NO + "%s.py  (%s)" % (mod, type(e).__name__))
        missing.append(mod)
if missing:
    todo.append(
        "옆 브랜치를 받아 이 폴더에 합칠 것 —\n"
        "       git clone -b fix/ste-report-consistency <repo> base\n"
        "       cp base/psepipe_v3_seam/*.py .\n"
        "       그다음 filters/ 의 두 파일로 덮어쓸 것 (그쪽이 더 낡았다)")

# ── 4. 필터 파일 ───────────────────────────────────────────────────────
head("4. 필터 — 두 수정이 모두 들어 있는가")
for f, marks in (("pselive3.py", ("cut_min_gap_s", "net_directional")),
                 ("psegpu_full.py", ("since_cut", "net_directional"))):
    p = f if os.path.exists(f) else os.path.join("filters", f)
    if not os.path.exists(p):
        need(False, f, "filters/%s 를 실행 폴더로 복사할 것" % f)
        continue
    s = open(p, encoding="utf-8").read()
    for mk, label in zip(marks, ("컷 불응기 (Kim&Moon)", "순 방향성 (seunghoon)")):
        need(mk in s, "%s — %s" % (f, label),
             "%s 에 %s 가 없다. filters/ 의 파일로 덮어쓸 것" % (f, label))

# ── 5. 영상 ────────────────────────────────────────────────────────────
head("5. 입력 영상  (팀 규칙상 커밋하지 않는다 — 환경변수로 알려줄 것)")
for env, dflt, what in (
        ("PSE_FLAGGED", "data/s1_flagged", "플래시 라벨 릴스 10편"),
        ("PSE_EXPLORE", "data/explore_100", "Explore 무작위 릴스"),
        ("PSE_CERA", "cera_640.mp4", "cera_640.mp4 (기준 클립)")):
    p = os.environ.get(env, dflt)
    ok = os.path.exists(p)
    n = (len([x for x in os.listdir(p) if x.endswith(".mp4")])
         if ok and os.path.isdir(p) else "")
    print((OK if ok else NO) + "%-12s %s %s" % (env, p, ("(%s편)" % n) if n else ""))
    if not ok:
        todo.append("set %s=<%s 가 있는 경로>" % (env, what))

# ── 정리 ───────────────────────────────────────────────────────────────
print()
print("=" * 66)
if not todo:
    print("준비 완료. 다음을 돌릴 수 있다:")
    print()
    print("  python run_rebased.py     대표 8편 — 순 방향성 효과 (약 45분)")
    print("  python run_hyst.py        히스테리시스 변형 (기각됨, 재현용)")
    print("  python diag_regen.py      회귀 + 마스크 토글 진단 (약 5분)")
    print("  python run_detail.py      detail_sigma 스윕 — 잔상 (약 20분)")
    print()
    print("결과는 results_*.csv 로 떨어진다. results/ 의 값과 비교할 것.")
else:
    print("할 일 %d 가지" % len(todo))
    for i, t in enumerate(todo, 1):
        print("\n  %d) %s" % (i, t))
print("=" * 66)
