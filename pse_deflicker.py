# -*- coding: utf-8 -*-
"""
pse_deflicker.py — Blind Deflickering(CVPR 2023) 실행 + 광과민성 재검증 통합 스크립트

노트북 PSE_BlindDeflicker_VSCode(4).ipynb 를 하나로 합친 것. 노트북에서 났던
문제들을 구조적으로 제거했다.

  · 셀 순서 의존 없음        — 모든 단계가 필요한 것을 스스로 준비한다
  · 전역 변수 오염 없음      — SRC/STEM/BEFORE/AFTER 를 영상 이름으로 그때그때 유도
  · 파괴적 기본값 없음       — 저장소 재클론은 --force 를 명시해야만 일어난다
  · ffmpeg PATH 문제 해결    — 저장소가 셸에서 부르는 `ffmpeg` 를 bin/ 에 심어 PATH 주입
  · 한글 로그 깨짐 해결      — 자식 프로세스 출력을 로케일 인코딩으로 읽는다

사용법 (PowerShell, .venv 파이썬을 직접 호출):

    $py = "C:\\Users\\PJ07\\Desktop\\deflicker\\.venv\\Scripts\\python.exe"

    & $py pse_deflicker.py check                # 환경 점검
    & $py pse_deflicker.py setup                # 저장소 + 가중치 (최초 1회)
    & $py pse_deflicker.py corpus               # 합성 코퍼스 생성 + 검출기 검증
    & $py pse_deflicker.py list                 # 작업 폴더의 mp4 목록
    & $py pse_deflicker.py run cera_khin        # 파이프라인 1편 (--dry 로 예상시간만)
    & $py pse_deflicker.py compare cera_khin    # 좌우 비교본
    & $py pse_deflicker.py verify               # 전 영상 수치 검증 표
    & $py pse_deflicker.py frames 500           # 프레임 상한 패치

VS Code 노트북에서 쓰고 싶으면 한 셀에서:

    import pse_deflicker as X
    X.verify()
"""
from __future__ import annotations

import argparse
import json
import locale
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
# 0. 설정 — 여기만 자기 환경에 맞게
# ══════════════════════════════════════════════════════════════════════════════


ROOT = Path(r"C:\Users\PJ07\Desktop\deflicker\최종!!")

OUT_DIR = ROOT / "프레임 안줄이고 실행"
OUT_DIR.mkdir(parents=True, exist_ok=True)

REPO = Path(r"C:\Users\PJ07\Desktop\deflicker\최종!!\All-In-One-Deflicker")
TOOLS = ROOT / "tools"          # 검출기(psecore.py 또는 검출기.py), pse_spectrum.py, make_extra.py
GENRE = ROOT / "genre"          # 합성 검증 코퍼스
BIN = ROOT / "bin"              # ffmpeg.exe 를 심어둘 곳

# 검증 대상. keyword 는 원본 파일명에 들어가는 단어, scale 은 ffmpeg -vf 값(None 이면 원본)
VIDEOS: dict[str, dict] = {
    "cera_khin": {"keyword": "cera",    "scale": "scale=640:-2"},
    "anyma":     {"keyword": "anyma",   "scale": "scale=-2:640"},
    "fein":      {"keyword": "fein",  "scale": None},
    "game":      {"keyword": "game",  "scale": None},
    "pinkvenom":      {"keyword": "pinkvenom",  "scale": None},
    "anime":      {"keyword": "anime",  "scale": None},

}

PROFILES_TO_RUN = ("bt1702", "strict")
CORE_CHANNELS = ("LUM", "RED", "RG", "BY")   # 기존 v0.9 기준선과 비교 가능한 4채널

# 통합 검출기 파일명 후보. 팀에서 받은 원본이 '검출기.py' 라 이름을 안 바꿔도 되게 한다.
DETECTOR_FILES = ("psecore.py", "검출기.py", "psecore_v2.py", "detector.py")
REPO_FPS = 10                                # 저장소가 입력을 떨구는 프레임률(하드코딩)
NATIVE_FPS = True
SEC_PER_FRAME = 12                           # 실측 기반 소요시간 추정 계수

REPO_URL = "https://github.com/ChenyangLEI/All-In-One-Deflicker.git"
WEIGHTS_URL = "https://github.com/ChenyangLEI/cvpr2023_deflicker_public_folder"


