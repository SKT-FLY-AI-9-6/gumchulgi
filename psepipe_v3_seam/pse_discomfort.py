# -*- coding: utf-8 -*-
"""pse_discomfort — 시각 불쾌감 통합 지표 (1/f 스펙트럼 이탈)

근거
----
자연 영상의 푸리에 진폭 스펙트럼은 공간주파수 f 에 대해 대략 1/f 로 떨어진다.
이 통계에서 벗어난 이미지 — 특정 주파수(특히 3 cpd 부근)에 에너지가 몰린
이미지 — 일수록 시각 불쾌감 평정이 높다는 것이 반복 확인돼 있다.

- Fernandez & Wilkins (2008) Perception 37:1098-1113 — 예술·자연 이미지에서
  불쾌감이 1/f 이탈과 상관.
- Penacchio & Wilkins (2015) Vision Res 108:1-7 — 진폭 스펙트럼의 자연영상
  기준 이탈(잔차)을 CSF 로 가중해 합산한 지표가 불쾌감을 예측.
- 후속 구현(ViStA, Buildings 2025;15:2208)의 공개된 절차: 시야 2° 타일을
  64×64 로 리샘플 → 타일별 진폭 스펙트럼 → 자연영상 기준 원뿔에 맞춘 잔차 →
  Mannos-Sakrison CSF 가중 합산.

구현 노트 (원 논문과의 차이)
---------------------------
원 논문의 기준은 보정된 자연영상 350장 의 평균 스펙트럼(수직·수평 방향에
초과 에너지가 있는 비등방 원뿔)이다. 자연영상 코퍼스 없이 쓸 수 있도록
여기서는 **타일별 최적적합 1/f^α 를 기준**으로 삼고, 그 위로 남는 양의
잔차만 CSF 가중으로 합산한다 (Fernandez & Wilkins 계열의 단순화).
따라서 절대값은 원 논문 수치와 다르며, **영상 간·구간 간 상대 비교용**이다.
규격 판정이 아니라 컴포트 점수의 한 성분으로만 쓸 것.

시야각 가정
-----------
공간주파수(cpd)는 픽셀이 아니라 시야각의 함수라 시청 거리 가정이 필요하다.
기본값 PX_PER_DEG=32 는 후속 구현과 같은 값이며, 폰을 약 30cm 에서 보는
일반적인 쇼츠 시청(1080px 세로 ≈ 화면 약 15cm)과 대략 맞는다. 시청 환경이
다르면 인자로 바꿀 것 — 값이 두 배 틀려도 CSF 피크가 2~8 cpd 로 넓어
순위는 크게 안 뒤집힌다.

사용
----
    import pse_discomfort as pd

    s = pd.frame_score(gray_or_bgr_frame)          # 프레임 1장 → float
    r = pd.analyze("clip.mp4")                     # 영상 → 요약 dict
    # r = {"mean": .., "p95": .., "max": .., "series": [..], "fps": ..}

의존성: numpy, (analyze 에만) opencv-python
"""

from __future__ import annotations

import numpy as np

PX_PER_DEG = 32          # 픽셀/시야도. 위 '시야각 가정' 참조.
TILE_DEG = 2.0           # 타일 한 변의 시야각 (후속 구현과 동일: 2°)
TILE_OVERLAP = 0.5       # 타일 겹침 비율 (동일: 50%)
_EPS = 1e-9


# ─────────────────────────────────────────────── 주파수 가중
def band_weight(f_cpd: np.ndarray, peak: float = 3.0,
                sigma_oct: float = 1.0) -> np.ndarray:
    """시각 스트레스 대역 가중 — 3 cpd 중심 로그가우시안 (옥타브 폭 1).

    Wilkins 계열 실측(패턴 글레어 1~4 cpd, 최대 3 cpd)과 편두통 근거표의
    위험 대역을 그대로 가중으로 옮긴 것. Penacchio & Wilkins (2015)는
    CSF(Mannos-Sakrison) 가중을 썼지만 그 함수는 8 cpd 부근이 피크라
    편두통 대역(3 cpd)과 어긋난다 — 본 지표는 편두통 컴포트 성분이
    목적이므로 문헌 대역을 우선했다. csf() 도 참고용으로 남겨둔다.
    """
    w = np.exp(-np.square(np.log2(np.maximum(f_cpd, _EPS) / peak))
               / (2.0 * sigma_oct ** 2))
    return np.where(f_cpd < 0.5, 0.0, w)


def csf(f_cpd: np.ndarray) -> np.ndarray:
    """Mannos & Sakrison (1974) 대비감도함수 — 참고용.

    A(f) = 2.6 (0.0192 + 0.114 f) exp(-(0.114 f)^1.1)
    """
    a = 0.114 * f_cpd
    out = 2.6 * (0.0192 + a) * np.exp(-np.power(a, 1.1))
    return np.where(f_cpd < 0.5, 0.0, out)


