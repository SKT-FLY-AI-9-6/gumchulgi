# -*- coding: utf-8 -*-
"""잔상(ghosting) 측정자.

사람 눈이 잡았는데 기존 지표(판정·헤일로·펌핑)가 못 잡은 것을 잰다.

A 는 out = prev + k*(in - prev) 라 k 가 작으면 출력이 입력을 못 따라간다.
움직이는 물체에서 그게 잔상으로 보인다. 판정은 '깜빡임이 없어졌는가'만 보고
헤일로는 '경계에 테두리가 생겼는가'만 보므로 이 축이 비어 있었다.

두 가지로 잰다:
  lag   출력이 몇 프레임 전 입력을 닮았는가 (0 이면 지연 없음)
  drag  움직이는 화소에서 |out_t - in_t| 가 그 화소의 움직임 대비 얼마인가
        (1.0 이면 출력이 입력 변화를 전혀 못 따라간 것)
"""
import os, sys
sys.path.insert(0, os.getcwd())
import cv2, numpy as np
import pselive3 as P3, psegpu_full as PGF

CLIPS = sys.argv[1:] or ["_dfull/cera_khin_360.mp4", "_dfull/travis_fein_360.mp4"]
LAGS = 4


def read_all(p):
    cap = cv2.VideoCapture(p); fr = []
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    while True:
        ok, f = cap.read()
        if not ok: break
        fr.append(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32))
    cap.release(); return fr, fps


def ghost(inp, out):
    """(평균 지연 프레임, drag) 를 돌려준다."""
    n = min(len(inp), len(out))
    lags, drags = [], []
    for t in range(LAGS, n):
        mo = np.abs(inp[t] - inp[t - 1])
        m = mo > 6.0                       # 실제로 움직인 화소만
        if m.sum() < 100:
            continue
        # 어느 과거 입력과 가장 닮았나
        errs = [np.abs(out[t][m] - inp[t - k][m]).mean() for k in range(LAGS + 1)]
        lags.append(int(np.argmin(errs)))
        drags.append(float(np.abs(out[t][m] - inp[t][m]).mean() / (mo[m].mean() + 1e-6)))
    return float(np.mean(lags)), float(np.mean(drags))


CFGS = [("불응기 없음 (수정 전)", dict(cut_min_gap_s=0.0)),
        ("불응기 0.2 (현재)", dict(cut_min_gap_s=0.2)),
        ("불응기 0.2 + hold 0.10", dict(cut_min_gap_s=0.2, hold_s=0.10)),
        ("불응기 0.2 + hold 0.05", dict(cut_min_gap_s=0.2, hold_s=0.05)),
        ("불응기 0.2 + slew x2", dict(cut_min_gap_s=0.2, slew_safety=1.6))]

for clip in CLIPS:
    inp, fps = read_all(clip)
    print(f"\n{os.path.basename(clip)}  {len(inp)}프레임")
    print(f"{'설정':<26}{'지연(프레임)':>13}{'drag':>8}{'컷':>6}")
    for name, kw in CFGS:
        cfg = P3.Cfg()
        for k, v in kw.items():
            setattr(cfg, k, v)
        rg, og = PGF.run(clip, cfg, PGF.OptF(), warmup=2)
        out = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32) for f in og]
        lag, drag = ghost(inp, out)
        print(f"{name:<26}{lag:>13.2f}{drag:>8.3f}{rg['cuts']:>6}", flush=True)