# ══════════════════════════════════════════════════════════════════════════════
# 1. 공용 헬퍼
# ══════════════════════════════════════════════════════════════════════════════

_ENC = locale.getpreferredencoding(False) or "utf-8"


def run(cmd, cwd=None, env=None, check=True, quiet=False) -> int:
    """셸 없이 실행 + 실시간 로그. Windows 한글 오류 메시지가 깨지지 않게 로케일로 읽는다."""
    cmd = [str(c) for c in cmd]
    if not quiet:
        print("$", " ".join(cmd), flush=True)
    p = subprocess.Popen(
        cmd, cwd=str(cwd) if cwd else None, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding=_ENC, errors="replace", bufsize=1,
    )
    for line in p.stdout:
        if not quiet:
            print(line, end="", flush=True)
    p.wait()
    if check and p.returncode != 0:
        raise RuntimeError(f"종료 코드 {p.returncode}: {' '.join(cmd[:3])} ...")
    return p.returncode


def force_rm(path) -> None:
    """Windows 에서 .git 안 읽기전용 파일 때문에 rmtree 가 실패하는 것 방지."""
    def onerr(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onerror=onerr)


def ensure_ffmpeg() -> str:
    """
    저장소 내부 코드는 셸에서 `ffmpeg` 를 직접 부른다. 시스템에 없으면
    imageio-ffmpeg 번들 바이너리를 bin/ffmpeg.exe 로 복사하고 PATH 앞에 붙인다.
    (번들 파일명이 ffmpeg-win-x86_64-vN.exe 라 그대로는 `ffmpeg` 로 안 불린다)
    """
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    BIN.mkdir(parents=True, exist_ok=True)
    dst = BIN / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if not dst.exists():
        import imageio_ffmpeg
        shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(), dst)
        if os.name != "nt":
            dst.chmod(dst.stat().st_mode | stat.S_IEXEC)
    os.environ["PATH"] = str(BIN) + os.pathsep + os.environ["PATH"]
    return str(dst)


def child_env() -> dict:
    """저장소 하위 프로세스용 환경. ensure_ffmpeg 가 넣은 PATH 를 그대로 물려준다."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO)
    env["PYTHONUNBUFFERED"] = "1"
    return env


def open_with_player(path) -> None:
    path = str(path)
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)                       # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        print(f"  (재생기 실행 실패: {e})")


def probe(path) -> dict:
    """해상도/fps/길이. cv2 는 무겁지만 이미 의존성에 있으니 그대로 쓴다."""
    import cv2
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise IOError(f"열 수 없음: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return {"fps": fps, "dur": n / fps if fps else 0.0, "w": w, "h": h}


def find_original(keyword: str) -> Path:
    """작업 폴더에서 원본 mp4 를 찾는다. 파이프라인이 만든 파생물은 제외."""
    derived = ("_after", "_before10", "_compare")
    cands = [
        p for p in ROOT.glob("*.mp4")
        if keyword.lower() in p.name.lower()
        and not any(d in p.name for d in derived)
    ]
    if not cands:
        raise FileNotFoundError(f"'{keyword}' 가 든 원본 mp4 없음 (폴더: {ROOT})")
    return sorted(cands, key=lambda p: p.stat().st_size, reverse=True)[0]


def paths_for(name: str) -> dict:
    """영상 이름 하나로 관련 경로 전부를 유도한다 — 전역 변수 오염의 원인을 제거."""
    return {
        "src":     REPO / "data" / "test" / f"{name}.mp4",     # 저장소 입력
        "after":   REPO / "results" / name / "final" / "output.mp4",
        "after_c": OUT_DIR / f"{name}_after.mp4",              # 꺼내둔 사본
        "bef10":   OUT_DIR / f"{name}_before10.mp4",           # 수치 검증용(fps 정합)
        "cmp10":   OUT_DIR / f"{name}_compare.mp4",            # 검증용 비교본
        "cmp_o":   OUT_DIR / f"{name}_compare_orig.mp4",       # 육안용 비교본
        "frames":  REPO / "data" / "test" / name,
        "flow":    REPO / "data" / "test" / f"{name}_flow",
        "results": REPO / "results" / name,
    }


def find_detector() -> Path | None:
    """통합 검출기 파일을 찾는다. 파일명을 psecore.py 로 바꾸지 않아도 되게 후보를 훑는다."""
    for f in DETECTOR_FILES:
        q = TOOLS / f
        if q.exists():
            return q
    return None


def _load_from_path(mod_name: str, path: Path):
    """
    파일 경로에서 모듈을 직접 로드한다. 한글 파일명(검출기.py)은 `import 검출기` 로도
    되긴 하지만 캐시·도구 호환이 나쁘므로 항상 psecore 라는 이름으로 등록한다.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"로드 실패: {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod          # 모듈 내부의 상대 참조 대비
    spec.loader.exec_module(mod)
    return mod


