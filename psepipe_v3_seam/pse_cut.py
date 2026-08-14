# -*- coding: utf-8 -*-
"""
pse_cut.py — 빠른 화면 전환(컷) 검출   [BT.1702 '화면 전환' 조항]
==================================================================
근거
  ITU-R BT.1702 / 「광과민성 발작 예방 종합 가이드북 2026」 §5.4 인용:
    "화면 전환: 빨리 바뀌는 화면(빠른 컷 등)도 **플래시 기준과 동일하게 간주**"
    "플래시 제한: 1초 동안 3회 초과, 화면의 1/4 이상"
    "지속 시간 및 누적 효과: 5초 이상 지속되는 경우를 피하도록 권고"

왜 별도 채널이 필요한가
  휘도(LUM) 채널은 **밝기가 변해야** 잡는다. 그런데 숏폼의 비트 맞춤 편집은
  노출을 일정하게 맞춰 놓고 장면만 빠르게 바꾸는 경우가 많다. 이때 화면 내용은
  초당 몇 번씩 통째로 뒤집히는데 평균 휘도는 거의 안 변해서 LUM 이 통과시킨다.
  규격은 이걸 플래시와 동일하게 보라고 명시하는데, 지금까지 검출기에 없었다.

이 검출기가 반드시 피해야 하는 실패
  **빠른 모션을 컷으로 세는 것.** 숏폼에는 휙 돌리는 촬영(whip pan), 급격한 줌,
  손떨림이 흔하다. 프레임 차분만 보면 이것들이 컷보다 더 큰 변화를 만든다.
  오탐이 나면 위반율이 부풀어 숫자 자체가 못 쓰게 된다. 그래서 네 겹으로 막는다.

    (1) 블록별 색 히스토그램  — 모션은 화면을 '이동'시키지만 색 분포는 보존한다.
                                컷은 색 분포 자체를 바꾼다.
    (2) 적응 임계             — 최근 프레임 거리의 중앙값 대비 이상치인지 본다.
                                계속 흔들리는 영상에서는 기준선이 같이 올라간다.
    (3) 일시적 변화 배제       — 4프레임 창에서 앞뒤 **양방향**을 본다. 섬광의
                                진입과 복귀가 각각 컷으로 세지는 것을 막는다.
    (4) 왕복 배제             — 최근 1초 안의 샷으로 되돌아오면 컷이 아니라
                                두 화면의 왕복(=플래시/패턴 위험)으로 본다.

  검증: 합성 클립 21편(컷 전용 10편 + 점멸·색·줄무늬 11편)에서 오탐·미탐 0.
  휙 돌리는 촬영·급격한 줌·손떨림 전부 컷 0회로 통과하고, 휘도를 맞춘 초당 6컷은
  잡는다 — 후자가 LUM 채널이 구조적으로 못 보는 바로 그 경우다.

  속도: 약 10.6 ms/frame (320px 분석, 단일코어). 40초 숏폼 1편에 약 12초.

  알려진 한계: 서로 다른 두 화면만 초당 여러 번 왕복하는 경우는 (4)에 의해
  컷으로 세지 않는다. 그건 플래시/색 채널이 담당해야 하는데, 휘도와 색이
  모두 맞춰진 두 장면의 왕복이라면 어느 채널도 못 잡는다. 실사에서는 거의
  없는 경우지만 기록해 둔다.

판정
  · 컷 후보: 변화한 블록 비율 > 80%(장면전환 면적 조건) + 적응 임계 초과 + 일시변화 아님
  · 1초 슬라이딩 창에서 컷 3회 초과 -> 위반
  · 위험대역(3회/s 이상)이 5초 이상 지속 -> 누적 위반

해석상 미확정 (원문 확인 필요)
  규격은 "플래시 기준과 동일하게 간주"라고만 한다. 그런데 플래시 1회는 **반대
  방향 변화 한 쌍**이고 컷 1회는 **단일 변화**다. 둘을 어떻게 맞출지 원문에
  명시가 없다.
    · 기본값(literal)  : 컷 1회 = 플래시 1회. 초당 컷 3회 초과면 위반.
    · 대안(paired)     : 컷 2회 = 플래시 1회. 초당 컷 6회 초과면 위반.
  기본값이 약 2배 엄격하다. `--paired` 로 바꿀 수 있고, 결과에는 **두 숫자를 모두**
  넣어 두었으니 BT.1702-3 원문을 확보하면 그때 확정하면 된다.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import deque

import cv2
import numpy as np

# ---------------------------------------------------------------- 상수
GRID = 5                    # 프레임을 GRID x GRID 블록으로 나눈다 (80% 임계에 맞춰 세분화)
H_BINS, S_BINS = 16, 8      # 블록별 HSV 히스토그램 해상도
BLOCK_DIST_THR = 0.45       # 블록이 "바뀌었다"고 볼 Bhattacharyya 거리
AREA_THR = 0.80             # **장면 전환의 면적 조건은 80%다** (25% 아님).
                            # 근거: Jordan, "Evaluating Conformance of Video Safety
                            # Tools for PSE", HCII 2025 — "NAB-J 지침에는 '장면 전환'
                            # 특별 조항이 있어 1초에 3회까지만 허용되며, 장면 전환은
                            # 화면의 **80%** 로 조작적 정의된다"(Cambridge Research
                            # Systems 의 HardingFPA 해석 기준).
                            # 이전 값 0.25 는 플래시 면적 기준을 잘못 가져온 것이었다.
ALT_AREA_THR = 0.25         # 왕복 판별용 (같은 샷으로 되돌아왔는지)
ADAPT_WIN = 45              # 적응 기준선을 잡을 최근 프레임 수 (~1.5초 @30fps)
ADAPT_K = 2.5               # 최근 중앙값의 몇 배를 넘어야 이상치로 볼지
BASE_EXCL = 0.60            # 기준선 추정에서 제외할 변화율 하한 — 컷(>0.80)과
                            # 게인 보정이 만드는 경계 번짐 잔상(0.6~0.8)은 평상시
                            # 모션이 아니다. 이보다 큰 값이 기준선에 섞이면
                            # 연속 컷 구간에서 임계가 컷 높이까지 올라간다.
ABS_MIN_DIST = 0.30         # 적응 임계가 낮아져도 이 아래는 컷으로 안 본다
MIN_CUT_GAP = 2             # 컷 사이 최소 프레임 간격 (같은 경계 중복 계상 방지)
TRANSIENT_RATIO = 0.60      # 앞뒤가 이만큼 비슷하면 컷이 아니라 일시적 변화(플래시)

MAX_CUTS_PER_SEC = 3        # 규격 — 초당 3회 초과 시 위반
CUMUL_SECONDS = 5.0         # 규격 — 위험대역 5초 이상 지속 시 누적 위반


def block_hists(frame_bgr: np.ndarray) -> np.ndarray:
    """GRID x GRID 블록별 HSV(H,S) 히스토그램. 반환 (GRID*GRID, H_BINS*S_BINS)."""
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    h, w = hsv.shape[:2]
    ys = np.linspace(0, h, GRID + 1).astype(int)
    xs = np.linspace(0, w, GRID + 1).astype(int)
    out = np.empty((GRID * GRID, H_BINS * S_BINS), np.float32)
    k = 0
    for i in range(GRID):
        for j in range(GRID):
            blk = hsv[ys[i]:ys[i + 1], xs[j]:xs[j + 1]]
            hist = cv2.calcHist([blk], [0, 1], None, [H_BINS, S_BINS],
                                [0, 180, 0, 256])
            cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
            out[k] = hist.flatten()
            k += 1
    return out


def block_distances(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """블록별 Bhattacharyya 거리 (0=동일, 1=완전히 다름)."""
    d = np.empty(a.shape[0], np.float32)
    for i in range(a.shape[0]):
        d[i] = cv2.compareHist(a[i], b[i], cv2.HISTCMP_BHATTACHARYYA)
    return d


class Stream:
    """프레임(분석 폭으로 축소된 BGR uint8)을 **한 장씩** 받아 컷을 누적한다.

    pse_pattern.Stream 과 같은 이유로 존재한다 — pse_bt1702 의 메인 루프가
    자기 디코드·축소 프레임을 그대로 먹일 수 있어야 프레임 이터러블 입력에서도
    컷 판정이 가능하고(이전에는 VideoCapture(path) 만 받아 이터러블이면
    예외가 pass=None 으로 삼켜졌다), 컷용 별도 디코드도 없어진다.
    """

    def __init__(self, fps: float, paired: bool = False):
        self.fps = fps
        self.paired = paired
        self.limit = MAX_CUTS_PER_SEC * (2 if paired else 1)
        self.win = max(1, int(round(fps)))
        self.hists = deque(maxlen=4)       # 최근 4프레임 히스토그램 (앞뒤 일시변화 판별용)
        self.recent = deque(maxlen=ADAPT_WIN)   # 최근 변화율 (적응 기준선)
        self.series = []                   # 프레임별 기록
        self.cut_frames = []               # 컷으로 확정된 프레임 인덱스
        self.last_cut = -10**9
        self.recent_shots = deque(maxlen=24)    # 최근 샷 시작 히스토그램 (왕복 판별용)
        self.idx = 0

    def push(self, small_bgr: np.ndarray) -> None:
        idx = self.idx
        self.hists.append(block_hists(small_bgr))
        hists = self.hists

        changed = 0.0
        is_cut = False
        reason = ""

        # 버퍼 [Z, A, B, C] = 프레임 N-3, N-2, N-1, N.
        # **A→B 경계에서 B 가 새 샷의 첫 프레임인가**를 판정한다.
        # 경계에서 즉시 판정하지 않고 한 프레임 늦게 보는 이유는, 일시적 변화(섬광)를
        # 가리려면 "다음 프레임에서 원래대로 돌아오는가"를 봐야 하기 때문이다.
        # 그리고 앞뒤 **양방향**을 봐야 한다 — 실측에서 섬광의 진입은 걸러졌는데
        # 복귀(흰 화면 → 원래 장면)가 컷으로 세지는 것을 확인했다.
        if len(hists) >= 4:
            Z, A, B, C = hists[0], hists[1], hists[2], hists[3]
            changed = float((block_distances(A, B) > BLOCK_DIST_THR).mean())
            self.recent.append(changed)

            # (2) 적응 임계 — 최근 중앙값 대비 이상치인가.
            # 기준선은 **평상시 모션**을 대표해야 하므로 컷급 변화와 그 번짐
            # 잔상(BASE_EXCL 초과)은 빼고 추정한다. 게인 보정(작동기 A)의 시간
            # 저역통과가 컷 경계를 2프레임으로 번지게 하면(부분 변화 0.6~0.8)
            # 그 잔상이 중앙값을 컷 높이까지 끌어올려 진짜 컷이 통째로
            # 탈락했다 — 27_anime 실측 15→9. 잔상을 빼면 기준선은 다시 저변
            # 모션만 반영하고, 계속 흔들리는 영상(0.6 이하 변화 연속)의 오탐
            # 방어는 그대로 남는다.
            lows = [v for v in self.recent if v <= BASE_EXCL]
            base = float(np.median(lows)) if len(lows) >= 8 else 0.0
            adaptive = max(ABS_MIN_DIST, ADAPT_K * base)

            cand = (changed > AREA_THR) and (changed >= adaptive)
            cut_idx = idx - 1                      # 새 샷의 첫 프레임

            if cand:
                # (3a) 전방 — A 와 C 가 비슷하면 B 는 스쳐간 한 장이다 (섬광 진입)
                fwd = float((block_distances(A, C) > BLOCK_DIST_THR).mean())
                if fwd < changed * TRANSIENT_RATIO:
                    cand = False
                    reason = "transient-진입(섬광)"
                else:
                    # (3b) 후방 — Z 와 B 가 비슷하면 B 는 A 이전 내용으로의 복귀다.
                    #      즉 A 가 스쳐간 한 장이었다는 뜻 (섬광 복귀)
                    bwd = float((block_distances(Z, B) > BLOCK_DIST_THR).mean())
                    if bwd < changed * TRANSIENT_RATIO:
                        cand = False
                        reason = "transient-복귀(섬광)"

            # (4) 왕복 배제 — 빠른 '컷'이란 서로 다른 샷들의 연속이지 두 화면의
            #     왕복이 아니다. 새 샷 B 가 최근 1초 안의 샷 시작들과 닮아 있으면
            #     장면이 순환하고 있다는 뜻이고, 그건 플래시/패턴 쪽 위험이다.
            #     (적↔흑 5Hz 점멸이 컷 5회/s 로 세지던 것을 실측으로 확인)
            if cand:
                for si, sh in self.recent_shots:
                    if idx - si > self.win:
                        continue
                    same = float((block_distances(sh, B) > BLOCK_DIST_THR).mean())
                    if same < ALT_AREA_THR:      # 최근 본 샷으로 되돌아옴
                        cand = False
                        reason = "alternation(왕복)"
                        break

            # 같은 경계 중복 계상 방지
            if cand and (cut_idx - self.last_cut) < MIN_CUT_GAP:
                cand = False
                reason = "gap"

            if cand:
                is_cut = True
                self.last_cut = cut_idx
                self.cut_frames.append(cut_idx)
                self.recent_shots.append((cut_idx, B))
        elif len(hists) >= 2:
            self.recent.append(float((block_distances(hists[-2], hists[-1]) > BLOCK_DIST_THR).mean()))

        cnt = sum(1 for c in self.cut_frames if idx - self.win < c <= idx)
        self.series.append({"i": idx, "changed": round(changed, 4),
                           "cut": bool(is_cut), "cuts_in_window": cnt,
                           "viol": cnt > self.limit, "why": reason})
        self.idx = idx + 1

    def finish(self, video: str = "<frames>") -> dict:
        return _finish(self.series, self.cut_frames, self.fps, self.paired,
                       self.limit, self.idx, video)


def analyze(path, width: int = 320, paired: bool = False,
            verbose: bool = False, fps: float = None) -> dict:
    """path 대신 프레임 이터러블(BGR uint8)도 받는다. 그 경우 fps 필수."""
    import os as _os
    if isinstance(path, (str, _os.PathLike)):
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            raise IOError(f"영상을 열 수 없습니다: {path}")
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not fps or fps != fps or fps <= 0 or fps > 240:
            fps = 30.0
        frames_in = None
    else:
        if fps is None:
            raise ValueError("프레임을 직접 넘길 때는 fps 가 필요합니다")
        cap, frames_in = None, iter(path)

    st = Stream(fps, paired=paired)
    while True:
        if cap is not None:
            ok, frame = cap.read()
            if not ok:
                break
        else:
            frame = next(frames_in, None)
            if frame is None:
                break
        h0, w0 = frame.shape[:2]
        if not w0 or not h0:
            break
        small = (cv2.resize(frame, (width, max(2, int(round(h0 * width / w0)))),
                            interpolation=cv2.INTER_AREA) if w0 != width else frame)
        st.push(small)
        if verbose and st.idx % 300 == 0:
            print(f"    ... {st.idx} frames", file=sys.stderr)
    if cap is not None:
        cap.release()
    if st.idx == 0:
        raise IOError(f"프레임을 읽지 못했습니다: {path}")
    return st.finish(video=str(path) if cap is not None else "<frames>")


def _finish(series, cut_frames, fps, paired, limit, idx, video):
    viol = np.array([s["viol"] for s in series], bool)
    counts = np.array([s["cuts_in_window"] for s in series], int)

    # 5초 누적 — 위험대역(한도 이상)이 끊기지 않고 지속되는가
    need = max(1, int(round(CUMUL_SECONDS * fps)))
    run = longest = 0
    for c in counts:
        run = run + 1 if c >= limit else 0
        longest = max(longest, run)
    sustained = bool(longest >= need)

    segs, st = [], None
    for i, v in enumerate(viol):
        if v and st is None:
            st = i
        elif not v and st is not None:
            segs.append([round(st / fps, 2), round(i / fps, 2)]); st = None
    if st is not None:
        segs.append([round(st / fps, 2), round(len(viol) / fps, 2)])

    dur = idx / fps
    n_cuts = len(cut_frames)
    return {
        "video": video,
        "standard": "ITU-R BT.1702 '화면 전환' — 빠른 컷을 플래시와 동일하게 간주",
        "interpretation": "paired (컷 2회=플래시 1회)" if paired else "literal (컷 1회=플래시 1회)",
        "limit_cuts_per_sec": limit,
        "fps": round(fps, 3), "frames": idx, "duration_s": round(dur, 2),
        "total_cuts": n_cuts,
        "cuts_per_sec_mean": round(n_cuts / max(dur, 1e-6), 2),
        "max_cuts_per_sec": int(counts.max()) if counts.size else 0,
        "violation_frames": int(viol.sum()),
        "violation_seconds": round(float(viol.sum()) / fps, 2),
        "sustained_over_5s": sustained,
        "longest_run_s": round(longest / fps, 2),
        "segments": segs,
        "cut_times": [round(c / fps, 2) for c in cut_frames],
        # 두 해석의 결과를 모두 남긴다 — 원문 확정 전까지 판단 보류용
        "would_violate_literal": bool((counts > MAX_CUTS_PER_SEC).any()),
        "would_violate_paired": bool((counts > MAX_CUTS_PER_SEC * 2).any()),
        "verdict": {
            "cut_violation": bool(viol.any()),
            "sustained_violation": sustained,
            "dangerous": bool(viol.any() or sustained),
        },
        "_series": series,
    }


def brief(r: dict) -> str:
    v = r["verdict"]
    tag = "FAIL" if v["dangerous"] else "PASS"
    extra = []
    if v["cut_violation"]:
        extra.append(f"위반 {r['violation_seconds']}s")
    if v["sustained_violation"]:
        extra.append(f"5초누적({r['longest_run_s']}s)")
    return (f"  CUT {tag}  총 {r['total_cuts']}컷  평균 {r['cuts_per_sec_mean']}/s  "
            f"최대 {r['max_cuts_per_sec']}/s  한도 {r['limit_cuts_per_sec']}/s"
            + (("  — " + ", ".join(extra)) if extra else ""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("srcs", nargs="+")
    ap.add_argument("--paired", action="store_true",
                    help="컷 2회를 플래시 1회로 간주 (한도 6회/s)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    for p in a.srcs:
        try:
            r = analyze(p, paired=a.paired)
            if a.json:
                print(json.dumps({k: v for k, v in r.items() if not k.startswith("_")},
                                 ensure_ascii=False, indent=1))
            else:
                print(p)
                print(brief(r))
        except Exception as exc:  # noqa: BLE001
            print(f"CUT ERROR {p}: {exc}", file=sys.stderr)
