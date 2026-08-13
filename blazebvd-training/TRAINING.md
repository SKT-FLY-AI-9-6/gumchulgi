# BlazeBVD 학습 가이드

## 1. 무엇을 학습하는가

STE는 학습 파라미터가 없는 결정론적 전처리입니다. 학습 대상은 그 뒤의 세 모듈입니다.

1. **GFRM**: 열화 프레임과 현재 수정본 STE의 `filtered_value`를 입력받아 clean frame을 복원합니다.
2. **LFRM**: 이전·현재·다음 프레임을 optical flow로 정렬해 국소 노출 영역의 텍스처를 보완합니다.
3. **TCM**: 양방향 recurrent transformer로 최종 시간 일관성을 학습합니다.

단계별 `best.pt`를 다음 단계가 상속하므로 순서는 반드시 GFRM -> LFRM -> TCM입니다.

## 2. 데이터와 split

권장 영상 데이터는 DAVIS 2017 TrainVal 480p입니다.

```powershell
python scripts/download_davis.py --output data
```

학습기는 `data/DAVIS/ImageSets/2017/train.txt`와 `val.txt`를 자동으로 찾아 공식 split을
사용합니다. 공식 split 파일이 없는 일반 폴더에서는 sequence 단위의 고정 train/validation
split을 생성합니다. 프레임 단위로 섞지 않으므로 같은 영상이 양쪽에 섞이지 않습니다.

데이터 폴더 형식은 다음과 같습니다.

```text
JPEGImages/480p/
  sequence-a/
    00000.jpg
    00001.jpg
  sequence-b/
    00000.jpg
```

`CleanVideoFolderDataset`의 길이는 sequence 수가 아니라 `--train-samples`입니다. 값이 0이면
train sequence당 16개 clip, validation sequence당 2개 clip을 매 epoch 생성합니다.

## 3. 합성 점멸

clean clip에서 다음 열화를 매번 새로 합성합니다.

- 논문의 공개 조건인 2~12프레임 공유 additive window
- 전역 밝기 및 색 변화
- 부드러운 국소 마스크 점멸
- 1~3프레임 빠른 교대 점멸
- 1~2프레임 impulse highlight/darkening
- 고채도 적색 교대 점멸

정확한 합성 분포는 논문에 공개되지 않았으므로 `configs/train.yaml`의 값은 명시적인
재구현 가정입니다. 실제 위험 영상은 clean target이 없으므로 주 학습 데이터가 아니라 최종
검증·미세조정 데이터로 분리해야 합니다.

## 4. 단계별 직접 실행

### GFRM

```powershell
blazebvd-train `
  --data data/DAVIS/JPEGImages/480p `
  --config configs/default.yaml `
  --training-config configs/train.yaml `
  --stage gfrm `
  --output runs/davis_blazebvd/gfrm `
  --epochs 40 `
  --batch-size 1 `
  --clip-length 12 `
  --crop-size 256 `
  --device cuda `
  --amp
```

### LFRM

```powershell
blazebvd-train `
  --data data/DAVIS/JPEGImages/480p `
  --config configs/default.yaml `
  --training-config configs/train.yaml `
  --stage lfrm `
  --init-checkpoint runs/davis_blazebvd/gfrm/best.pt `
  --output runs/davis_blazebvd/lfrm `
  --epochs 20 `
  --batch-size 1 `
  --clip-length 12 `
  --crop-size 256 `
  --flow raft_small `
  --device cuda `
  --amp
```

LFRM 학습 때만 합성 artifact의 정답 mask를 exposure/singular 보조 mask로 사용합니다.
기본 `--lfrm-force-all`은 모든 interior frame에서 LFRM을 호출해 singular frame이 0개인
배치에서도 gradient가 끊기지 않게 합니다. 실제 추론에서는 이 oracle mask를 사용하지 않고
STE 판정만 사용합니다.

### TCM

```powershell
blazebvd-train `
  --data data/DAVIS/JPEGImages/480p `
  --config configs/default.yaml `
  --training-config configs/train.yaml `
  --stage tcm `
  --init-checkpoint runs/davis_blazebvd/lfrm/best.pt `
  --output runs/davis_blazebvd/tcm `
  --epochs 30 `
  --batch-size 1 `
  --clip-length 12 `
  --crop-size 256 `
  --flow raft_small `
  --device cuda `
  --amp `
  --perceptual `
  --adversarial `
  --long-warp
```

TCM은 추론과 동일하게 실제 STE singular/exposure gating을 사용한 고정 GFRM+LFRM 출력을
입력받습니다. `--perceptual`의 첫 실행은 torchvision VGG16 가중치가 필요합니다.

## 5. 손실함수

- GFRM: clean target MSE
- LFRM: clean target artifact-weighted L1
- TCM: reconstruction + perceptual + 0.01 adversarial + 0.1 adaptive warp
- 모든 단계: temporal-excess + STE-rebound 정규화

`temporal-excess`는 출력의 V-channel 프레임 차이가 clean target과 STE reference 모두보다
새롭게 커지는 부분만 벌점으로 줍니다. `STE-rebound`는 STE가 실제로 낮춘 픽셀에서 출력이
STE/clean 기준보다 과도하게 밝아지는 부분을 벌점으로 줍니다. 가중치는
`configs/train.yaml`에서 조정합니다.

## 6. 로그·체크포인트·재개

각 stage 폴더에 다음 파일이 생성됩니다.

- `best.pt`: validation loss가 가장 낮은 전체 checkpoint
- `last.pt`: 마지막 epoch, optimizer/scaler/global step 포함
- `metrics.csv`, `metrics.jsonl`: train/validation 지표
- `last_metrics.json`: 최근 epoch 요약
- `run_config.json`: 모델·합성 설정·실제 sequence split
- `tensorboard/`: `--tensorboard` 사용 시 생성

중단된 동일 stage를 재개할 때는 총 목표 epoch를 지정합니다.

```powershell
blazebvd-train `
  --data data/DAVIS/JPEGImages/480p `
  --config configs/default.yaml `
  --training-config configs/train.yaml `
  --stage tcm `
  --resume runs/davis_blazebvd/tcm/last.pt `
  --output runs/davis_blazebvd/tcm `
  --epochs 40 `
  --device cuda `
  --flow raft_small `
  --amp `
  --perceptual `
  --adversarial `
  --long-warp
```

LR은 저장된 global step과 새 `--epochs`를 기준으로 warmup+cosine schedule을 다시 계산하므로
목표 epoch를 늘려도 이전 scheduler의 종료 길이에 고정되지 않습니다.

## 7. 평가 시 주의사항

smoke loss나 synthetic validation PSNR만으로 광과민 안전성을 주장할 수 없습니다. 최소한
다음 세 축을 별도로 평가해야 합니다.

1. clean/synthetic: PSNR, SSIM, LPIPS, temporal warping error
2. 실제 콘서트·플래시 영상: 색·얼굴·텍스처 보존과 장면 전환 오작동
3. 최종 출력: 프로젝트 PSE 검출기의 flash/red-flash 위반 수를 입력·STE·최종 출력 간 비교

신경망 checkpoint를 바꾸거나 loss weight를 조정할 때마다 최종 PSE 재검사를 반복해야 합니다.
