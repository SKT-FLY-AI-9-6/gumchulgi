# ai_poc — AI 이식 PoC 실측 코드 (2026-08-26)

`docs/AI-이식-로드맵.md` 권장순서 1·2·3 의 실행 코드와 실측 CSV.
결과 해석은 `docs/AI-이식-PoC-실측.md` 에 있다. 여기 있는 건 **재현 수단**이다.

## 파일

| 파일 | 무엇 |
|---|---|
| `tog24_probe.py` | TOG24(compphoto/Intrinsic v2) 키프레임 광원층 추출·몽타주. 설치/가중치 우회법이 파일 상단 주석에 있다 |
| `tog24_residual.py` | R+ vs R− vs \|R\| vs 단순 휘도 의 IoU 비교 (기각 근거) |
| `run_cuts.py` | TransNetV2 vs NCC vs 심판(pse_cut) 컷 검출 비교 + 디졸브/하드컷 합성 |
| `leak_probe.py` | σ32 누수 판별자 — 점멸 마스크 연결성분 등가지름 + tex 비율 분포 |
| `bg_matrix.py` | tex 클램프 가설 시험 (배경 밝기만 바꾼 대조) |
| `gen_clips.py` | 소형/대형 광원 점멸 합성 클립 생성 |
| `run_vmaf.py` | base vs strong VMAF + 판정 |
| `*.csv` | 위 실측 결과 |

## GPU 노트북에서 할 일 (여기서 못 끝낸 것)

**1. σ32 누수 판별자 검증 — 이게 제일 중요하다.**
로컬에서는 누수 양성 표본을 합성으로 못 만들었다(두 가설 모두 기각).
실사 누수 5편이 있는 노트북에서만 답이 나온다:

```
python leak_probe.py --clips 실사폴더/{CIHun1gx7zU,PFSDW2g3D8o,UoHK74aS9sY,Y76O5wY7EcM,xDdAHEUQ2zA}.mp4 \
                     --clips 실사폴더/strong채택_표본20편.mp4 --csv leak_real.csv
```
보는 것: 누수 5편과 strong 성공군의 `med_diam_px` / `restorable_frac` /
`n_regions` 분포가 갈리는가. 갈리면 사전 분기 규칙이 서고, 안 갈리면
REGRESS_0820 5절처럼 **기각으로 확정**하고 사후 폴백을 유지한다.

**2. TOG24 재확인 (선택).** `python tog24_probe.py --device cuda --res 1024`
— CPU 7.6s/frame 이 GPU 에서 논문값(~1s)에 맞는지, 고해상에서 R+ 가
나아지는지. 현재 결론(기각)을 뒤집으려면 이게 필요하다.

**3. VMAF 열.** `regress_ab.py --vmaf` 로 209편 회귀에 열 2개 추가.
절대값이 아니라 **base 대비 Δ** 로만 읽는다.

## 환경 메모 (샌드박스에서 막혔던 것)

- `pip install <github zip>` → 프록시 403. `git clone` 후 `pip install --no-deps .` 로 우회.
- `torch.hub.load_state_dict_from_url` → 400. GitHub **release** 자산은 통과하므로 curl 로 선다운로드.
- `dl.fbaipublicfiles.com`(WSL-Images 사전학습) 차단 → `tog24_probe.py` 의
  몽키패치로 회피(어차피 release 가중치가 백본을 덮어쓴다).
- TransNetV2 저장소 가중치는 **git-lfs** 라 익명 레인에서 못 받는다 →
  PyPI `transnetv2-pytorch` (가중치 번들) 사용.
- 이 빌드의 ffmpeg 에는 `drawtext` 필터가 없다 → 라벨은 cv2 로 각인.