def load_detectors():
    """
    TOOLS 의 검출기 두 종을 올린다.
      검출기(psecore) — BT.1702 판정. 채널 6종, 프로파일 방식
      pse_spectrum   — 3~30Hz 위험대역 에너지. 프레임률 무관, 지표 게이밍 검출용
    """
    det = find_detector()
    if det is None:
        raise FileNotFoundError(
            f"{TOOLS} 에 통합 검출기가 없습니다.\n"
            f"  찾은 이름 후보: {', '.join(DETECTOR_FILES)}\n"
            f"  현재 있는 .py : {sorted(q.name for q in TOOLS.glob('*.py')) or '없음'}"
        )
    if not (TOOLS / "pse_spectrum.py").exists():
        raise FileNotFoundError(f"{TOOLS} 에 pse_spectrum.py 가 없습니다.")

    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))   # pse_spectrum → pse_analyze 참조를 위해 필요

    P = _load_from_path("psecore", det)

    try:
        import pse_spectrum as S                               # noqa: E402
    except ModuleNotFoundError as e:
        if "pse_analyze" in str(e):
            raise ModuleNotFoundError(
                "pse_spectrum.py 가 pse_analyze 를 import 합니다.\n"
                f"  pse_analyze.py 를 {TOOLS} 에 두거나, 해당 import 줄을\n"
                "    SDR_PEAK = 200.0\n"
                "    def decode_linear(f):\n"
                "        rgb = f[..., ::-1].astype(np.float32) / 255.0\n"
                "        return np.power(rgb, 2.4, dtype=np.float32)\n"
                "  로 바꾸세요."
            ) from e
        raise

    import importlib
    importlib.reload(S)                  # 스크립트를 고치고 다시 돌릴 때 대비
    return P, S


# ══════════════════════════════════════════════════════════════════════════════
# 2. check — 환경 점검
# ══════════════════════════════════════════════════════════════════════════════

def check() -> None:
    print("python :", sys.version.split()[0])
    print("exe    :", sys.executable)
    if ".venv" not in sys.executable:
        print("   [!] .venv 파이썬이 아닙니다. .venv\\Scripts\\python.exe 로 실행하세요.")

    try:
        import torch
        print("torch  :", torch.__version__, "| cuda:", torch.cuda.is_available())
        if torch.cuda.is_available():
            p = torch.cuda.get_device_properties(0)
            arch = torch.cuda.get_arch_list()
            # cubin 은 같은 메이저 세대 안에서 상위 마이너로 호환된다 (sm_86 → sm_89 OK)
            ok = any(a.startswith("sm_") and a[3] == str(p.major)
                     and int(a[4:]) <= p.minor for a in arch)
            print(f"gpu    : {p.name}  sm_{p.major}{p.minor}  "
                  f"{p.total_memory / 1e9:.1f} GB  | 커널 호환: {'OK' if ok else '재설치 필요'}")
        else:
            print("   [!] CPU 로는 사실상 못 돌립니다.")
    except ImportError:
        print("torch  : 없음")

    try:
        import numpy as np
        print("numpy  :", np.__version__,
              "" if np.__version__.startswith("1.") else "  [!] torch 2.1 은 numpy<2 필요")
    except ImportError:
        print("numpy  : 없음")

    for mod in ("cv2", "easydict", "tqdm", "tensorboard", "imageio_ffmpeg", "skimage"):
        try:
            __import__(mod)
            print(f"{mod:14}: OK")
        except ImportError:
            print(f"{mod:14}: 없음  → pip install {mod}")

    print("ffmpeg :", ensure_ffmpeg())
    print("git    :", shutil.which("git") or "없음 → winget install Git.Git")
    print("ROOT   :", ROOT, "" if ROOT.exists() else "  [!] 없음")
    print("REPO   :", REPO, "" if (REPO / "test.py").exists() else "  [!] setup 필요")
    print("TOOLS  :", TOOLS, sorted(p.name for p in TOOLS.glob("*.py")) if TOOLS.exists() else "[!] 없음")
    det = find_detector() if TOOLS.exists() else None
    print("검출기 :", det.name if det else f"[!] 없음 — 후보 {', '.join(DETECTOR_FILES)}")
    print("스펙트럼:", "pse_spectrum.py"
          if (TOOLS / "pse_spectrum.py").exists() else "[!] 없음")


