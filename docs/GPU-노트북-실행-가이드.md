# GPU 노트북 실행 가이드 (2026-08-14)

클라우드 컨테이너(CPU 전용)에서 **못 한 것들**을 GPU 노트북에서 돌리는 순서.
이미 끝난 것: 검출기 통합, comfort v0.2 병합, 합성 5클립 3파전(A 5/5 승),
D_ste·D_full CPU 실측(둘 다 패), 비교 영상 3편. → `validation/three_way_synth.csv`,
`dfull_synth.csv` 참조. 아래는 **GPU가 있어야만 되는 나머지 4개**다.

---

## 0. 준비 (1회, 15분)

```bash
git clone https://github.com/SKT-FLY-AI-9-6/gumchulgi.git
cd gumchulgi
git checkout fix/ste-report-consistency          # 통합 완료된 브랜치

# BlazeBVD 코드+가중치 (blazebvd 브랜치, LFS)
git worktree add ../blazebvd-wt origin/blazebvd
cd ../blazebvd-wt
git lfs install && git lfs pull --include "blazebvd-training/runs/davis_blazebvd/**"
cd ../gumchulgi

pip install opencv-python numpy scipy pillow pyyaml tqdm
pip install torch torchvision                    # CUDA 자동 포함 (4090 OK)
pip install -e ../blazebvd-wt/blazebvd-training --no-deps
# ffmpeg 이 PATH 에 있어야 함:  ffmpeg -version
python -c "import torch; print(torch.cuda.is_available())"   # True 여야 함
```

Windows 는 `python3` 대신 `python`, 경로 구분자 `\` 사용. 아래는 전부
`psepipe_v3_seam` 폴더 안에서 실행.

## 1. ★ psegpu_full 검증 — 아직 아무도 못 한 것 (최우선)

작성자가 GPU 없는 환경에서 만든 코드라 "실행 검증 안 됨" 상태다.

```bash
python verify_full.py --quick        # 핵심 6클립 (클립 세트 보유 시)
python verify_full.py                # 27클립 전수
python verify_full.py --clip 아무위반클립.mp4   # 세트 없을 때
```

- ⚠️ `--quick`/전수는 `synth/`·`genre/`·`run3/` 27클립 세트를 기대하는데
  **그 세트는 리포에 없다** (영상 커밋 금지). 세트 생성기를 가진 팀원
  (psegpu 작성자) 로컬에 있으니 받아두거나, 없으면 `--clip` 으로 대체.
- **판정 기준은 스크립트가 출력한다: "악화 0 이 절대 조건."**
  - 통과 → psegpu_full 을 파이프라인 A 슬롯의 실행판으로 승격
  - 실패 → pselive3(CPU) 유지, 실패 클립을 이슈로 기록
- CPU ms vs GPU ms 속도 비교가 같이 나온다 → 발표 슬라이드 재료.

## 2. 실사 릴스 A vs D 재실행 + 비교 영상

CPU 컨테이너에는 릴스가 없어서 합성 클립으로만 돌렸다. 실사로 재현:

```bash
# 3파전의 실사판 (A / D_ste). D 열까지 자동으로 채워짐
python compare_ad.py 릴스1.mp4 릴스2.mp4 ... \
  --d-cmd "python -m blazebvd.cli correct {src} -o {dst} --stage ste --config ../../blazebvd-wt/blazebvd-training/configs/default.yaml" \
  --csv validation/ad_reels.csv

# D_full (신경망 전체, GPU) — CPU 에선 4초 클립에 18분이던 것
python -m blazebvd.cli correct 릴스1.mp4 -o 릴스1_Dfull.mp4 --stage full \
  --checkpoint ../../blazebvd-wt/blazebvd-training/runs/davis_blazebvd/tcm/best.pt \
  --device cuda --config ../../blazebvd-wt/blazebvd-training/configs/default.yaml

# 체인(A→D)은 반드시 재검출:  합성 04번에서 D가 A의 보정을 되돌려
# 패턴 위반이 재발했다 (three_way_synth.csv).  D 출력은 무조건:
python tier.py 릴스1_Dfull.mp4

# 비교 영상 (발표·설문용)
python validation/make_sbs.py compare_릴스1.mp4 \
  "ORIGINAL=릴스1.mp4" "A (ours)=_ad_work/릴스1_A.mp4" "D ste=_ad_work/릴스1_D.mp4"
```

**08-14 실사 2차 결과 반영** (`validation/ad_blazebvd_full.csv`, 팀 GPU 실측):
anime27·cera 는 A 승, **travis 는 D-full 승** — A 가 화면전환 축을 못 넘긴
클립을 D-full 이 통과시켰다 (단 헤일로는 21.7 로 A 의 4.5 보다 큼).
→ D 의 자리가 확정됨: 기본 경로가 아니라 **"A 가 실패한 클립의 2차 시도"**
슬롯. 파이프라인: A → 재검출 → (실패 시) D-full → 재검출. 남은 질문은
travis 에서 A→D-full 체인이 D-full 단독보다 헤일로를 줄이는가 — 3파전
하네스로 확인할 것.

## 3. D_full GPU 속도 실측

2번의 D_full 명령을 `time` 으로 재서 CPU 실측(180p 4초 ≈ 18분)과 비교.
GPU에서 몇 초대로 떨어지는지가 "D 를 오프라인 국소 청소부로 쓸 수 있는
최소 조건"이다. 이 수치도 `dfull_synth.csv` 옆에 기록할 것.

## 4. (다음 스텝) BlazeBVD 파인튜닝 — A 잔상 도메인

합성·CPU 실측의 결론: DAVIS 일반 플리커로 학습된 현재 가중치는 규격
통과도, A 잔상 청소도 못 한다(2전 2패, 헤일로 22~37 신규 생성). 살리는 길:

1. 깨끗한 실사 클립 수백 편 수집 (검출기 PASS 인 것)
2. `blazebvd-training/src/blazebvd/degradation.py` 에 **우리 A 가 남기는
   게인 아티팩트 시뮬레이션**(구간 게인 클램프 + 경계 헤일로)을 추가
3. (입력=아티팩트 입힌 클립, 정답=원본) 페어로 GFRM/LFRM 재학습
4. 재학습본을 2번 하네스로 재평가 — A 뒤 국소 청소부 슬롯 재도전

## 결과 회수

끝나면 다음 파일들을 커밋(영상 제외)하거나 채팅에 업로드:
`verify_full` 출력 로그, `validation/ad_reels.csv`, D_full 시간 기록.
받으면 종합 분석해서 기획서·발표 수치로 정리한다.
