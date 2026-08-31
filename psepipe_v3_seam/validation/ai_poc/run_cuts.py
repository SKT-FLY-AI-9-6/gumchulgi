# -*- coding: utf-8 -*-
"""PoC2 — TransNetV2 vs 현행 컷 검출(NCC / pse_cut.Stream) 비교."""
import csv, json, os, subprocess, sys, time
sys.path.insert(0, "/home/user/gumchulgi/psepipe_v3_seam")
import cv2, numpy as np, torch
import pse_cut, pse_chroma
from transnetv2_pytorch.transnetv2_pytorch import TransNetV2

S = "/tmp/claude-0/-home-user-gumchulgi/8b6ecb4d-7f89-5d01-9d46-550dce056d9c/scratchpad"
UP = "/root/.claude/uploads/8b6ecb4d-7f89-5d01-9d46-550dce056d9c"
CUTS = f"{S}/ai_poc/cuts"; os.makedirs(CUTS, exist_ok=True)
W, H, FPS = 640, 360, 30

def make_scene(path, kind, sec=4):
    """확연히 다른 두 장면 — A: 청색 대각 그라디언트+원, B: 주황 수직 밴드+사각."""
    fr = []
    for i in range(int(sec * FPS)):
        img = np.zeros((H, W, 3), np.uint8)
        if kind == "A":
            xx, yy = np.meshgrid(np.linspace(0, 1, W), np.linspace(0, 1, H))
            img[..., 0] = (200 * (xx * .6 + yy * .4)).astype(np.uint8)
            img[..., 1] = (90 * yy).astype(np.uint8)
            cv2.circle(img, (int(W * .3) + i, int(H * .5)), 60, (255, 210, 120), -1)
        else:
            xx, _ = np.meshgrid(np.linspace(0, 1, W), np.linspace(0, 1, H))
            img[..., 2] = (60 + 180 * ((np.sin(xx * 22) > 0))).astype(np.uint8)
            img[..., 1] = 110
            cv2.rectangle(img, (int(W * .55) - i, 80), (int(W * .55) - i + 140, 260), (40, 40, 240), -1)
        fr.append(img)
    return fr

def write(frames, path):
    p = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                          "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264",
                          "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", path],
                         stdin=subprocess.PIPE)
    for f in frames:
        p.stdin.write(np.ascontiguousarray(f).tobytes())
    p.stdin.close(); p.wait()

def build_clips():
    A, B = make_scene(None, "A"), make_scene(None, "B")
    write(A + B, f"{CUTS}/hardcut_test.mp4")            # GT: 컷 1개 @ 4.00s
    n = FPS                                             # 1초 디졸브
    mid = [cv2.addWeighted(A[-n + i], 1 - (i + 1) / n, B[i], (i + 1) / n, 0) for i in range(n)]
    write(A[:-n] + mid + B[n:], f"{CUTS}/dissolve_test.mp4")   # GT: 디졸브 3.0~4.0s

def ncc_cuts(path):
    """pse_chroma 와 동일 정의: 64x64 그레이 NCC, 임계 0.45, 불응 0.5s."""
    cap = cv2.VideoCapture(path); fps = cap.get(cv2.CAP_PROP_FPS) or 30
    prev, since, gap, out, i = None, 10**9, max(1, int(round(fps * 0.5))), [], 0
    while True:
        ok, fr = cap.read()
        if not ok: break
        g = cv2.resize(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY), (64, 64)).astype(np.float32)
        g -= g.mean(); sd = float(g.std()); gn = g / sd if sd > 1e-3 else np.zeros_like(g)
        cut = prev is not None and sd > 1e-3 and float((gn * prev).mean()) < pse_chroma.CUT_THRESH
        if cut and since < gap: cut = False
        since = 0 if cut else since + 1
        if cut: out.append(round(i / fps, 2))
        prev = gn; i += 1
    cap.release(); return out

