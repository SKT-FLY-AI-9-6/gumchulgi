# 광과민성 위험 완화 + 재검증 파이프라인

`Kim&Moon` 브랜치. 다른 브랜치가 **"위험한가"** 를 답한다면, 이 브랜치는 그다음
질문을 맡는다 — **"고치면 실제로 안전해지는가."**

Blind Video Deflickering by Neural Filtering with a Flawed Atlas (CVPR 2023) 를
전처리로 돌리고, 그 결과를 우리 검출기로 다시 재서 **완화 전후를 같은 조건으로
비교**한다.

## 왜 재검증이 필요한가

디플리커를 돌리면 BT.1702 판정은 거의 항상 좋아진다. 문제는 그게 진짜 개선인지
아닌지를 판정만 봐서는 구분할 수 없다는 점이다.

BT.1702 판정은 **인접 프레임 간 변화량**을 본다. 영상을 60fps 로 보간하면 같은
밝기 변화가 두 프레임에 나뉘어 프레임당 변화량이 절반이 된다. 눈에 보이는 점멸은
그대로인데 판정만 통과한다. 전형적인 지표 게이밍이다.

그래서 이 파이프라인은 두 축을 **항상 같이** 본다.

| 축 | 도구 | 보는 것 |
|---|---|---|
| 판정 | `pse_bt1702.py` / `pse_analyze.py` | 규격 위반 구간(초) |
| 에너지 | `pse_spectrum.py` | 3~30Hz · 10~20Hz 대역 에너지 (프레임률 무관) |

**판정만 좋아지고 대역 에너지가 그대로면 폐기 대상이다.** `verify` 명령이 두
숫자를 한 표에 붙여 내는 이유가 이것이다.

프레임률 비교도 같은 함정이다. 저장소는 입력을 10fps 로 떨구므로 원본(24/30fps)과
직접 비교하면 "프레임을 버린 것만으로 줄어든 몫"이 신경망 성과로 잡힌다. 그래서
BEFORE 를 결과와 같은 프레임률로 맞춰 두고 비교한다 (`ensure_before10`).

---

## 빠른 시작

```bash
pip install torch opencv-python numpy easydict tqdm tensorboard imageio-ffmpeg scikit-image
```

`numpy<2` 여야 한다 (torch 2.1 제약). ffmpeg 은 없으면 imageio-ffmpeg 번들을
`bin/ffmpeg.exe` 로 심고 PATH 앞에 붙인다 — 따로 설치하지 않아도 된다.