# ══════════════════════════════════════════════════════════════════════════════
# 3. setup — 저장소 + 가중치
# ══════════════════════════════════════════════════════════════════════════════

def setup(force: bool = False) -> None:
    """force=True 는 저장소를 통째로 지운다 — results/ 의 실행 결과도 같이 사라진다."""
    if force:
        if REPO.exists():
            done = [p.name for p in (REPO / "results").iterdir()] if (REPO / "results").exists() else []
            if done:
                print(f"[!] results/ 에 결과 {len(done)}건이 있습니다: {', '.join(done)}")
                if input("    정말 지우고 다시 받을까요? (yes 입력) ").strip().lower() != "yes":
                    print("    취소했습니다.")
                    return
            force_rm(REPO)

    if not (REPO / "test.py").exists():
        if not shutil.which("git"):
            raise RuntimeError("git 이 없습니다. winget install Git.Git 후 터미널을 새로 여세요.")
        run(["git", "clone", REPO_URL, REPO])
    else:
        print("저장소 이미 있음:", REPO)

    weights = REPO / "pretrained_weights"
    if not weights.exists():
        tmp = ROOT / "_weights_tmp"
        if tmp.exists():
            force_rm(tmp)
        run(["git", "clone", WEIGHTS_URL, tmp])
        shutil.move(str(tmp / "pretrained_weights"), str(weights))
        force_rm(tmp)

    total = sum(f.stat().st_size for f in weights.rglob("*") if f.is_file())
    for f in sorted(weights.rglob("*")):
        if f.is_file():
            print(f"  {f.relative_to(weights)}  {f.stat().st_size / 1e6:.1f} MB")
    print(f"가중치 합계 {total / 1e6:.1f} MB")
    ensure_ffmpeg()


# ══════════════════════════════════════════════════════════════════════════════
# 4. frames — 프레임 상한 패치
# ══════════════════════════════════════════════════════════════════════════════

