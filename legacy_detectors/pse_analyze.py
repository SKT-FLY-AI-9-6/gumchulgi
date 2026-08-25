# -*- coding: utf-8 -*-
"""
pse_analyze.py  —  설계서 v0.2 §4 C2 모듈 프로토타입
=====================================================
기존 v0.1(bt1702_detector) 의 휘도 기반 판정에
**원추 대립축(DKL) 변조 탐지**를 추가한다.

채널 4종
  LUM : BT.1702-3 Guideline 1 (휘도 플래시)   <- v0.1 이 보던 유일한 채널
  RED : 채도 높은 적색 전환 (BT.1702 명시)     <- v0.1 구현됨
  RG  : L-M  적<->녹 대립축 변조               <- 신규
  BY  : S-(L+M) 청<->황 대립축 변조            <- 신규

RG / BY 는 **등휘도(isoluminant)** 점멸을 잡는다. 휘도가 변하지 않으므로
LUM 채널에는 아무 신호도 잡히지 않는 종류의 위험이다.
"""
from __future__ import annotations
import json, sys
import numpy as np
import cv2

# ---------------------------------------------------------------- BT.1702-3 상수 (v0.1과 동일)
SDR_PEAK = 200.0
DARK_LUM_THR = 160.0
LUM_DIFF_THR = 20.0
MICHELSON_THR = 1.0 / 17.0
AREA_THR = 0.25
MAX_FLASH_PER_SEC = 3
EOTF_GAMMA = 2.4
RED_RATIO = 0.8
RED_MIN_V = 0.25

# ---------------------------------------------------------------- 대립축 상수 (신규 / 조정 대상)
ADAPT_TAU = 0.25          # s, 순응 배경 시상수
RG_THR = 0.10             # 원추 대비 차 (L/Lb - M/Mb) 프레임간 변화 임계
BY_THR = 0.20             # S 축은 민감도가 낮아 임계를 높게
DARK_GATE_Y = 0.004       # 선형 Y 하한 — 이보다 어두운 픽셀은 색 판정에서 제외

# ---------------------------------------------------------------- v0.4 : 문헌 근거 강화 (빡빡 모드)
STRICT = True             # 빡빡 모드 (문헌 근거 강화 판정)
LOCAL_AREA_WIN = 0.5      # 국소 면적 창(프레임 폭 대비)
CUMUL_SECONDS = 5.0       # 이 시간 이상 위험대역 지속 시 누적 위반
CUMUL_FLASH_MIN = 3       # 누적에 계상할 최소 플래시/s (한도 경계)
AFTERIMAGE_TAU = 0.10     # s, 잔상 시간 가산 창 (렌더 평활에 사용)


def _area_feed(mask: np.ndarray, k: int) -> float:
    """마스크의 위험 면적. 빡빡 모드에서는 전체 평균 대신 국소 창 최대 채움률을
    쓴다 — 화면 일부만 강하게 점멸해도(Harding 10° 시야 기준) 잡히도록."""
    g = float(mask.mean())
    if not STRICT or k <= 1 or not mask.any():
        return g
    loc = cv2.boxFilter(mask.astype(np.float32), -1, (k, k))
    return max(g, float(loc.max()))

# ---------------------------------------------------------------- 색공간 행렬
M_RGB2XYZ = np.array([[0.4124, 0.3576, 0.1805],
                      [0.2126, 0.7152, 0.0722],
                      [0.0193, 0.1192, 0.9505]], np.float32)
M_XYZ2LMS = np.array([[ 0.15514,  0.54312, -0.03286],
                      [-0.15514,  0.45684,  0.03286],
                      [ 0.0,      0.0,      0.01608]], np.float32)
M_RGB2LMS = (M_XYZ2LMS @ M_RGB2XYZ).astype(np.float32)


def decode_linear(frame_bgr: np.ndarray) -> np.ndarray:
    """8bit BGR -> 선형광 RGB [0,1] (BT.1886 EOTF, 감마 2.4)"""
    rgb = frame_bgr[..., ::-1].astype(np.float32) / 255.0
    return np.power(rgb, EOTF_GAMMA, dtype=np.float32)


