# -*- coding: utf-8 -*-
"""
pseenv.py — 실행 환경 차이를 여기 한 곳에서만 흡수한다.

이걸 만든 이유
--------------------------------------------------------------------------------
스크립트들이 `/tmp/...` 를 하드코딩하고 있었다. Linux 에서만 돌던 코드라 문제가
없었지만 **Windows 에는 /tmp 가 없다**. VS Code 로 로컬에서 돌리려면 전부 깨진다.
장치 선택도 마찬가지다 — "cuda" 를 박아 두면 NVIDIA 없는 노트북에서 즉시 죽는다.
"""
from __future__ import annotations

import os
import tempfile

__all__ = ["tmp", "tmpdir", "pick_device", "device_note", "ROOT"]

ROOT = os.path.dirname(os.path.abspath(__file__))


def tmpdir(sub: str = "pse") -> str:
    """OS 에 맞는 임시 폴더. Windows 는 %TEMP%, macOS/Linux 는 /tmp."""
    d = os.path.join(tempfile.gettempdir(), sub)
    os.makedirs(d, exist_ok=True)
    return d


def tmp(name: str, sub: str = "pse") -> str:
    return os.path.join(tmpdir(sub), name)


def pick_device(prefer: str = "auto") -> str:
    """auto -> cuda > mps > cpu. 명시하면 그대로 쓰되 없으면 cpu 로 떨어진다."""
    if prefer and prefer != "auto":
        return prefer
    try:
        import torch
    except ImportError:
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def device_note(dev: str) -> str:
    """그 장치에서 이 프로젝트가 뭘 기대해도 되는지 한 줄로."""
    if dev == "cuda":
        return "NVIDIA CUDA — GPU 단계(3·4번)를 그대로 진행하세요."
    if dev == "mps":
        return ("Apple Silicon MPS — 동작은 하지만 fp32 원소별 연산 위주라 "
                "CUDA 만큼의 이득은 기대하지 마세요. 판정 일치(3번)는 꼭 확인.")
    return ("GPU 없음 — 3·4번(GPU 검증/벤치)은 의미가 없습니다. "
            "1·2번(CPU 기준선)까지만 돌리세요.")