def frames(new_max: int) -> None:
    """
    stage1 atlas 의 최대 프레임 수를 올린다. 이걸 안 올리면 긴 영상에서
    'the number of style frames is different from the number of content frames'
    로 마지막 단계에서 죽는다. 올릴수록 시간과 VRAM 이 선형으로 는다.
    """
    patched = 0
    for cfg in REPO.rglob("*.json"):
        if "results" in cfg.parts or "data" in cfg.parts:
            continue
        try:
            d = json.loads(cfg.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        for k, v in list(d.items()):
            if "maximum" in k.lower() and "frame" in k.lower() and isinstance(v, int):
                print(f"  {cfg.relative_to(REPO)}  {k} = {v}")
                if v < new_max:
                    bak = cfg.with_suffix(cfg.suffix + ".bak")
                    if not bak.exists():
                        shutil.copy2(cfg, bak)
                    d[k] = new_max
                    cfg.write_text(json.dumps(d, indent=2), encoding="utf-8")
                    print(f"    → {new_max} 로 패치 (백업 {bak.name})")
                    patched += 1
    print(f"패치 {patched}건" if patched else "패치할 항목 없음 (이미 충분하거나 키 이름이 다름)")


# ══════════════════════════════════════════════════════════════════════════════
# 5. run — 영상 1편 파이프라인
# ══════════════════════════════════════════════════════════════════════════════

def prepare(name: str) -> Path:
    """원본을 찾아 ASCII 이름 + 지정 해상도로 저장소 입력 위치에 넣는다."""
    spec = VIDEOS[name]
    orig = find_original(spec["keyword"])
    info = probe(orig)
    est_frames = info["dur"] * REPO_FPS
    print(f"원본: {orig.name}")
    print(f"      {info['w']}x{info['h']}  {info['fps']:.2f}fps  {info['dur']:.1f}초"
          f"  →  약 {est_frames:.0f}프레임")
    print(f"예상 소요: 약 {est_frames * SEC_PER_FRAME / 60:.0f}분")

    P = paths_for(name)
    P["src"].parent.mkdir(parents=True, exist_ok=True)
    ff = ensure_ffmpeg()
    cmd = [ff, "-y", "-i", orig]
    if spec["scale"]:
        cmd += ["-vf", spec["scale"]]
    cmd += ["-c:v", "libx264", "-crf", "16", "-an", P["src"]]
    run(cmd, quiet=False)
    return P["src"]


def run_video(name: str, dry: bool = False, clean: bool = True) -> None:
    if name not in VIDEOS:
        raise KeyError(f"모르는 이름: {name}  (가능: {', '.join(VIDEOS)})")
    if not (REPO / "test.py").exists():
        raise RuntimeError("저장소가 없습니다. 먼저 setup 을 실행하세요.")

    p = paths_for(name)
    if dry:
        info = probe(find_original(VIDEOS[name]["keyword"]))
        fps_use = round(info["fps"]) if NATIVE_FPS else REPO_FPS
        est = info["dur"] * fps_use
        print(f"[dry] {name}: {info['w']}x{info['h']} {info['fps']:.2f}fps "
              f"{info['dur']:.1f}초 → {fps_use}fps 로 약 {est:.0f}프레임, "
              f"약 {est * SEC_PER_FRAME / 60:.0f}분")
        return
        

    if clean:  # 이전 잔여물이 남으면 프레임 수가 안 맞아 마지막 단계에서 죽는다
        for d in (p["frames"], p["flow"], p["results"]):
            shutil.rmtree(d, ignore_errors=True)

    src = prepare(name)
    fps_use = round(probe(src)["fps"]) if NATIVE_FPS else REPO_FPS
    print(f"추출 프레임률: {fps_use}fps")
    t0 = time.time()
    run([sys.executable, "test.py", "--video_name", f"data/test/{src.name}", "--fps", str(fps_use)],
        cwd=REPO, env=child_env())
    print(f"\n소요 {(time.time() - t0) / 60:.1f}분")

    if not p["after"].exists():
        found = sorted(p["results"].rglob("*.mp4"), key=lambda q: q.stat().st_mtime, reverse=True)
        raise FileNotFoundError(
            f"출력 없음: {p['after']}\n"
            + ("있는 mp4:\n  " + "\n  ".join(str(q) for q in found[:10]) if found
               else "results/ 가 비었습니다. 위 로그에서 실패 지점을 확인하세요.")
        )

    shutil.copy2(p["after"], p["after_c"])
    ensure_before10(name)
    print("\nAFTER  :", p["after_c"])
    print("BEFORE :", p["bef10"])


def ensure_before10(name: str) -> Path:
    """
    수치 검증용 BEFORE. 저장소가 입력을 10fps 로 떨구므로 원본(24/30fps)과
    직접 비교하면 '프레임을 버린 것만으로 줄어든 몫'이 신경망 성과로 잡힌다.
    """
    p = paths_for(name)
    if NATIVE_FPS:
        return p["src"]
    if not p["bef10"].exists():
        if not p["src"].exists():
            raise FileNotFoundError(f"저장소 입력이 없습니다: {p['src']}")
        run([ensure_ffmpeg(), "-y", "-i", p["src"], "-vf", f"fps={REPO_FPS}",
             "-c:v", "libx264", "-crf", "16", "-an", p["bef10"]], quiet=True)
    return p["bef10"]


# ══════════════════════════════════════════════════════════════════════════════
# 6. compare — 좌우 비교본
# ══════════════════════════════════════════════════════════════════════════════

def compare(name: str, visual: bool = True, width: int = 480, play: bool = True) -> Path:
    """
    visual=True  : 원본(원래 fps) vs 결과 — 육안 확인용
    visual=False : 10fps BEFORE vs 결과 — 수치 검증과 같은 조건
    """
    p = paths_for(name)
    after = p["after"] if p["after"].exists() else p["after_c"]
    if not after.exists():
        raise FileNotFoundError(f"결과가 없습니다: {name}  (먼저 run 하세요)")

    if visual:
        left = find_original(VIDEOS[name]["keyword"])
        fps = probe(left)["fps"]
        out = p["cmp_o"]
    else:
        left = ensure_before10(name)
        fps = REPO_FPS
        out = p["cmp10"]

    fc = (f"[0:v]fps={fps:g},scale={width}:-2,setsar=1[a];"
          f"[1:v]fps={fps:g},scale={width}:-2,setsar=1[b];"
          f"[a][b]hstack=inputs=2")
    run([ensure_ffmpeg(), "-y", "-i", left, "-i", after, "-filter_complex", fc,
         "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-an", out])
    print("생성:", out)
    if play:
        open_with_player(out)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 7. corpus — 합성 코퍼스 생성 + 검출기 자체 검증
# ══════════════════════════════════════════════════════════════════════════════

def corpus() -> None:
    """
    정답을 아는 합성 클립으로 검출기가 제대로 도는지 먼저 확인한다.
    이게 통과해야 실제 영상 수치를 믿을 수 있다.
    """
    ensure_ffmpeg()
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))

    if (TOOLS / "make_extra.py").exists():
        import make_extra as MK
        GENRE.mkdir(parents=True, exist_ok=True)
        specs = [
            ("27_anime_cuts_10ps", MK.anime_fast,
             "FAIL 기대 — 급컷 10회/s = 5플래시/s (한도 3 초과)"),
            ("28_blue_strobe_5hz", MK.blue_strobe,
             "휘도축으로는 원리적 검출 불가 — RGB/BY 축이 잡아야 함"),
        ]
        for fname, fn, note in specs:
            out = GENRE / f"{fname}.mp4"
            if out.exists():
                print(f"  이미 있음 {out.name}")
            else:
                fr, w, h, fps = fn()
                MK.write(fr, str(out), w, h, fps)
            print(f"     기대: {note}")
    else:
        print(f"[!] make_extra.py 없음 ({TOOLS}) — 생성은 건너뛰고 기존 클립만 검증합니다")

    clips = sorted(GENRE.glob("*.mp4")) if GENRE.exists() else []
    if not clips:
        print("검증할 클립이 없습니다.")
        return

    P, _ = load_detectors()
    print(f"\npsecore {P.__version__} | 채널 {P.CHANNELS}")
    for f in clips:
        print(f"\n── {f.name}")
        for prof in PROFILES_TO_RUN:
            rep = P.analyze(str(f), P.PROFILES[prof], profile_name=prof)
            failed = sorted({s.channel for s in rep.segments})
            warned = sorted({s.channel for s in rep.warn_segments})
            print(f"   [{prof:7}] {rep.verdict:4}  FAIL={failed or '-'}  WARN={warned or '-'}")