def to_lms(lin_rgb: np.ndarray) -> np.ndarray:
    return lin_rgb @ M_RGB2LMS.T


# ---------------------------------------------------------------- 플래시 카운터 (채널 공용)
class FlashChannel:
    def __init__(self, name: str, fps: float, area_thr: float = AREA_THR):
        self.name = name
        self.fps = fps
        self.win = max(1, int(round(fps)))
        self.area_thr = area_thr
        self.pending: tuple[int, int] | None = None
        self.edges: list[int] = []
        self.series: list[dict] = []

    def push(self, idx: int, area_up: float, area_dn: float):
        area = max(area_up, area_dn)
        tr = 0
        if area_up > self.area_thr:
            tr = +1
        elif area_dn > self.area_thr:
            tr = -1
        if tr != 0:
            if self.pending is not None and self.pending[1] == -tr:
                self.edges.append(self.pending[0])
                self.pending = None
            else:
                self.pending = (idx, tr)
        cnt = sum(1 for e in self.edges if idx - self.win < e <= idx)
        self.series.append({"i": idx, "area": round(float(area), 4),
                            "tr": tr, "flashes": cnt, "viol": cnt > MAX_FLASH_PER_SEC})
        return cnt > MAX_FLASH_PER_SEC

    def summary(self) -> dict:
        v = np.array([s["viol"] for s in self.series], bool)
        f = np.array([s["flashes"] for s in self.series], int)
        a = np.array([s["area"] for s in self.series], float)
        return {"channel": self.name,
                "max_flashes_per_sec": int(f.max()) if f.size else 0,
                "max_area_pct": round(float(a.max()) * 100, 1) if a.size else 0.0,
                "violation_frames": int(v.sum()),
                "violation_seconds": round(float(v.sum()) / self.fps, 2),
                "violation_ratio": round(float(v.mean()) if v.size else 0.0, 4),
                "pass": bool(v.sum() == 0)}

    def segments(self) -> list:
        v = [s["viol"] for s in self.series]
        segs, st = [], None
        for i, f in enumerate(v):
            if f and st is None:
                st = i
            elif not f and st is not None:
                segs.append((round(st / self.fps, 2), round(i / self.fps, 2)))
                st = None
        if st is not None:
            segs.append((round(st / self.fps, 2), round(len(v) / self.fps, 2)))
        return segs


