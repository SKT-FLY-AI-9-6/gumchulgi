#!/usr/bin/env python3
"""TOG24 "Colorful Diffuse Intrinsic Image Decomposition" (compphoto/Intrinsic v2)
keyframe light-source layer (R+ = positive residual) probe.

Runs the full 5-stage pipeline on keyframes of:
  - cera_khin.mp4        : 6 evenly spaced keyframes
  - 09_local_strobe_10pct.mkv : 3 strobe-ON keyframes + IoU(R+ top-5% mask, GT strobe region)
  - travis_fein.mp4      : 3 evenly spaced keyframes

Outputs per-video 3-column montages [input | tonemapped R+ | dif_img] and a results JSON.

Setup notes (what was needed in the sandboxed CPU environment, 2026-08-24):
  pip install --no-deps torchvision timm antialiased_cnns
  pip install scikit-image matplotlib pillow beautifulsoup4 requests pyyaml huggingface_hub safetensors
  git clone https://github.com/CCareaga/MiDaS (@fb51e3a)   -> pip install --no-deps .
  git clone https://github.com/CCareaga/chrislib (@9a4c63f) -> pip install --no-deps .
  git clone https://github.com/compphoto/Intrinsic          -> pip install --no-deps .
  (pip install of https://codeload.github.com/... zip got HTTP 403 through the agent proxy; git clone worked)
  Weights: torch.hub.load_state_dict_from_url got HTTP 400 through the proxy -> pre-download with curl:
    for s in 0 1 2 3 4; do curl -sSL -o $TORCH_HOME/hub/checkpoints/stage_$s.pt \
      https://github.com/compphoto/Intrinsic/releases/download/v2.0/stage_$s.pt; done
  torch.hub.load("facebookresearch/WSL-Images", ...) inside altered_midas.blocks needs network
  (github API + dl.fbaipublicfiles.com, the latter hard-blocked) -> monkeypatched below with a
  torchvision resnext101_32x8d skeleton; load_models() overwrites every backbone weight from the
  release state dicts, so pretrained ImageNet weights are unnecessary.

On a 4090 notebook with open network you can likely drop the curl step (torch.hub will download),
but the monkeypatch is still recommended to avoid the dl.fbaipublicfiles dependency.
Usage: python tog24_probe.py --device cuda --res 1024   (or --device cpu --res 448)
"""
import argparse, json, os, sys, time, urllib.request

import cv2
import numpy as np
import torch

# ---------------------------------------------------------------------------
# monkeypatch: build resnext101 backbone locally instead of torch.hub.load()
# ---------------------------------------------------------------------------
import torchvision
import altered_midas.blocks as _B

def _local_resnext101_wsl(use_pretrained, in_chan=3, group_width=8, aa=False):
    if group_width != 8:
        raise ValueError("local patch only supports resnext101_32x8d (group_width=8)")
    resnet = torchvision.models.resnext101_32x8d(weights=None)
    if in_chan != 3:
        resnet.conv1 = torch.nn.Conv2d(in_chan, 64, 7, 2, 3, bias=False)
    return _B._make_resnet_backbone(resnet)

_B._make_pretrained_resnext101_wsl = _local_resnext101_wsl

# torch.hub.load("rwightman/gen-efficientnet-pytorch", "tf_efficientnet_lite3", ...) also needs
# network to resolve the hub repo (urllib got HTTP 400 through the proxy). Use a local git clone
# of that exact repo with source='local' — state-dict keys stay identical. timm's modern
# tf_efficientnet_lite3 is NOT a drop-in (no .act1 attribute).
_GEN_EFF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gen-efficientnet-pytorch")

def _local_efficientnet_lite3(use_pretrained, exportable=False, in_chan=3):
    if not os.path.isdir(_GEN_EFF_DIR):
        import subprocess
        subprocess.run(["git", "clone", "--depth", "1",
                        "https://github.com/rwightman/gen-efficientnet-pytorch.git", _GEN_EFF_DIR],
                       check=True)
    effnet = torch.hub.load(_GEN_EFF_DIR, "tf_efficientnet_lite3", source="local",
                            pretrained=use_pretrained, exportable=exportable)
    if in_chan != 3:
        effnet.conv_stem = _B.Conv2dSame(in_chan, 32, kernel_size=(3, 3), stride=(2, 2), bias=False)
    return _B._make_efficientnet_backbone(effnet)

_B._make_pretrained_efficientnet_lite3 = _local_efficientnet_lite3

