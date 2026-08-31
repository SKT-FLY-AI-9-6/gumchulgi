# -*- coding: utf-8 -*-
"""TOG24 잔차층 재분석 — 포화 광원은 R+ 가 아니라 R− 로 가는가?

tog24_probe 1차 실측: 09_local_strobe 에서 R+ top5% IoU = 0.036 (사실상 실패).
같은 프레임에서 pos_p999=0.034 인데 neg_p999=0.99, overexp_frac=0.10 —
스트로브 영역이 통째로 포화(클리핑)돼 양수 잔차가 아니라 음수 잔차로 간다는
가설. R+/R−/|R| 및 순수 휘도 상위 5% (AI 없는 기준선) 의 IoU 를 비교한다.
"""
import json, os, sys, time
import cv2, numpy as np, torch
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tog24_probe as TP
from intrinsic.pipeline import load_models, run_pipeline

S = "/tmp/claude-0/-home-user-gumchulgi/8b6ecb4d-7f89-5d01-9d46-550dce056d9c/scratchpad"
STROBE = f"{S}/testclips/09_local_strobe_10pct.mkv"
BULBS = f"{S}/ai_poc/clips/12_bulbs_grid.mkv"

def iou(mask, gt):
    return round(float((mask & gt).sum() / max((mask | gt).sum(), 1)), 4)

def top_mask(x, q=0.95):
    return x >= np.quantile(x, q)

def analyze(models, path, idxs, tag, res=800, device="cpu"):
    gt_mask, on_level, T = TP.strobe_ground_truth(path)
    out = []
    for idx in idxs:
        img = TP.read_frame(path, idx)
        t0 = time.time()
        with torch.no_grad():
            r = run_pipeline(models, img, stage=4,
                             resize_conf=int(min(res, TP.max_side(path))), device=device)
        pos, neg = r["pos_res"].mean(axis=2), r["neg_res"].mean(axis=2)
        absr = pos + np.abs(neg)
        inp = r["image"]
        lum = inp.mean(axis=2) if inp.ndim == 3 else inp
        gt = cv2.resize(gt_mask.astype(np.uint8), (pos.shape[1], pos.shape[0]),
                        interpolation=cv2.INTER_NEAREST).astype(bool)
        row = dict(clip=tag, frame=int(idx), sec=round(time.time() - t0, 1),
                   gt_area=round(float(gt.mean()), 4),
                   iou_pos=iou(top_mask(pos), gt), iou_neg=iou(top_mask(np.abs(neg)), gt),
                   iou_abs=iou(top_mask(absr), gt), iou_lum=iou(top_mask(lum), gt),
                   pos_p999=round(float(np.quantile(pos, .999)), 4),
                   neg_p999=round(float(np.quantile(np.abs(neg), .999)), 4))
        print(row, flush=True)
        out.append(row)
        # 몽타주: 입력 | R+ | |R−| | 휘도상위 (GT 윤곽 오버레이)
        tiles = []
        for x, lab in ((inp, "input"), (pos, "R+"), (np.abs(neg), "|R-|"), (lum, "luminance")):
            u8 = (np.clip(x / max(np.quantile(x, .995), 1e-6), 0, 1) ** (1 / 2.2) * 255).astype(np.uint8) \
                 if x.ndim == 2 else (np.clip(x, 0, 1) * 255).astype(np.uint8)
            if u8.ndim == 2:
                u8 = cv2.applyColorMap(u8, cv2.COLORMAP_INFERNO)[:, :, ::-1]
            u8 = np.ascontiguousarray(cv2.resize(u8, (int(u8.shape[1] * 320 / u8.shape[0]), 320)))
            g = cv2.resize(gt.astype(np.uint8) * 255, (u8.shape[1], u8.shape[0]), interpolation=cv2.INTER_NEAREST)
            cnts, _ = cv2.findContours(g, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(u8, cnts, -1, (0, 255, 0), 1)
            tiles.append(TP.put_label(u8, lab))
        cv2.imwrite(f"{S}/ai_poc/tog24_resid_{tag}_{idx}.png",
                    np.hstack(tiles)[:, :, ::-1])
    return out

if __name__ == "__main__":
    TP.ensure_weights()
    models = load_models("v2", device="cpu")
    rows = analyze(models, STROBE, [0, 42], "strobe09")
    rows += analyze(models, BULBS, [30, 90], "bulbs12")
    json.dump(rows, open(f"{S}/ai_poc/tog24_residual.json", "w"), indent=1)
    for k in ("iou_pos", "iou_neg", "iou_abs", "iou_lum"):
        print(k, "평균", round(float(np.mean([r[k] for r in rows])), 4))
