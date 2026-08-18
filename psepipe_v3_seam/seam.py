# -*- coding: utf-8 -*-
"""이질감 측정기 — 필터가 만든 '보이는 부작용' 3가지를 잰다.

목표가 "이질감 없이"인데 지금까지 지표는 PSNR/선택비뿐이었다. 둘 다 이질감
지표가 아니다 — 위반 구역 PSNR 은 일부러 낮고(점멸을 눌렀으니), 이질감은
**어디가 얼마나 달라졌나**가 아니라 **원본에 없던 구조가 생겼나**의 문제다.

지표 3개, 전부 마스크 없이 (src, out) 쌍만으로 계산한다:

  · 펌핑 P — 원본이 시간적으로 정지한 화소에서 출력이 움직인 양.
      정지 화소: |ΔY_src| <= 1.0 이 **연속 STATIC_RUN(10)프레임** 이어진 화소.
      1프레임 정지로 재면 5Hz 점멸도 켜짐/꺼짐 사이에서 "정지"로 잡혀
      위반 구역을 고치느라 생긴 필연적 변화가 섞였다(1차 보정에서 실측).
      10프레임이면 3Hz 이상 점멸은 구조적으로 배제된다 (30fps 에서 3Hz 의
      반주기 = 5프레임 < 10).  P = 그 화소들의 mean|ΔY_out|.

  · 헤일로 H — 원본에 없던 공간 경계가 생긴 양.
      G = 휘도 Sobel 크기.  H = 프레임별 **p99**(max(G_out - G_src, 0)) 의 평균.
      평균으로 재면 경계 링(화소의 ~1%)이 나머지 99% 에 희석돼 하드 마스크와
      평활 마스크가 구분이 안 됐다(1차 보정에서 실측). 상위 1% 로 잡아야
      "가장 나쁜 경계"를 본다.

  · 잔상 G — 움직인 화소에서 출력이 **과거 입력에 머무는** 양.
      Kim&Moon harness/ghost_metric.py 의 lag/drag 를 CPU 범용 축으로 이식.
      사람 눈이 잡았는데 판정·펌핑·헤일로가 전부 못 잡은 축이다 — A 는
      out = prev + k·(in - prev) 라 k 가 작으면 출력이 입력을 못 따라가고,
      움직이는 물체에서 그게 잔상(유령 얼굴)으로 보인다.
        lag  : 출력이 몇 프레임 전 입력을 가장 닮았는가 (0 = 지연 없음)
        drag : 움직인 화소(|ΔY_src| > 6)에서 |Y_out - Y_src| 가 그 화소의
               움직임 크기 대비 얼마인가 (1.0 = 입력 변화를 전혀 못 따라감)
      주의: 점멸 프레임에서는 전 화면이 '움직임'으로 잡히므로 drag 에
      점멸 억제분이 섞인다. 그래서 이 축은 **같은 판정 결과끼리의 상대
      비교**로 읽는다 — 판정을 이기고 drag 가 낮은 쪽이 잔상이 적은 것.

셋 다 인코딩 자체가 바닥값을 만든다 (x264 가 링잉/블록을 넣는다). 그래서
절대값이 아니라 **인코딩-만-한 대조군 대비**로 읽어야 한다. --base 로 대조군을
넘기면 초과분(excess)을 같이 낸다.

검증(대조군 보정): 지표가 지표 노릇을 하는지 아래 4개로 확인했다 —
  copy(인코딩만) ≈ 0 / 평활 마스크 ≈ copy / 하드 시간창 ↑펌핑 / 하드 공간마스크 ↑헤일로.
"""
import argparse, json, subprocess, sys
import cv2
import numpy as np


def make_control(src, dst, crf=16):
    """인코딩-만-한 대조군을 **프레임 정렬 보장**으로 만든다.
    `ffmpeg -i src` 재인코딩은 타임스탬프가 이상한 실전 파일(VFR 릴스)에서
    프레임이 밀려 모션 전체가 '새 구조'로 잡힌다 (실측 cera: copy 헤일로 172 >
    필터 16.6 — 지표가 뒤집힘). cv2 로 디코드한 프레임을 그대로 파이프에 넣으면
    필터 출력과 같은 경로라 어긋날 수 없다."""
    cap = cv2.VideoCapture(src)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    q = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                          "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
                          "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
                          "-pix_fmt", "yuv420p", dst], stdin=subprocess.PIPE)
    while True:
        ok, f = cap.read()
        if not ok:
            break
        q.stdin.write(f.tobytes())
    cap.release(); q.stdin.close(); q.wait()
    return dst

STATIC_THR = 1.0      # 8bit 휘도에서 이 이하로 변한 화소 = 정지
STATIC_RUN = 10       # 이만큼 연속으로 정지여야 진짜 정지 (3Hz 점멸 배제)

GHOST_MOTION_THR = 6.0   # 8bit 휘도, 이 이상 변한 화소 = 움직임 (ghost_metric 원본값)
GHOST_MIN_PIX = 100      # 움직인 화소가 이보다 적은 프레임은 잔상 표본에서 제외
GHOST_LAGS = 4           # 몇 프레임 과거까지 '닮음'을 뒤지는가


def _luma(f):
    return cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32)