# ---------------------------------------------------------------- 메인 분석
def analyze(path: str, width: int = 320, verbose: bool = True) -> dict:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise IOError(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    if not fps or fps != fps or fps <= 0 or fps > 240:
        fps = 30.0
    alpha = 1.0 - float(np.exp(-1.0 / (fps * ADAPT_TAU)))   # 순응 배경 갱신 계수

    ch = {k: FlashChannel(k, fps) for k in ("LUM", "RED", "RG", "BY")}
    prev = None
    bg = None            # 순응 배경 LMS
    idx = 0
    kwin = max(1, int(round(width * LOCAL_AREA_WIN)))   # 국소 면적 창(px)
    trace = {"lum_mean": [], "rg": [], "by": [], "t": []}

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        h0, w0 = frame.shape[:2]
        small = cv2.resize(frame, (width, max(2, int(h0 * width / w0))),
                           interpolation=cv2.INTER_AREA)
        lin = decode_linear(small)
        lms = to_lms(lin)
        Y = lin @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        lum_cd = Y * SDR_PEAK

        bg = lms.copy() if bg is None else (alpha * lms + (1 - alpha) * bg)
        bgf = np.maximum(bg, 1e-4)
        cc = lms / bgf - 1.0                       # 원추 대비 (l, m, s)
        rg = cc[..., 0] - cc[..., 1]               # L-M
        by = cc[..., 2] - 0.5 * (cc[..., 0] + cc[..., 1])   # S-(L+M)
        lit = Y > DARK_GATE_Y                      # 너무 어두운 픽셀 제외

        f8 = small.astype(np.float32) / 255.0
        tot = f8.sum(2) + 1e-6
        red = (f8[..., 2] / tot >= RED_RATIO) & (f8[..., 2] >= RED_MIN_V)

        if prev is not None:
            ld = np.minimum(prev["lum"], lum_cd)
            lb = np.maximum(prev["lum"], lum_cd)
            d = lb - ld
            mich = np.where(lb + ld > 0, d / np.maximum(lb + ld, 1e-6), 0.0)
            harmful = ((ld < DARK_LUM_THR) & (d >= LUM_DIFF_THR)) | \
                      ((ld >= DARK_LUM_THR) & (mich > MICHELSON_THR))
            sg = np.sign(lum_cd - prev["lum"])
            ch["LUM"].push(idx, _area_feed(harmful & (sg > 0), kwin),
                                _area_feed(harmful & (sg < 0), kwin))

            ch["RED"].push(idx, _area_feed(red & ~prev["red"], kwin),
                                _area_feed(prev["red"] & ~red, kwin))

            for key, cur, pv, thr in (("RG", rg, prev["rg"], RG_THR),
                                      ("BY", by, prev["by"], BY_THR)):
                dd = (cur - pv) * lit
                ch[key].push(idx, _area_feed(dd > thr, kwin),
                                  _area_feed(dd < -thr, kwin))

        trace["t"].append(round(idx / fps, 3))
        trace["lum_mean"].append(round(float(lum_cd.mean()), 2))
        trace["rg"].append(round(float(np.abs(rg[lit]).mean()) if lit.any() else 0.0, 4))
        trace["by"].append(round(float(np.abs(by[lit]).mean()) if lit.any() else 0.0, 4))

        prev = {"lum": lum_cd, "red": red, "rg": rg, "by": by}
        idx += 1
        if verbose and idx % 300 == 0:
            print(f"    ... {idx} frames")

    cap.release()

    cumul = {}
    win = max(1, int(round(CUMUL_SECONDS * fps)))
    for k, c in ch.items():
        f = np.array([s["flashes"] for s in c.series], int)
        near = f >= CUMUL_FLASH_MIN
        run = 0; frames_over = 0; longest = 0
        for x in near:
            run = run + 1 if x else 0
            longest = max(longest, run)
            if run >= win:
                frames_over += 1
        cumul[k] = {"sustained": bool(longest >= win),
                    "longest_run_s": round(longest / fps, 2),
                    "cumulative_seconds": round(frames_over / fps, 2)}

    out = {"video": path, "fps": round(fps, 3), "frames": idx,
           "duration_s": round(idx / fps, 2),
           "strict": STRICT,
           "channels": {k: c.summary() for k, c in ch.items()},
           "cumulative": cumul,
           "segments": {k: c.segments() for k, c in ch.items()},
           "_trace": trace,
           "_series": {k: c.series for k, c in ch.items()}}
    for k in ch:
        out["channels"][k]["sustained_over_5s"] = cumul[k]["sustained"]
        out["channels"][k]["pass"] = out["channels"][k]["pass"] and not (STRICT and cumul[k]["sustained"])
    out["verdict"] = {
        "v0.1_luminance_only_pass": out["channels"]["LUM"]["pass"] and out["channels"]["RED"]["pass"],
        "v0.2_with_opponent_pass": all(c["pass"] for c in out["channels"].values()),
    }
    return out


def brief(r: dict) -> str:
    L = [f"{r['video']}  ({r['duration_s']}s @ {r['fps']}fps, {r['frames']}f)"]
    L.append(f"  {'채널':<5} {'판정':<6} {'최대플래시/s':>12} {'최대면적%':>10} {'위반초':>8}")
    for k in ("LUM", "RED", "RG", "BY"):
        c = r["channels"][k]
        L.append(f"  {k:<5} {'PASS' if c['pass'] else 'FAIL':<6} "
                 f"{c['max_flashes_per_sec']:>12} {c['max_area_pct']:>10.1f} "
                 f"{c['violation_seconds']:>8.2f}")
    v = r["verdict"]
    L.append(f"  -> v0.1(휘도만): {'통과' if v['v0.1_luminance_only_pass'] else '위반검출'}"
             f"   |   v0.2(대립축 포함): {'통과' if v['v0.2_with_opponent_pass'] else '위반검출'}")
    return "\n".join(L)


if __name__ == "__main__":
    for p in sys.argv[1:]:
        r = analyze(p, verbose=False)
        print(brief(r))
        print()