# ─────────────────────────────────────────────── 타일 하나의 이탈 점수
def _tile_score(tile: np.ndarray, px_per_deg: float) -> float:
    """64×64 휘도 타일 → CSF 가중 1/f 초과 에너지 (스칼라).

    1) 한창(Hann)으로 경계 누설 억제 후 FFT 진폭
    2) log A ~ log f 선형회귀로 최적 1/f^α 적합 (DC 제외)
    3) 적합선 **위로 남는** 양의 잔차를 위험 대역 가중(3 cpd 피크)으로 평균
    4) 타일 RMS 대비를 곱해 스케일 — 대비가 없으면 이탈도 없다
       (로그 잔차만 쓰면 저대비 줄무늬가 고대비와 같은 점수가 되는 결함이
       실측에서 확인돼 넣은 항이다. 균일 화면은 정확히 0 이 된다.)
    """
    n = tile.shape[0]
    w = np.hanning(n)
    zero_mean = tile - tile.mean()
    rms = float(zero_mean.std())                     # 대비 스케일 (0~약 0.5)
    if rms < 1e-3:                                   # 사실상 균일 → 이탈 없음
        return 0.0
    win = zero_mean * w[:, None] * w[None, :]
    amp = np.abs(np.fft.fftshift(np.fft.fft2(win)))

    fy = np.fft.fftshift(np.fft.fftfreq(n, d=1.0 / px_per_deg))
    fx = fy
    f = np.hypot(fy[:, None], fx[None, :])          # cpd 격자

    mask = f > 0.5                                   # DC·초저주파 제외
    logf = np.log(f[mask])
    loga = np.log(amp[mask] + _EPS)

    # 최적적합 1/f^α:  log A = c − α·log f
    alpha, c = np.polyfit(logf, loga, 1)
    fit = c + alpha * logf

    # 초과 에너지는 **선형 진폭 영역**에서 잰다. 로그 잔차로 재면 창(Hann)
    # 누설 스커트가 노이즈 플로어 대비 수십 dB 위라 넓은 면적이 전부
    # '초과'로 잡혀, 대역 밖 스파이크도 점수가 비슷해지는 결함이 있었다.
    a_lin = amp[mask]
    excess = np.maximum(a_lin - np.exp(fit), 0.0)    # 1/f 적합 위 초과 진폭
    wgt = band_weight(f[mask])
    s = float((excess * wgt).sum() / (a_lin.sum() + _EPS))
    return s * min(1.0, rms / 0.25)                  # 대비 스케일 (0.25≈고대비)


# ─────────────────────────────────────────────── 프레임 점수
def frame_score(frame: np.ndarray, px_per_deg: float = PX_PER_DEG) -> float:
    """프레임(그레이 또는 BGR uint8) → 불쾌감 이탈 점수.

    시야 2° 타일(64×64, 50% 겹침)별 점수의 평균과 최대를 절반씩 섞는다 —
    국소적으로 강한 줄무늬(최대)와 화면 전반의 질감(평균)을 모두 반영.
    """
    if frame.ndim == 3:                              # BGR → 휘도 (Rec.709)
        b, g, r = frame[..., 0], frame[..., 1], frame[..., 2]
        gray = 0.0722 * b + 0.7152 * g + 0.2126 * r
    else:
        gray = frame.astype(np.float64)
    gray = gray.astype(np.float64) / 255.0

    tile_px = 64
    # 입력 해상도를 px_per_deg 기준으로 재해석: 타일 = TILE_DEG 도 = 64px
    need = int(round(TILE_DEG * px_per_deg))         # 원본에서 타일이 차지할 px
    h, w = gray.shape
    if min(h, w) < need:                             # 너무 작으면 통짜 1타일
        import numpy as _np
        side = min(h, w)
        tile = gray[:side, :side]
        tile = _resize64(tile)
        return _tile_score(tile, px_per_deg)

    step = max(1, int(need * (1.0 - TILE_OVERLAP)))
    tiles = []
    for y in range(0, h - need + 1, step):
        for x in range(0, w - need + 1, step):
            tiles.append(_resize64(gray[y:y + need, x:x + need]))
    s = _tile_scores_batch(np.stack(tiles), px_per_deg)
    return float(0.5 * s.mean() + 0.5 * s.max())


# ─────────────────────────────────────────────── 배치 경로 (속도)
# 타일별 파이썬 루프 + polyfit 은 320px 프레임에서 150ms 가 나온다.
# 상수(주파수 격자·가중·회귀 설계행렬)를 캐시하고 FFT·회귀를 타일 축으로
# 일괄 처리하면 동일 결과를 한 자릿수 빠르게 얻는다.
_CACHE: dict = {}


def _grids(n: int, px_per_deg: float):
    key = (n, px_per_deg)
    if key not in _CACHE:
        fy = np.fft.fftshift(np.fft.fftfreq(n, d=1.0 / px_per_deg))
        f = np.hypot(fy[:, None], fy[None, :])
        mask = f > 0.5
        logf = np.log(f[mask])
        lf_mean = logf.mean()
        lf_var = float(((logf - lf_mean) ** 2).sum())
        win2 = np.hanning(n)[:, None] * np.hanning(n)[None, :]
        _CACHE[key] = (mask, logf, lf_mean, lf_var, band_weight(f[mask]), win2)
    return _CACHE[key]