def _grad(y):
    gx = cv2.Sobel(y, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(y, cv2.CV_32F, 0, 1, ksize=3)
    return cv2.magnitude(gx, gy)


def measure(src, out, max_frames=None, verbose=False):
    ca, cb = cv2.VideoCapture(src), cv2.VideoCapture(out)
    if not ca.isOpened() or not cb.isOpened():
        raise IOError(f"열 수 없음: {src} / {out}")
    prev_s = prev_o = None
    streak = None                      # 화소별 연속 정지 프레임 수
    pump_sum = 0.0; pump_n = 0
    pump_worst = 0.0; pump_worst_t = -1
    halo_sum = 0.0; halo_frames = 0
    halo_worst = 0.0; halo_worst_t = -1
    hist = []                          # 최근 src 휘도 (최신이 앞), 잔상 lag 탐색용
    ghost_lag_sum = 0.0; ghost_drag_sum = 0.0; ghost_frames = 0
    ghost_worst = 0.0; ghost_worst_t = -1
    t = 0
    while True:
        oa, fa = ca.read(); ob, fb = cb.read()
        if not (oa and ob):
            break
        if fa.shape != fb.shape:
            fb = cv2.resize(fb, (fa.shape[1], fa.shape[0]))
        ys, yo = _luma(fa), _luma(fb)

        # 헤일로 — 프레임별 상위 1% (경계 링을 겨냥)
        ex = np.maximum(_grad(yo) - _grad(ys), 0.0)
        h = float(np.percentile(ex, 99))
        halo_sum += h; halo_frames += 1
        if h > halo_worst:
            halo_worst, halo_worst_t = h, t

        # 펌핑 — 연속 STATIC_RUN 프레임 정지한 화소만
        if prev_s is not None:
            d_src = np.abs(ys - prev_s)
            quiet = d_src <= STATIC_THR
            streak = np.where(quiet, streak + 1, 0) if streak is not None \
                     else quiet.astype(np.int32)
            static = streak >= STATIC_RUN
            n = int(static.sum())
            if n:
                p = float(np.abs(yo - prev_o)[static].sum())
                pump_sum += p; pump_n += n
                pf = p / n
                if pf > pump_worst:
                    pump_worst, pump_worst_t = pf, t

            # 잔상 — 움직인 화소에서 출력이 어느 과거 입력을 닮았나
            m = d_src > GHOST_MOTION_THR
            if int(m.sum()) >= GHOST_MIN_PIX and len(hist) >= GHOST_LAGS:
                errs = [float(np.abs(yo[m] - ys[m]).mean())]
                errs += [float(np.abs(yo[m] - h[m]).mean())
                         for h in hist[:GHOST_LAGS]]
                ghost_lag_sum += int(np.argmin(errs))
                drag = errs[0] / (float(d_src[m].mean()) + 1e-6)
                ghost_drag_sum += drag; ghost_frames += 1
                if drag > ghost_worst:
                    ghost_worst, ghost_worst_t = drag, t
        hist.insert(0, ys)
        del hist[GHOST_LAGS:]
        prev_s, prev_o = ys, yo
        t += 1
        if max_frames and t >= max_frames:
            break
        if verbose and t % 300 == 0:
            print(f"    ... {t}", file=sys.stderr)
    ca.release(); cb.release()
    return {
        "frames": t,
        "pumping": round(pump_sum / max(pump_n, 1), 4),
        "pumping_worst": round(pump_worst, 4),
        "pumping_worst_t": pump_worst_t,
        "halo": round(halo_sum / max(halo_frames, 1), 4),
        "halo_worst": round(halo_worst, 4),
        "halo_worst_t": halo_worst_t,
        "ghost_lag": round(ghost_lag_sum / max(ghost_frames, 1), 3),
        "ghost_drag": round(ghost_drag_sum / max(ghost_frames, 1), 4),
        "ghost_drag_worst": round(ghost_worst, 4),
        "ghost_drag_worst_t": ghost_worst_t,
        "ghost_frames": ghost_frames,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--base", default=None,
                    help="인코딩-만-한 대조군. 주면 excess(대조군 초과분)도 낸다")
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--make-base", action="store_true",
                    help="대조군을 자동 생성해 초과분을 낸다")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = measure(a.src, a.out, a.max_frames)
    base = a.base
    if a.make_base and not base:
        import os, tempfile
        base = os.path.join(tempfile.gettempdir(), "_seam_ctrl.mp4")
        make_control(a.src, base)
    if base:
        b = measure(a.src, base, a.max_frames)
        r["base"] = b
        r["pumping_excess"] = round(max(r["pumping"] - b["pumping"], 0.0), 4)
        r["halo_excess"] = round(max(r["halo"] - b["halo"], 0.0), 4)
        r["ghost_drag_excess"] = round(max(r["ghost_drag"] - b["ghost_drag"], 0.0), 4)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        print(f"펌핑 {r['pumping']:.3f} (최악 {r['pumping_worst']:.3f} @f{r['pumping_worst_t']})   "
              f"헤일로 {r['halo']:.3f} (최악 {r['halo_worst']:.3f} @f{r['halo_worst_t']})   "
              f"잔상 lag {r['ghost_lag']:.2f} drag {r['ghost_drag']:.3f} "
              f"(최악 {r['ghost_drag_worst']:.3f} @f{r['ghost_drag_worst_t']}, 표본 {r['ghost_frames']}f)")
        if base:
            print(f"인코딩 대조군 대비 초과 — 펌핑 +{r['pumping_excess']:.3f}  헤일로 +{r['halo_excess']:.3f}"
                  f"  잔상 drag +{r['ghost_drag_excess']:.3f}")


if __name__ == "__main__":
    main()