**`setup` 은 돌리지 않아도 된다.** 디플리커 저장소 코드와 사전학습 가중치가
이 브랜치에 같이 들어 있다 (`All-In-One-Deflicker/`, 약 65MB). 클론하면 바로
`run` 부터 할 수 있다. 자세한 건 [업스트림 저장소](#업스트림-저장소--알아서-받지-않고-같이-올린-이유) 항목.

```bash
python pse_deflicker.py check          # 환경 점검 (GPU 커널 호환까지)
python pse_deflicker.py corpus         # 합성 클립으로 검출기 자체 검증
python pse_deflicker.py list           # 대상 영상 목록/실행 상태
python pse_deflicker.py run game       # 파이프라인 1편  (--dry 로 예상시간만)
python pse_deflicker.py compare game   # 좌우 비교본 생성
python pse_deflicker.py verify         # 전 영상 수치 검증 표 → verify_report.json
```

CPU 로는 사실상 못 돌린다. 소요는 대략 **프레임당 12초** — 40초 30fps 영상이면
약 4시간이다. 반드시 `--dry` 로 먼저 확인할 것.

긴 영상이 마지막 단계에서 `the number of style frames is different from the
number of content frames` 로 죽으면 stage1 프레임 상한 문제다:

```bash
python pse_deflicker.py frames 500     # 상한을 올린다 (시간·VRAM 이 선형 증가)
```

---

## 파일 지도

### `pse_deflicker.py` — 통합 실행기

노트북(`PSE_BlindDeflicker_VSCode.ipynb`)을 하나로 합치면서 노트북에서 났던
문제를 구조적으로 제거했다.

- **셀 순서 의존 없음** — 모든 단계가 필요한 것을 스스로 준비한다
- **전역 변수 오염 없음** — 경로를 영상 이름 하나에서 `paths_for()` 로 유도
- **파괴적 기본값 없음** — 저장소 재클론은 `--force` 를 명시해야만 일어나고,
  `results/` 에 결과가 있으면 한 번 더 물어본다
- **ffmpeg PATH 문제 해결** — 저장소 내부 코드가 셸에서 부르는 `ffmpeg` 를
  `bin/` 에 심어 주입 (번들 파일명이 `ffmpeg-win-x86_64-vN.exe` 라 그대로는 안 불린다)
- **한글 로그 안 깨짐** — 자식 프로세스 출력을 로케일 인코딩으로 읽는다

### `final_detectors/` — 재검증에 쓰는 검출기

| 파일 | 역할 |
|---|---|
| `pse_bt1702.py` | 규격 준수 단일 판정기. 플래시·색·패턴·지속·컷 6조항 |
| `pse_analyze.py` | 4채널(LUM/RED/RG/BY). 등휘도 색 점멸까지 — **규격 밖 추가 위험** |
| `pse_spectrum.py` | 3~30Hz 대역 에너지. 지표 게이밍 검증용 |
| `pse_cut.py` | 빠른 컷 검출. 오탐 방지 4겹 (모션을 컷으로 안 센다) |
| `pse_pattern.py` | 줄무늬·격자. 2D FFT + Gabor |
| `bt1702_detector.py` | v0.1 원조. 알려진 결함 2개 — 회귀 비교용으로만 |
| `make_*clips.py` | 정답을 아는 합성 검증 클립 생성 |

상세 이력과 검증 수치는 `final_detectors/README.txt` 에 있다. 합성 클립 24편
(점멸·색·줄무늬 11 + 컷·모션 10 + 시퀀스 3) 기준 오탐·미탐 0.

`검출기_명세서.pdf` — 검출기 명세서.

---

## 업스트림 저장소 — 알아서 받지 않고 같이 올린 이유

`All-In-One-Deflicker/` 는 [ChenyangLEI/All-In-One-Deflicker](https://github.com/ChenyangLEI/All-In-One-Deflicker)
의 코드와 가중치다. **Apache License 2.0** 이며 원본 `LICENSE` 를 그대로 동봉했다.

기준 커밋: **`214f90cd40df3885760cd6d4c09aa18dfdc03db2`**

`setup` 으로 받아도 되는데 굳이 커밋한 이유는, **원본을 그대로 받으면 우리와 다른
숫자가 나오기 때문이다.** 로컬 수정 2건이 들어가 있다 — 전체 diff 는
`All-In-One-Deflicker/UPSTREAM_CHANGES.patch` 에 있고, `src/` 에는 **이미 적용된
상태**로 들어 있다.

### ① 출력 프레임률 하드코딩 (`src/neural_filter_and_refinement.py`)

원본은 결과 mp4 를 쓸 때 출력 프레임률을 `-r 12` 로 박아 놨다.

```python
# 원본 — 입력 fps 가 뭐든 출력은 항상 12fps
cmd = "ffmpeg -y -r %s -i %s -crf 25 -r 12 -qscale 4 %s" % (str(opts.fps), ...)

# 수정 — 입력 fps 를 그대로 유지
cmd = "ffmpeg -y -r %s -i %s -crf 25 -r %s -qscale 4 %s" % (str(opts.fps), ..., str(opts.fps), ...)
```

**이 프로젝트에서는 치명적이다.** `NATIVE_FPS = True` 로 30fps 를 넣어도 결과물이
12fps 로 나오면 BEFORE 와 AFTER 의 프레임률이 어긋나고, 위에서 말한 "프레임을 버린
몫이 신경망 성과로 잡히는" 상황이 그대로 재현된다. 판정 수치를 믿으려면 이 수정이
반드시 들어가 있어야 한다.

### ② 프레임 상한 (`src/config/config_flow_100.json`)

`maximum_number_of_frames` 를 200 → **400** 으로 올렸다. `pse_deflicker.py frames`
명령이 한 일이다. 안 올리면 긴 영상이 마지막 단계에서
`the number of style frames is different from the number of content frames` 로 죽는다.

패치 diff 가 90줄인 건 그 명령이 `json.dumps(indent=2)` 로 다시 써서 들여쓰기가
4칸→2칸으로 전부 바뀌었기 때문이고, 실제 변경은 이 한 줄뿐이다.

### 그 밖에 손댄 것

- `.gitignore` → `.gitignore.upstream` 으로 이름 변경. 원본 2~3번째 줄이 `results/`
  와 `pretrained_weights/` 를 막는데, 하위 `.gitignore` 가 루트보다 우선하므로
  이름을 그대로 두면 가중치가 커밋에서 빠진다. 업스트림에 다시 기여할 일이 있으면
  이름을 되돌릴 것.
- `.git/`, `demo.gif`(18.5MB), `data/`, `results/` 는 뺐다.

---

## 옮겨 심을 때 반드시 고칠 것

`pse_deflicker.py` 상단 §0 은 **제작자 로컬 절대경로로 하드코딩되어 있다.**

```python
ROOT  = Path(r"C:\Users\PJ07\Desktop\deflicker\최종!!")
REPO  = ROOT / "All-In-One-Deflicker"
TOOLS = ROOT / "tools"     # 검출기(psecore.py 또는 검출기.py), pse_spectrum.py
GENRE = ROOT / "genre"     # 합성 검증 코퍼스
```

- `ROOT` 를 자기 경로로 바꿀 것.
- `TOOLS` 는 이 저장소의 `final_detectors/` 와 **다른 폴더를 가리킨다.** 검출기를
  `tools/` 에 두거나 `TOOLS = ROOT / "final_detectors"` 로 바꿔야 `corpus`·`verify`
  가 돈다. 찾는 이름은 `psecore.py`, `검출기.py`, `psecore_v2.py`, `detector.py` 순.
- `VIDEOS` 딕셔너리의 `keyword` 는 원본 파일명에 들어가는 단어다. 자기 영상에
  맞게 다시 쓸 것.
- `NATIVE_FPS = True` 면 원본 프레임률을 그대로 쓰고 `ensure_before10` 은
  저장소 입력을 BEFORE 로 반환한다. 10fps 고정으로 비교하려면 `False`.

## 커밋하지 않은 것

팀 공통 규칙(`main` 의 README)대로 **영상은 올리지 않는다.**

- `*.mp4` — 입력 원본과 `프레임 안줄이고 실행/`·`10fps로 줄이고 실행/` 의 처리
  결과·좌우 비교본. 로컬에만 있다
- `All-In-One-Deflicker/data/` — 추출 프레임과 옵티컬 플로우 `.npy`. **약 27GB**
- `All-In-One-Deflicker/results/` — 학습 중간물과 결과 png. **약 20GB**
- `bin/` — 심어둔 ffmpeg 바이너리

`data/`·`results/` 가 저 크기인 건 RAFT 플로우가 2채널 float32 무압축이기 때문이다.
원본 해상도(`scale: None`)로 돌린 pinkvenom 은 **프레임당 12.6MB** 씩 쌓인다.
`VIDEOS` 에서 `scale=640:-2` 로 줄인 cera_khin·anyma 는 1/4 수준이다.

```
pinkvenom   7.47 GB   scale=None      cera_khin   1.91 GB   scale=640:-2
anime       5.84 GB   scale=None      anyma       1.85 GB   scale=-2:640
fein        5.54 GB   scale=None
game        3.90 GB   scale=None
```

디스크가 부족하면 `data/test/*_flow/` 부터 지우면 된다. 다만 재실행 시 다시 계산해야
하는 비싼 파일이다 (프레임당 12초의 상당 부분).

`verify` 가 만드는 `verify_report.json` 은 수십 KB 이고 숫자의 근거이므로
**커밋 대상이다.**