# ══════════════════════════════════════════════════════════════════════════════
# 8. verify — 수치 검증 표
# ══════════════════════════════════════════════════════════════════════════════

def _seg_seconds(segs) -> dict:
    d: dict[str, float] = {}
    for s in segs:
        d[s.channel] = d.get(s.channel, 0.0) + (s.end_ms - s.start_ms) / 1000.0
    return d


def verify(names: list[str] | None = None, t0=None, t1=None) -> list[dict]:
    """
    BT.1702 판정과 3~30Hz 대역 에너지를 같이 본다.
    판정만 좋아지고 에너지가 그대로면 지표 게이밍이므로 폐기 대상.
    """
    P, S = load_detectors()
    names = names or list(VIDEOS)
    rows = []

    for name in names:
        p = paths_for(name)
        after = p["after"] if p["after"].exists() else p["after_c"]
        if not after.exists():
            print(f"\n[{name}] 결과 없음 — 건너뜀")
            continue
        try:
            bef = ensure_before10(name)
        except FileNotFoundError as e:
            print(f"\n[{name}] BEFORE 준비 실패: {e}")
            continue

        print(f"\n{'=' * 74}\n{name}")
        ref = S.measure(str(bef), t0=t0, t1=t1)
        for path, tag in ((bef, "이전"), (after, "이후")):
            for prof in PROFILES_TO_RUN:
                rep = P.analyze(str(path), P.PROFILES[prof], profile_name=prof)
                fs = _seg_seconds(rep.segments)
                ws = _seg_seconds(rep.warn_segments)
                core = sum(fs.get(k, 0.0) for k in CORE_CHANNELS)
                print(f"  [{tag}/{prof:7}] {rep.verdict:4}"
                      f"  4채널 {core:6.1f}s  전체 {sum(fs.values()):6.1f}s"
                      f"  FAIL={sorted(fs) or '-'}  WARN={sorted(ws) or '-'}")
                rows.append({"video": name, "stage": tag, "profile": prof,
                             "verdict": rep.verdict, "core_sec": round(core, 2),
                             "all_sec": round(sum(fs.values()), 2),
                             "fail": sorted(fs), "warn": sorted(ws)})
            m = S.measure(str(path), t0=t0, t1=t1)
            print("   ", S.brief(m, ref).strip())
            rows[-1]["band_3_30"] = m["band_3_30"]
            rows[-1]["band_10_20"] = m["band_10_20"]

    if rows:
        out = ROOT / "verify_report.json"
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n저장: {out}")
    return rows