def judge_cuts(path):
    """심판(pse_bt1702)이 쓰는 pse_cut.Stream — 블록 히스토그램 기반."""
    cap = cv2.VideoCapture(path); fps = cap.get(cv2.CAP_PROP_FPS) or 30
    st = pse_cut.Stream(fps); i = 0
    while True:
        ok, fr = cap.read()
        if not ok: break
        h = 180; w = int(fr.shape[1] * h / fr.shape[0])
        st.push(cv2.resize(fr, (w, h), interpolation=cv2.INTER_AREA)); i += 1
    cap.release()
    return [round(f / fps, 2) for f in st.cut_frames]

def transnet_cuts(model, path, thr=0.5):
    cap = cv2.VideoCapture(path); fps = cap.get(cv2.CAP_PROP_FPS) or 30
    fr = []
    while True:
        ok, f = cap.read()
        if not ok: break
        fr.append(cv2.cvtColor(cv2.resize(f, (48, 27), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB))
    cap.release()
    v = np.stack(fr)
    pad_s = np.repeat(v[:1], 25, 0); pad_e = np.repeat(v[-1:], 25 + 50, 0)
    padded = np.concatenate([pad_s, v, pad_e])
    preds = []
    with torch.no_grad():
        for ptr in range(0, len(v) + 50, 50):
            batch = padded[ptr:ptr + 100]
            if len(batch) < 100: break
            t = torch.from_numpy(batch).unsqueeze(0)
            single, _ = model(t)
            preds.append(torch.sigmoid(single).numpy()[0, 25:75, 0])
    p = np.concatenate(preds)[:len(v)]
    cuts = [round(i / fps, 2) for i in range(1, len(p)) if p[i] >= thr and p[i - 1] < thr]
    return cuts, float(p.max())

if __name__ == "__main__":
    build_clips()
    m = TransNetV2(); import transnetv2_pytorch as _t
    wp = os.path.join(os.path.dirname(_t.__file__), "transnetv2-pytorch-weights.pth")
    m.load_state_dict(torch.load(wp, map_location="cpu", weights_only=True)); m.eval()
    targets = [("dissolve_test", f"{CUTS}/dissolve_test.mp4", "디졸브 3.0~4.0s"),
               ("hardcut_test", f"{CUTS}/hardcut_test.mp4", "하드컷 4.00s"),
               ("02_flash_2hz", f"{S}/testclips/02_flash_2hz.mkv", "컷 없음(전면 2Hz 플래시)"),
               ("01_flash_5hz", f"{S}/testclips/01_flash_5hz.mkv", "컷 없음(전면 5Hz 플래시)"),
               ("cera_khin", f"{UP}/5cb50f8a-cera_khin.mp4", "실사(정답없음)"),
               ("pinkvenom", f"{UP}/1a6ccb54-pinkvenom.mp4", "실사(정답없음)"),
               ("travis_fein", f"{UP}/b2876855-travis_fein.mp4", "실사(정답없음)")]
    rows = []
    for name, path, gt in targets:
        t0 = time.time(); nc = ncc_cuts(path); t_ncc = time.time() - t0
        t0 = time.time(); jc = judge_cuts(path); t_j = time.time() - t0
        t0 = time.time(); tc, pmax = transnet_cuts(m, path); t_tn = time.time() - t0
        row = dict(clip=name, gt=gt, ncc_n=len(nc), judge_n=len(jc), transnet_n=len(tc),
                   ncc_t=[*nc][:8], judge_t=[*jc][:8], transnet_t=[*tc][:8],
                   tn_pmax=round(pmax, 3), sec_ncc=round(t_ncc, 1), sec_judge=round(t_j, 1),
                   sec_transnet=round(t_tn, 1))
        print(json.dumps(row, ensure_ascii=False), flush=True)
        rows.append(row)
        json.dump(rows, open(f"{S}/ai_poc/cutcompare.json", "w"), ensure_ascii=False, indent=1)
    with open(f"{S}/ai_poc/cutcompare.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print("DONE")
