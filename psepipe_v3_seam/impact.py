# -*- coding: utf-8 -*-
"""impact.py — 보정(필터)이 영상에 '무엇을 얼마나 바꿨는가'를 사용자 언어로 잰다.

seam.py 가 부작용(원본에 없던 구조가 생겼나)을 잰다면, 여기는 **효과와
비용**을 잰다. 대시보드에서 "이 영상은 이렇게 보정됐다"를 한눈에 보여주는
게 목적이라 축이 3개뿐이고, 전부 정본 심판(pse_bt1702)의 자를 그대로 빌려
한 문장으로 설명된다:

  · 휘도 — 얼마나 어두워졌나 (보정의 비용)
      lum_mean_drop_pct : 전체 샘플 평균 **선형광** 휘도(cd/m²)의 감소율%.
        휘도는 정본 pse_bt1702.luminance_cd(coherent=False) 그대로다 —
        감마 인코딩 값 평균으로 재면 어두운 쪽이 과대평가돼 규격 판정과
        다른 자로 재는 셈이 된다(정본이 조각별 sRGB EOTF 를 쓰는 이유와
        같다). 부호를 유지한다 — 보정이 밝게 만들었으면 음수가 나온다.
      lum_peak_drop_pct : **플래시 위반 구간 안** 샘플의 프레임별 p99 휘도
        평균의 감소율%. 전체 평균은 위반 구간 밖 프레임(대부분)에 희석돼
        "번쩍임이 얼마나 눌렸나"가 안 보인다 — seam.py 헤일로가 평균 대신
        p99 를 쓰는 것과 같은 논리로, 구간 안 상위 1% 화소(플래시의 피크)
        를 본다. 구간은 report_before 의 rules.flash.segments(초 단위
        [시작,끝] 목록)를 쓰고, 구간 정보가 없거나 샘플이 안 걸리면 전체
        샘플로 대체한다.

  · 플래시 — 위반이 얼마나 사라졌나 (보정의 효과)
      flash_before/after : rules.flash 의 total_events.
      flash_viol_s_before/after : violation_seconds.
      정본 심판의 값을 **그대로 옮긴다** — 판정 파이프라인이 이미 만든
      report(report_before/report_after)가 있으면 재계산 없이 쓰고, 없으면
      pse_bt1702.analyze(with_pattern=False, with_cut=False) 로 직접 구한다.
      여기서 다른 정의로 다시 세면 대시보드 숫자와 판정 숫자가 어긋난다.

  · 색 — 색감이 얼마나 보존됐나 (보정의 품질)
      color_mean_duv / color_p95_duv : 화소별 CIE 1976 UCS 색차
        ||u'v'_out − u'v'_src|| 의 평균 / 95백분위 (전 샘플 합산).
        u'v' 는 정본 pse_bt1702.uv_prime — 적색 규격 임계가 Δu'v' 0.20
        이므로 "0.01 대면 지각적으로 작다"는 눈금(seam.py 색충실도 축과
        동일)까지 같이 가져온다.
      color_keep_pct : 채도 보존율% = 100·(1 − 평균 채도손실률).
        채도 = D65 백색점 (0.19783, 0.46832) 까지의 u'v' 거리.
        손실률 = mean( max(sat_src − sat_out, 0) / sat_src ),
        sat_src >= 0.05 인 lit 화소 한정(무채색은 분모가 0 근처라 제외,
        해당 화소가 없으면 손실률 0). max(·,0) 클램프라 채도를 올린 것은
        손실로 치지 않는다 — "창작자의 색을 지웠는가"만 묻는 축이다.

      **이 축이 게인 사다리의 얼굴이다.** 게인 사다리는 선형광 등배 곱이라
      색도(u'v')가 이론상 보존된다 — X·Y·Z 가 같은 배율로 줄면 비율인
      u'v' 는 불변이다. 이 지표가 그 보존을 실측으로 증명하고, 전역 톤을
      만지는 보정(BlazeBVD STE 등 톤매핑 계열)과의 차이를 드러낸다 —
      톤매핑은 채널별 비선형 압축이라 채도가 함께 눌린다.

측정 규약
  · 두 영상을 **같은 프레임 인덱스**로 짝지어 stride 샘플링한다
    (총 ~max_samples 쌍, 기본 120). 게인 보정은 프레임을 더하거나 빼지
    않으므로 인덱스 짝이 곧 시간 짝이다. 프레임 크기가 다르면 out 을 src
    크기로 리사이즈한다(INTER_AREA — 정본 축소와 같은 보간).
  · 색은 폭 96px(pse_bt1702.COLOR_W, 정본 색 채널과 같은 폭) 축소본에서
    잰다 — 평균/백분위 지표라 축소로 충분하고 CIE 변환이 비용의 절반이다.
  · lit = 8bit 최대채널 >= 40 (pse_bt1702.RB_MIN_V, rb_sides 와 같은
    게이트). **양쪽 프레임 모두** lit 이어야 표본에 넣는다 — u'v' 는
    분모(X+15Y+3Z)가 0 근처면 값 자체가 무의미하고, 8bit 양자화 잡음이
    어두운 화소의 Δu'v' 를 부풀린다. 게인 사다리는 위반 구간에서 휘도를
    크게 깎으므로 src 쪽만 게이트하면 out 이 어두워진 화소의 잡음이
    게인 계열에만 불리하게 섞인다.

공용 계약 — impact JSON (videos.impact_json 에 저장, API 로 그대로 노출)
  {"v": 1,
   "lum_mean_drop_pct": float,  "lum_peak_drop_pct": float,
   "flash_before": int,         "flash_after": int,
   "flash_viol_s_before": float,"flash_viol_s_after": float,
   "color_mean_duv": float,     "color_p95_duv": float,
   "color_keep_pct": float}
  API: GET /dashboard/recent_impact?limit=10 (auth 필수) →
  {"items": [{"video_id": int, "title": str, "thumb_url": str|null,
              "watched_at": str, "filter_level": str|null,
              "impact": {...위 JSON...}}]}
  — 이 사용자의 watch_events 중 videos.filtered_path 가 있고 impact_json 이
    있는 영상, 영상별 최신 시청 1행, 최신순 limit 개.

주의
  · 샘플링 지표다 — stride 가 위반 구간을 성기게 지나가면 peak 축 표본이
    몇 프레임뿐일 수 있다. 정밀 비교가 필요하면 max_samples 를 올리거나
    seam.measure(전 프레임)를 따로 돌릴 것.
  · 인코딩 자체의 바닥값(x264 양자화·링잉)이 Δu'v' 에 0.00x 대로 섞인다.
    절대 0 을 기대하지 말고 **대조 보정(STE 등)과의 상대 비교**로 읽는다
    (seam.py 의 인코딩 대조군 논리와 같다).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pse_bt1702 as BT

UV_D65 = np.array([0.19783, 0.46832], np.float32)  # D65 백색점 (u', v')
SAT_MIN = 0.05        # 채도손실률 분모 하한 — 무채색(백/회) 화소 제외
PEAK_PCTL = 99.0      # 프레임 내 피크 휘도 백분위 (seam.py 헤일로와 같은 눈금)


def _open(path):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise IOError(f"영상을 열 수 없습니다: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    # 컨테이너가 거짓 fps 를 신고하는 경우가 있다 (VP9 webm 1000fps 실측).
    # pse_bt1702.analyze() / seam.make_control() 과 같은 가드.
    if not fps or fps != fps or fps <= 0 or fps > 240:
        fps = 30.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    return cap, fps, n


def _flash_rule(rep: dict) -> dict:
    return (rep or {}).get("rules", {}).get("flash", {}) or {}


def measure(src_path, out_path, report_before=None, report_after=None,
            max_samples: int = 120, verbose: bool = False) -> dict:
    """보정 전(src_path)/후(out_path) 쌍에서 impact JSON(모듈 docstring 참조)을
    만든다. report_before/report_after 는 pse_bt1702.analyze() 결과 dict —
    판정 파이프라인이 이미 계산한 값이 있으면 넘겨서 재계산을 아낀다."""
    cap_s, fps, n_s = _open(src_path)
    cap_o, _, n_o = _open(out_path)
    # 짝지을 수 있는 프레임 수로 stride 를 정한다. 메타데이터가 깨져 0 이면
    # stride=1 로 전 프레임을 짝짓는다 (루프는 어차피 짧은 쪽에서 멈춘다).
    n = min(n_s, n_o) if (n_s > 0 and n_o > 0) else max(n_s, n_o)
    stride = max(1, int(math.ceil(n / float(max_samples)))) if n > 0 else 1

    samples = []                # (t_s, mean_src, mean_out, p99_src, p99_out)
    duv_pool = []               # lit 화소별 Δu'v' (전 샘플 합산)
    loss_sum = 0.0
    loss_n = 0
    idx = 0
    while True:
        if idx % stride:        # 비표본 프레임은 grab 만 — 디코드 후처리 생략
            if not (cap_s.grab() and cap_o.grab()):
                break
            idx += 1
            continue
        ok_s, fr_s = cap_s.read()
        ok_o, fr_o = cap_o.read()
        if not ok_s or not ok_o:
            break
        if fr_o.shape[:2] != fr_s.shape[:2]:
            fr_o = cv2.resize(fr_o, (fr_s.shape[1], fr_s.shape[0]),
                              interpolation=cv2.INTER_AREA)

        # ── 휘도: 정본 선형광 cd/m² (원해상도에서 — 피크 p99 가 축소에 민감)
        lum_s = BT.luminance_cd(fr_s, coherent=False)
        lum_o = BT.luminance_cd(fr_o, coherent=False)
        samples.append((idx / fps,
                        float(lum_s.mean()), float(lum_o.mean()),
                        float(np.percentile(lum_s, PEAK_PCTL)),
                        float(np.percentile(lum_o, PEAK_PCTL))))

        # ── 색: 96px 축소본에서 u'v' (docstring '측정 규약' 참조)
        cw = min(BT.COLOR_W, fr_s.shape[1])
        chh = max(2, int(round(fr_s.shape[0] * cw / fr_s.shape[1])))
        sm_s = cv2.resize(fr_s, (cw, chh), interpolation=cv2.INTER_AREA)
        sm_o = cv2.resize(fr_o, (cw, chh), interpolation=cv2.INTER_AREA)
        uv_s, uv_o = BT.uv_prime(sm_s), BT.uv_prime(sm_o)
        lit = (sm_s.max(axis=2) >= BT.RB_MIN_V) & \
              (sm_o.max(axis=2) >= BT.RB_MIN_V)
        if lit.any():
            duv_pool.append(np.linalg.norm(uv_o - uv_s, axis=-1)[lit])
            sat_s = np.linalg.norm(uv_s - UV_D65, axis=-1)
            sat_o = np.linalg.norm(uv_o - UV_D65, axis=-1)
            m = lit & (sat_s >= SAT_MIN)
            if m.any():
                loss = np.maximum(sat_s[m] - sat_o[m], 0.0) / sat_s[m]
                loss_sum += float(loss.sum())
                loss_n += int(m.sum())
        idx += 1
        if verbose and idx % 600 == 0:
            print(f"    ... {idx} frames", file=sys.stderr)
    cap_s.release()
    cap_o.release()
    if not samples:
        raise IOError(f"짝지을 프레임이 없습니다: {src_path} / {out_path}")

    # ── 플래시: 정본 심판 값 그대로 (없으면 직접 판정)
    if report_before is None:
        report_before = BT.analyze(str(src_path),
                                   with_pattern=False, with_cut=False)
    if report_after is None:
        report_after = BT.analyze(str(out_path),
                                  with_pattern=False, with_cut=False)
    fl_b, fl_a = _flash_rule(report_before), _flash_rule(report_after)

    arr = np.array([s[1:] for s in samples], np.float64)
    ts = np.array([s[0] for s in samples], np.float64)

    mean_src, mean_out = float(arr[:, 0].mean()), float(arr[:, 1].mean())
    lum_mean_drop = ((1.0 - mean_out / mean_src) * 100.0
                     if mean_src >= 1e-6 else 0.0)

    in_seg = np.zeros(len(ts), bool)
    for seg in fl_b.get("segments") or []:
        in_seg |= (ts >= float(seg[0])) & (ts <= float(seg[1]))
    sel = arr[in_seg] if in_seg.any() else arr   # 구간 없으면 전체로 대체
    p99_src, p99_out = float(sel[:, 2].mean()), float(sel[:, 3].mean())
    lum_peak_drop = ((1.0 - p99_out / p99_src) * 100.0
                     if p99_src >= 1e-6 else 0.0)

    if duv_pool:
        duv = np.concatenate(duv_pool)
        mean_duv, p95_duv = float(duv.mean()), float(np.percentile(duv, 95))
    else:
        mean_duv = p95_duv = 0.0
    loss_rate = (loss_sum / loss_n) if loss_n else 0.0

    return {
        "v": 1,
        "lum_mean_drop_pct": round(float(lum_mean_drop), 2),
        "lum_peak_drop_pct": round(float(lum_peak_drop), 2),
        "flash_before": int(fl_b.get("total_events", 0) or 0),
        "flash_after": int(fl_a.get("total_events", 0) or 0),
        "flash_viol_s_before": round(float(fl_b.get("violation_seconds", 0.0)
                                           or 0.0), 2),
        "flash_viol_s_after": round(float(fl_a.get("violation_seconds", 0.0)
                                          or 0.0), 2),
        "color_mean_duv": round(mean_duv, 5),
        "color_p95_duv": round(p95_duv, 5),
        "color_keep_pct": round(100.0 * (1.0 - loss_rate), 2),
    }


def report(r: dict, src: str = None, out: str = None) -> str:
    L = []
    if src:
        L.append(f"{src}")
        L.append(f"  → {out}")
    L.append(f"  휘도    전체 평균 {r['lum_mean_drop_pct']:+.2f}%  ·  "
             f"위반구간 p99 {r['lum_peak_drop_pct']:+.2f}%   (양수 = 어두워짐)")
    L.append(f"  플래시  {r['flash_before']}회 / {r['flash_viol_s_before']:.2f}s"
             f"  →  {r['flash_after']}회 / {r['flash_viol_s_after']:.2f}s")
    L.append(f"  색      Δu'v' 평균 {r['color_mean_duv']:.5f} · "
             f"p95 {r['color_p95_duv']:.5f}  ·  "
             f"채도 보존 {r['color_keep_pct']:.2f}%")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(
        description="보정 전/후 영향 지표 — impact JSON (videos.impact_json 계약)")
    ap.add_argument("src", help="보정 전 원본")
    ap.add_argument("out", help="보정 후 출력")
    ap.add_argument("--max-samples", type=int, default=120)
    ap.add_argument("--json", action="store_true", help="계약 JSON 만 출력")
    a = ap.parse_args()
    r = measure(a.src, a.out, max_samples=a.max_samples)
    if a.json:
        print(json.dumps(r, ensure_ascii=False))
    else:
        print(report(r, a.src, a.out))


if __name__ == "__main__":
    main()