def _tile_scores_batch(tiles: np.ndarray, px_per_deg: float) -> np.ndarray:
    """(T,64,64) 타일 묶음 → (T,) 점수. _tile_score 와 같은 계산의 일괄판."""
    n = tiles.shape[-1]
    mask, logf, lf_mean, lf_var, wgt, win2 = _grids(n, px_per_deg)

    zm = tiles - tiles.mean(axis=(1, 2), keepdims=True)
    rms = zm.std(axis=(1, 2))                              # (T,)
    amp = np.abs(np.fft.fftshift(np.fft.fft2(zm * win2), axes=(1, 2)))
    a = amp[:, mask]                                       # (T,M)
    loga = np.log(a + _EPS)

    # 타일별 최적적합 1/f^α — 닫힌형 단순회귀 (polyfit 일괄판)
    la_mean = loga.mean(axis=1, keepdims=True)
    alpha = ((logf - lf_mean) * (loga - la_mean)).sum(axis=1) / lf_var  # (T,)
    fit = la_mean + alpha[:, None] * (logf - lf_mean)[None, :]

    excess = np.maximum(a - np.exp(fit), 0.0)
    s = (excess * wgt).sum(axis=1) / (a.sum(axis=1) + _EPS)
    s = s * np.minimum(1.0, rms / 0.25)
    return np.where(rms < 1e-3, 0.0, s)


def _resize64(a: np.ndarray) -> np.ndarray:
    """간단한 평균 풀링/보간으로 64×64 로. (cv2 없이도 동작)"""
    try:
        import cv2
        return cv2.resize(a, (64, 64), interpolation=cv2.INTER_AREA)
    except Exception:
        ys = (np.linspace(0, a.shape[0] - 1, 64)).astype(int)
        xs = (np.linspace(0, a.shape[1] - 1, 64)).astype(int)
        return a[ys][:, xs]


# ─────────────────────────────────────────────── 영상 요약
def analyze(path: str, px_per_deg: float = PX_PER_DEG,
            sample_fps: float = 3.0) -> dict:
    """영상 → 프레임 표본의 이탈 점수 시계열과 요약.

    공간 지표라 매 프레임이 필요 없다 — 기본 초당 3장 표본이면 충분하고,
    검출기 메인 루프에 편입할 때는 같은 축소 프레임을 그대로 먹이면 된다.
    """
    import cv2
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise IOError(f"영상을 열 수 없습니다: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    hop = max(1, int(round(fps / sample_fps)))
    series, idx = [], 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % hop == 0:
            series.append(frame_score(frame, px_per_deg))
        idx += 1
    cap.release()
    s = np.asarray(series) if series else np.zeros(1)
    return {"mean": float(s.mean()), "p95": float(np.percentile(s, 95)),
            "max": float(s.max()), "series": [round(float(v), 4) for v in s],
            "sample_fps": sample_fps, "fps": fps, "px_per_deg": px_per_deg}


# ─────────────────────────────────────────────── 자가 검증
if __name__ == "__main__":
    rng = np.random.default_rng(0)

    def stripes(cpd, n=256, ppd=PX_PER_DEG, contrast=1.0):
        x = np.arange(n) / ppd
        # 정현파 격자 — 사각파는 3n 고조파가 표본화 접힘(aliasing)으로
        # 위험 대역에 되돌아와 테스트가 오염된다 (12cpd 의 36cpd 고조파가
        # 32ppd 표본화에서 4cpd 로 접힘). 실영상 검증에서는 무관.
        img = 0.5 + 0.5 * contrast * np.sin(2 * np.pi * cpd * x)
        return (np.tile(img, (n, 1)) * 255).astype(np.uint8)

    def natural_like(n=256):
        """1/f 진폭의 합성 '자연풍' 노이즈"""
        f = np.fft.fftfreq(n)
        fr = np.hypot(f[:, None], f[None, :]); fr[0, 0] = 1
        spec = (rng.standard_normal((n, n)) + 1j * rng.standard_normal((n, n))) / fr
        img = np.fft.ifft2(spec).real
        img = (img - img.min()) / (np.ptp(img) + _EPS)
        return (img * 255).astype(np.uint8)

    tests = [
        ("균일 회색", np.full((256, 256), 128, np.uint8)),
        ("자연풍 1/f 노이즈", natural_like()),
        ("줄무늬 3cpd (위험 대역)", stripes(3)),
        ("줄무늬 3cpd 저대비 20%", stripes(3, contrast=0.2)),
        ("줄무늬 12cpd (대역 밖)", stripes(12)),
    ]
    print("점수는 상대 비교용 — 기대 순서: 3cpd ≫ 12cpd > 자연풍 ≥ 균일")
    for name, img in tests:
        print(f"  {name:24s} {frame_score(img):.4f}")
