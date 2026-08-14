# -*- coding: utf-8 -*-
"""
bt1702_detector.py   [v0.1 — 원조. pse_analyze.py 로 대체됨. 이력 보존용]
==================
ITU-R BT.1702-3 (11/2023) 권고 기준에 따라 영상이 광과민성 발작(PSE)을
유발할 수 있는지 탐지하는 모듈.

※ 이 파일은 휘도(LUM)와 채도 적색(RED) 두 축만 본다. 등휘도 색 점멸에는
   구조적으로 눈이 멀어 있다. 현재 팀 표준은 `pse_analyze.py`(6채널)이다.
   또한 이 버전에는 알려진 결함이 두 개 있다 —
     · 전환마다 1회로 세어 플래시를 2배로 과대계수한다
       (BT.1702 의 정의는 "반대 방향 변화 한 쌍 = 1회")
     · RED 채널이 전환 면적을 양수 슬롯에만 넣어 부호가 항상 +1 이므로
       쌍이 완성되지 않는다 → 적색은 구조적으로 FAIL 할 수 없다
   두 결함 모두 pse_analyze.py 에서 수정됐다. 비교·회귀 목적으로만 사용할 것.

구현 기준 (SDR 가정):
  Guideline 1 - 잠재적으로 유해한 플래시(flash)
    * 어두운 쪽 휘도 < 160 cd/m^2 : 밝은/어두운 이미지 휘도차 >= 20 cd/m^2 이면 유해
    * 어두운 쪽 휘도 >= 160 cd/m^2 : Michelson 대비 > 1/17 이면 유해 (HDR용이지만 함께 구현)
    * 채도 높은 빨강(saturated red)으로/으로부터의 전환은 휘도와 무관하게 유해
    * 유해 플래시 영역이 화면의 25% 초과 + 1초 내 플래시 3회 초과(휘도 변화 6회 초과)
      -> 위반(violation)
    * 연속 플래시 leading edge 간격이 334 ms(60Hz 환경) 이상이면 허용
  Annex 1 Attachment 1 - 유해 패턴(간이 구현)
    * 명암 줄무늬 쌍 5개 초과, 정지 패턴은 화면 40% 초과 / 움직이는 패턴은 25% 초과
  Annex 2 / NOTE 3 - 휘도 환산
    * SDR peak white = 200 cd/m^2, BT.1886 EOTF(감마 2.4) 가정

사용 예:
    from bt1702_detector import analyze_video
    result = analyze_video("input.mp4")
    print(result.summary())
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict

import cv2
import numpy as np

# ---------------------------------------------------------------- 상수 (BT.1702-3)
SDR_PEAK_LUMINANCE = 200.0        # cd/m^2, NOTE 3 (SDR)
DARK_LUM_THRESHOLD = 160.0        # cd/m^2, Guideline 1 구간 경계
LUM_DIFF_THRESHOLD = 20.0         # cd/m^2, 160 미만 구간의 유해 휘도차
MICHELSON_THRESHOLD = 1.0 / 17.0  # 160 이상 구간의 유해 대비
AREA_THRESHOLD = 0.25             # 화면 면적 25% 초과
MAX_FLASHES_PER_SEC = 3           # 1초 내 3회 초과 시 위반
SAFE_FLASH_INTERVAL = 0.334       # s, 60Hz 환경에서 허용되는 최소 leading-edge 간격
EOTF_GAMMA = 2.4                  # BT.1886

# 패턴(Attachment 1, 간이)
PATTERN_MIN_PAIRS = 5
PATTERN_AREA_STATIC = 0.40
PATTERN_AREA_MOVING = 0.25

# saturated red 판정 (일반적으로 사용되는 기준: 붉은 성분 비율 >= 0.8)
RED_SATURATION_RATIO = 0.8
RED_MIN_VALUE = 0.25              # 정규화 R값 하한 (너무 어두운 픽셀 배제)


# ---------------------------------------------------------------- 유틸
def frame_to_luminance(frame_bgr: np.ndarray) -> np.ndarray:
    """8-bit BGR 프레임 -> 화면 휘도(cd/m^2). BT.1886 EOTF + BT.709 계수."""
    rgb = frame_bgr[..., ::-1].astype(np.float32) / 255.0
    linear = np.power(rgb, EOTF_GAMMA, dtype=np.float32)
    y = (0.2126 * linear[..., 0]
         + 0.7152 * linear[..., 1]
         + 0.0722 * linear[..., 2])
    return y * SDR_PEAK_LUMINANCE


def harmful_change_mask(l_prev: np.ndarray, l_cur: np.ndarray):
    """
    두 프레임 사이의 픽셀별 '유해한 휘도 변화' 마스크와 부호를 반환.
    반환: (harmful_mask(bool), sign(int8: +1 증가, -1 감소))
    """
    l_dark = np.minimum(l_prev, l_cur)
    l_bright = np.maximum(l_prev, l_cur)
    diff = l_bright - l_dark
    denom = l_bright + l_dark
    michelson = np.where(denom > 0, diff / np.maximum(denom, 1e-6), 0.0)

    below = (l_dark < DARK_LUM_THRESHOLD) & (diff >= LUM_DIFF_THRESHOLD)
    above = (l_dark >= DARK_LUM_THRESHOLD) & (michelson > MICHELSON_THRESHOLD)
    harmful = below | above
    sign = np.sign(l_cur - l_prev).astype(np.int8)
    return harmful, sign


def saturated_red_mask(frame_bgr: np.ndarray) -> np.ndarray:
    """채도 높은 빨강 픽셀 마스크."""
    f = frame_bgr.astype(np.float32) / 255.0
    b, g, r = f[..., 0], f[..., 1], f[..., 2]
    total = r + g + b
    ratio = np.where(total > 1e-6, r / np.maximum(total, 1e-6), 0.0)
    return (ratio >= RED_SATURATION_RATIO) & (r >= RED_MIN_VALUE)


def detect_pattern(gray: np.ndarray) -> tuple[bool, float, float]:
    """
    Attachment 1의 유해 패턴 간이 탐지 (informative 수준).
    1D FFT(행/열 평균 프로파일)로 5쌍(=5 사이클) 초과의 강한 주기 성분을 찾고,
    해당 주파수 성분의 에너지 비중으로 대략적 면적 점유율을 추정한다.
    반환: (패턴 존재 여부, 추정 점유율, 지배 주기 사이클 수)

    ※ 이 근사는 부정확하다. 사각파 줄무늬는 에너지가 고조파로 흩어져 화면을
       100% 채워도 집중도가 0.3 안팎으로 낮게 나온다. 실제 면적 측정은
       pse_pattern.py 의 Gabor 기반 구현을 쓸 것.
    """
    h, w = gray.shape
    best_cycles, best_frac = 0.0, 0.0
    for axis in (0, 1):
        profile = gray.mean(axis=axis).astype(np.float32)
        profile -= profile.mean()
        spec = np.abs(np.fft.rfft(profile * np.hanning(profile.size)))
        if spec.size < 8:
            continue
        spec[0] = 0.0
        k = int(np.argmax(spec))
        cycles = float(k)  # 프로파일 전체 길이 기준 사이클 수
        total = float(spec.sum()) + 1e-6
        frac = float(spec[max(k - 1, 0):k + 2].sum()) / total  # 에너지 집중도 ~ 점유율 근사
        if cycles > PATTERN_MIN_PAIRS and frac > best_frac:
            best_cycles, best_frac = cycles, frac
    is_pattern = best_cycles > PATTERN_MIN_PAIRS and best_frac > PATTERN_AREA_STATIC
    return is_pattern, best_frac, best_cycles


# ---------------------------------------------------------------- 결과 자료구조
@dataclass
class FrameMetrics:
    index: int
    time: float
    mean_luminance: float
    harmful_area: float        # 유해 휘도 변화 픽셀 비율 (0~1)
    red_area_change: float     # saturated red 상태가 바뀐 픽셀 비율
    transition: int            # +1(밝아짐) / -1(어두워짐) / 0
    is_red_transition: bool
    flashes_in_window: int     # 이 프레임 기준 직전 1초 윈도우 내 플래시 수
    flash_violation: bool
    red_violation: bool
    pattern_detected: bool
    pattern_area: float


@dataclass
class AnalysisResult:
    video_path: str
    fps: float
    n_frames: int
    duration: float
    analysis_width: int
    frames: list = field(default_factory=list)          # FrameMetrics 리스트
    violation_segments: list = field(default_factory=list)  # (t_start, t_end, type)

    # ------------------------------ 편의 프로퍼티
    def _arr(self, name):
        return np.array([getattr(f, name) for f in self.frames])

    @property
    def times(self):            return self._arr("time")
    @property
    def harmful_areas(self):    return self._arr("harmful_area")
    @property
    def flash_counts(self):     return self._arr("flashes_in_window")
    @property
    def mean_luminances(self):  return self._arr("mean_luminance")
    @property
    def violations(self):       return self._arr("flash_violation") | self._arr("red_violation")

    def risk_weights(self, pad_seconds: float = 0.5) -> np.ndarray:
        """
        프레임별 위험 가중치(0~1). 위반 구간을 pad_seconds 만큼 앞뒤로 확장하고
        부드럽게 스무딩 -> 필터 모듈에서 적응형 블렌딩에 사용.
        """
        v = self.violations.astype(np.float32)
        pad = max(1, int(round(pad_seconds * self.fps)))
        kernel = np.ones(2 * pad + 1, dtype=np.float32)
        expanded = np.clip(np.convolve(v, kernel, mode="same"), 0, 1)
        smooth_k = np.hanning(2 * pad + 1).astype(np.float32)
        smooth_k /= smooth_k.sum()
        return np.clip(np.convolve(expanded, smooth_k, mode="same"), 0, 1)

    def summary(self) -> dict:
        v = self.violations
        n_viol = int(v.sum())
        return {
            "video": self.video_path,
            "duration_s": round(self.duration, 2),
            "fps": round(self.fps, 3),
            "frames_analyzed": self.n_frames,
            "violation_frames": n_viol,
            "violation_ratio": round(float(n_viol) / max(len(v), 1), 4),
            "violation_seconds": round(n_viol / self.fps, 2),
            "max_flashes_per_second": int(self.flash_counts.max()) if len(self.frames) else 0,
            "max_harmful_area_pct": round(float(self.harmful_areas.max()) * 100, 1) if len(self.frames) else 0,
            "violation_segments": [
                {"start_s": round(s, 2), "end_s": round(e, 2), "type": t}
                for s, e, t in self.violation_segments
            ],
            "compliant_bt1702": n_viol == 0,
        }

    def save_json(self, path: str):
        data = {"summary": self.summary(),
                "frames": [asdict(f) for f in self.frames]}
        with open(path, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- 메인 분석
def analyze_video(video_path: str,
                  analysis_width: int = 320,
                  check_patterns: bool = True,
                  pattern_every_n: int = 15,
                  verbose: bool = True) -> AnalysisResult:
    """
    영상을 BT.1702-3 기준으로 분석한다.

    Parameters
    ----------
    analysis_width : 분석용 다운스케일 폭 (속도용; 면적 비율 판정에는 영향 미미)
    pattern_every_n : 패턴 검사를 n 프레임마다 수행 (비용 절감)
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise IOError(f"영상을 열 수 없습니다: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    win = max(1, int(round(fps)))  # 1초 윈도우 프레임 수

    result = AnalysisResult(video_path=video_path, fps=fps, n_frames=0,
                            duration=0.0, analysis_width=analysis_width)

    prev_lum = None
    prev_red = None
    # 전환(transition) 이력: (frame_index, sign)
    transitions: list[tuple[int, int]] = []
    # 플래시 leading edge 프레임 인덱스 (일반 / red)
    flash_edges: list[int] = []
    red_edges: list[int] = []

    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        h0, w0 = frame.shape[:2]
        scale = analysis_width / float(w0)
        small = cv2.resize(frame, (analysis_width, max(2, int(h0 * scale))),
                           interpolation=cv2.INTER_AREA)

        lum = frame_to_luminance(small)
        red = saturated_red_mask(small)
        t = idx / fps

        harmful_area = 0.0
        red_change_area = 0.0
        transition = 0
        is_red_transition = False

        if prev_lum is not None:
            harmful, sign = harmful_change_mask(prev_lum, lum)
            n_pix = harmful.size
            area_up = float(np.count_nonzero(harmful & (sign > 0))) / n_pix
            area_dn = float(np.count_nonzero(harmful & (sign < 0))) / n_pix
            harmful_area = max(area_up, area_dn)

            # saturated red 로/로부터의 전환 (휘도 무관)
            red_change_area = float(np.count_nonzero(red ^ prev_red)) / n_pix
            is_red_transition = red_change_area > AREA_THRESHOLD

            if area_up > AREA_THRESHOLD:
                transition = +1
            elif area_dn > AREA_THRESHOLD:
                transition = -1

            # 반대 방향 전환 쌍 = 플래시 1회 (leading edge = 앞 전환 시점)
            if transition != 0:
                if transitions and transitions[-1][1] == -transition:
                    edge = transitions[-1][0]
                    # SAFE_FLASH_INTERVAL 이상 떨어진 leading edge는 항상 허용
                    if not flash_edges or (edge - flash_edges[-1]) / fps < SAFE_FLASH_INTERVAL:
                        flash_edges.append(edge)
                    else:
                        flash_edges.append(edge)  # 기록은 하되 윈도우 카운트에서 걸러짐
                transitions.append((idx, transition))

            if is_red_transition:
                if not red_edges or (idx - red_edges[-1]) > 1:
                    red_edges.append(idx)

        # 직전 1초 윈도우 내 플래시 수
        flashes_in_window = sum(1 for e in flash_edges if idx - win < e <= idx)
        red_in_window = sum(1 for e in red_edges if idx - win < e <= idx)

        flash_violation = flashes_in_window > MAX_FLASHES_PER_SEC
        red_violation = red_in_window > MAX_FLASHES_PER_SEC  # red 전환도 동일 빈도 기준 적용

        pattern_detected, pattern_area = False, 0.0
        if check_patterns and idx % pattern_every_n == 0:
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            pattern_detected, pattern_area, _ = detect_pattern(gray)

        result.frames.append(FrameMetrics(
            index=idx, time=round(t, 4),
            mean_luminance=round(float(lum.mean()), 2),
            harmful_area=round(harmful_area, 4),
            red_area_change=round(red_change_area, 4),
            transition=transition,
            is_red_transition=is_red_transition,
            flashes_in_window=flashes_in_window,
            flash_violation=bool(flash_violation),
            red_violation=bool(red_violation),
            pattern_detected=bool(pattern_detected),
            pattern_area=round(pattern_area, 3),
        ))

        prev_lum, prev_red = lum, red
        idx += 1
        if verbose and idx % 300 == 0:
            print(f"  ... {idx} 프레임 분석 중 (t={t:.1f}s)")

    cap.release()
    result.n_frames = idx
    result.duration = idx / fps

    # ---- 위반 구간(segment) 계산
    v = result.violations
    seg_start = None
    for i, flag in enumerate(v):
        if flag and seg_start is None:
            seg_start = i
        elif not flag and seg_start is not None:
            result.violation_segments.append(
                (seg_start / fps, i / fps, "flash"))
            seg_start = None
    if seg_start is not None:
        result.violation_segments.append((seg_start / fps, len(v) / fps, "flash"))

    return result


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "input.mp4"
    res = analyze_video(path)
    print(json.dumps(res.summary(), ensure_ascii=False, indent=2))