def list_videos() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    print(f"{ROOT} 의 mp4:")
    for p in sorted(ROOT.glob("*.mp4")):
        print(f"  {p.stat().st_size / 1e6:8.1f} MB  {p.name}")
    print("\n등록된 대상:")
    for name, spec in VIDEOS.items():
        pp = paths_for(name)
        done = "완료" if (pp["after"].exists() or pp["after_c"].exists()) else "미실행"
        try:
            orig = find_original(spec["keyword"]).name
        except FileNotFoundError:
            orig = "(원본 못 찾음)"
        print(f"  {name:11} [{done}]  keyword='{spec['keyword']}'  {orig}")


# ══════════════════════════════════════════════════════════════════════════════
# 9. CLI
# ══════════════════════════════════════════════════════════════════════════════

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="환경 점검")

    sp = sub.add_parser("setup", help="저장소 + 가중치 준비")
    sp.add_argument("--force", action="store_true", help="저장소를 지우고 다시 받는다 (결과도 삭제)")

    sp = sub.add_parser("frames", help="stage1 프레임 상한 패치")
    sp.add_argument("max", type=int)

    sub.add_parser("list", help="영상 목록/상태")
    sub.add_parser("corpus", help="합성 코퍼스 생성 + 검출기 검증")

    sp = sub.add_parser("run", help="영상 1편 파이프라인")
    sp.add_argument("name", choices=list(VIDEOS))
    sp.add_argument("--dry", action="store_true", help="예상 시간만 보고 끝")
    sp.add_argument("--keep", action="store_true", help="이전 중간 산출물을 지우지 않는다")

    sp = sub.add_parser("compare", help="좌우 비교본 생성")
    sp.add_argument("name", choices=list(VIDEOS))
    sp.add_argument("--numeric", action="store_true", help="10fps 끼리 비교(검증 조건과 동일)")
    sp.add_argument("--width", type=int, default=480)
    sp.add_argument("--no-play", action="store_true")

    sp = sub.add_parser("verify", help="수치 검증 표")
    sp.add_argument("names", nargs="*", default=[],
                    help=f"비우면 전부. 가능: {', '.join(VIDEOS)}")
    sp.add_argument("--t0", type=float, default=None)
    sp.add_argument("--t1", type=float, default=None)

    a = ap.parse_args(argv)

    if a.cmd == "check":
        check()
    elif a.cmd == "setup":
        setup(force=a.force)
    elif a.cmd == "frames":
        frames(a.max)
    elif a.cmd == "list":
        list_videos()
    elif a.cmd == "corpus":
        corpus()
    elif a.cmd == "run":
        run_video(a.name, dry=a.dry, clean=not a.keep)
    elif a.cmd == "compare":
        compare(a.name, visual=not a.numeric, width=a.width, play=not a.no_play)
    elif a.cmd == "verify":
        verify(list(a.names) or None, t0=a.t0, t1=a.t1)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n중단됨")
        raise SystemExit(130)
    except Exception as e:
        print(f"\n오류: {type(e).__name__}: {e}", file=sys.stderr)
        raise SystemExit(1)