from intrinsic.pipeline import load_models, run_pipeline  # noqa: E402

V2_URLS = [f"https://github.com/compphoto/Intrinsic/releases/download/v2.0/stage_{s}.pt"
           for s in range(5)]

def ensure_weights():
    """Pre-download v2 weights into the torch hub cache with urllib (progress-free);
    torch.hub.load_state_dict_from_url() then finds them in cache and skips network."""
    ckpt_dir = os.path.join(torch.hub.get_dir(), "checkpoints")
    os.makedirs(ckpt_dir, exist_ok=True)
    for url in V2_URLS:
        dst = os.path.join(ckpt_dir, url.rsplit("/", 1)[1])
        if os.path.exists(dst) and os.path.getsize(dst) > 1 << 20:
            continue
        print("downloading", url)
        urllib.request.urlretrieve(url, dst)

# ---------------------------------------------------------------------------
def read_frame(path, idx):
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
    ok, fr = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"failed to read frame {idx} of {path}")
    # NOTE: float32 like chrislib.data_util.load_image (float64 crashes the float32 nets)
    return cv2.cvtColor(fr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0

def max_side(path):
    cap = cv2.VideoCapture(path)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return max(w, h)

def video_info(path):
    cap = cv2.VideoCapture(path)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.release()
    return n, fps

def strobe_ground_truth(path, max_frames=200):
    """GT strobe mask from per-pixel temporal std of gray (strobe region flickers hard),
    plus per-frame mean brightness inside the mask to find strobe-ON frames."""
    cap = cv2.VideoCapture(path)
    frames = []
    while len(frames) < max_frames:
        ok, fr = cap.read()
        if not ok:
            break
        frames.append(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0)
    cap.release()
    stack = np.stack(frames)                       # T,H,W
    std = stack.std(axis=0)
    thr = 0.5 * std.max()
    mask = std > thr
    on_level = np.array([f[mask].mean() for f in stack])
    return mask, on_level, len(frames)

def tonemap(lin, scale):
    return np.clip(lin / max(scale, 1e-6), 0, 1) ** (1 / 2.2)

def put_label(img_u8, text):
    cv2.putText(img_u8, text, (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img_u8, text, (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    return img_u8

def process_video(models, path, frame_idxs, device, res, out_png, fps,
                  gt_mask=None, results_sink=None, tile_h=320):
    """Run pipeline on the given frames, write [input|R+|dif_img] montage, return stats."""
    rows_raw, stats = [], []
    for idx in frame_idxs:
        img = read_frame(path, idx)
        t0 = time.time()
        with torch.no_grad():
            res_d = run_pipeline(models, img, stage=4, resize_conf=int(res), device=device)
        dt = time.time() - t0
        pos = res_d["pos_res"]          # linear positive residual (H,W,3), model-res
        neg = res_d["neg_res"]
        dif = res_d["dif_img"]
        inp = res_d["image"]            # sRGB input at model res
        pos_mag = pos.mean(axis=2)
        over_frac = float((inp.max(axis=2) >= 0.98).mean())
        st = dict(frame=idx, t_sec=round(idx / fps, 2), sec=round(dt, 1),
                  shape=list(inp.shape[:2]),
                  pos_p999=float(np.quantile(pos_mag, 0.999)), pos_max=float(pos_mag.max()),
                  neg_mean=float(neg.mean()), neg_p999=float(np.quantile(neg.mean(axis=2), 0.999)),
                  overexp_frac=round(over_frac, 4))
        if gt_mask is not None:
            gt = cv2.resize(gt_mask.astype(np.uint8), (pos_mag.shape[1], pos_mag.shape[0]),
                            interpolation=cv2.INTER_NEAREST).astype(bool)
            top = pos_mag >= np.quantile(pos_mag, 0.95)      # R+ top-5% mask
            iou = float((top & gt).sum() / max((top | gt).sum(), 1))
            st["iou_top5_vs_gt"] = round(iou, 4)
            st["gt_area_frac"] = round(float(gt.mean()), 4)
        stats.append(st)
        rows_raw.append((idx, inp, pos_mag, neg.mean(axis=2), dif))
        print(f"  frame {idx}: {dt:.1f}s shape={inp.shape} "
              f"pos_p999={st['pos_p999']:.4f} " + (f"IoU={st.get('iou_top5_vs_gt')}" if gt_mask is not None else ""))

    # common R+ scale per video for comparable rows
    r_scale = max(np.quantile(pm, 0.995) for _, _, pm, _, _ in rows_raw)
    rows = []
    for idx, inp, pos_mag, neg_mag, dif in rows_raw:
        h, w = inp.shape[:2]
        tw = int(round(w * tile_h / h))
        def prep(x, label):
            u8 = (np.clip(x, 0, 1) * 255).astype(np.uint8)
            if u8.ndim == 2:
                u8 = cv2.applyColorMap(u8, cv2.COLORMAP_INFERNO)[:, :, ::-1]
            u8 = cv2.resize(u8, (tw, tile_h), interpolation=cv2.INTER_AREA)
            return put_label(np.ascontiguousarray(u8), label)
        t = idx / fps
        row = np.concatenate([
            prep(inp, f"input f{idx} ({t:.1f}s)"),
            prep(tonemap(pos_mag, r_scale), f"R+ (scale {r_scale:.3f})"),
            prep(np.clip(dif, 0, 1) ** (1 / 2.2), "dif_img"),
        ], axis=1)
        rows.append(row)
    mont = np.concatenate(rows, axis=0)
    cv2.imwrite(out_png, mont[:, :, ::-1])
    print("  wrote", out_png, mont.shape)
    if results_sink is not None:
        results_sink[os.path.basename(path)] = stats
    return stats

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--res", type=int, default=800,
                    help="max side for inference (int resize_conf); capped at each video's native max side. "
                         "800 => ~448px width on 720x1280 portrait (CPU ~9s/frame); on GPU try 1024+")
    ap.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--cera", default="/root/.claude/uploads/8b6ecb4d-7f89-5d01-9d46-550dce056d9c/5cb50f8a-cera_khin.mp4")
    ap.add_argument("--strobe", default="/tmp/claude-0/-home-user-gumchulgi/8b6ecb4d-7f89-5d01-9d46-550dce056d9c/scratchpad/testclips/09_local_strobe_10pct.mkv")
    ap.add_argument("--travis", default="/root/.claude/uploads/8b6ecb4d-7f89-5d01-9d46-550dce056d9c/b2876855-travis_fein.mp4")
    ap.add_argument("--skip-travis", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    ensure_weights()
    t0 = time.time()
    models = load_models("v2", device=a.device)
    print(f"load_models('v2') on {a.device}: {time.time()-t0:.1f}s")

    results = {"device": a.device, "res": a.res}

    # cera: 6 evenly spaced
    n, fps = video_info(a.cera)
    res_c = min(a.res, max_side(a.cera))
    idxs = [int((i + 0.5) * n / 6) for i in range(6)]
    print("cera keyframes", idxs, "res", res_c)
    process_video(models, a.cera, idxs, a.device, res_c,
                  os.path.join(a.out, "tog24_cera_montage.png"), fps, results_sink=results)

    # 09 local strobe: GT mask + 3 strobe-ON frames spread over the clip
    gt_mask, on_level, T = strobe_ground_truth(a.strobe)
    _, fps_s = video_info(a.strobe)
    thirds = [range(0, T // 3), range(T // 3, 2 * T // 3), range(2 * T // 3, T)]
    on_idxs = [int(max(rg, key=lambda i: on_level[i])) for rg in thirds]
    print(f"strobe GT area={gt_mask.mean():.3f}, ON keyframes {on_idxs}")
    st = process_video(models, a.strobe, on_idxs, a.device, min(a.res, max_side(a.strobe)),
                       os.path.join(a.out, "tog24_strobe09_montage.png"), fps_s,
                       gt_mask=gt_mask, results_sink=results)
    results["strobe_iou_mean"] = round(float(np.mean([s["iou_top5_vs_gt"] for s in st])), 4)

    # travis: 3 evenly spaced
    if not a.skip_travis:
        n, fps = video_info(a.travis)
        res_t = min(a.res, max_side(a.travis))
        idxs = [int((i + 0.5) * n / 3) for i in range(3)]
        print("travis keyframes", idxs, "res", res_t)
        process_video(models, a.travis, idxs, a.device, res_t,
                      os.path.join(a.out, "tog24_travis_montage.png"), fps, results_sink=results)

    all_secs = [s["sec"] for v in results.values() if isinstance(v, list) for s in v]
    results["sec_per_frame_mean"] = round(float(np.mean(all_secs)), 1)
    with open(os.path.join(a.out, "tog24_results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("sec/frame mean:", results["sec_per_frame_mean"])
    print(json.dumps({k: v for k, v in results.items() if not isinstance(v, list)}, indent=1))

if __name__ == "__main__":
    main()
