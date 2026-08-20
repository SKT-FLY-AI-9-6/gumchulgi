# E2E 체크리스트 (실기기, 노트북 네이티브 서버)

서버 준비: `docs/노트북-서버-실행.md` 대로 api+워커 기동.
배너 확인용으로 `DAILY_BUDGET_S=60` 환경변수로 낮춰 재기동.
`legacy_detectors/make_testclips.py` 01 클립을 mp4 로 변환해 폰에 저장.

백엔드 스모크(2026-08-20, RTX 4090 노트북)는 API 로 통과 확인:
가입 → 01_flash mp4 업로드 → 워커 처리 ~15초 → risk=corrected,
filter_level=strong, n_flash=1 → 피드 variant=filtered → Range 206 →
시청 이벤트 {today_percent, status} 응답.

- [ ] 가입 → 로그인 → 앱 재시작 시 자동 로그인
- [ ] 01_flash(위반) 영상 업로드 → 내 페이지 "처리 중" → 수 분 내 "게시됨"
- [ ] 안전 영상 업로드 → risk 뱃지 없음, 피드에서 원본 재생
- [ ] 필터 ON: 위반 영상이 "보호 필터 적용됨"으로 재생 (점멸 억제 확인)
- [ ] 필터 OFF: 같은 영상 "⚠ 광 자극 원본" + 시청 시 대시보드 수치 상승
- [ ] 반복 시청으로 80% 초과 → 경고 배너 → [필터 ON] → 배너 사라지고 보정본 재생
- [ ] 자동 스킵 ON → 위험 영상이 피드에서 사라짐
- [ ] 대시보드: 오늘 횟수·시간·%·곡선·주간·자극 유형 수치가 시청 내역과 일치
- [ ] 좋아요 토글·조회수 증가 확인
- [ ] 200MB/3분 초과·비영상 파일 업로드 → 오류 안내
- [ ] 기내모드에서 피드 → "다시 시도" 동작

---

## 부록 — 개발 PC(한글 경로) 기준 준비 명령

### 서버 (Docker 불가 시 venv 네이티브)
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000   # server/ 에서
python -m worker.main                              # 별도 터미널
```
클라우드 배포 시 EC2에서 `docker compose up -d --build`.

### APK 빌드·설치 (반드시 ASCII worktree에서)
- APK 위치: `C:/src/gcg/app/build/app/outputs/flutter-apk/app-debug.apk`
- 실기기 설치: USB 디버깅 켠 후 `adb install` 또는 파일 복사.
- 실기기는 PC와 같은 와이파이에서 PC IP 로 접속해야 함 — 빌드 시
  `--dart-define=API_BASE=http://<PC-IP>:8000` 필수 (기본값 10.0.2.2 는 에뮬레이터용).

실기기용 재빌드:
```bash
cd /c/src/gcg/app && export TMP='C:\src\tmp' TEMP='C:\src\tmp' PUB_CACHE='C:\src\pub-cache' GRADLE_USER_HOME='C:\src\gradle-home' JAVA_HOME='C:\Program Files\Microsoft\jdk-17.0.20.8-hotspot' && C:/src/flutter/bin/flutter.bat build apk --debug --dart-define=API_BASE=http://<PC-IP>:8000
```

### 테스트 클립 준비
```bash
python legacy_detectors/make_testclips.py <outdir>
ffmpeg -i <outdir>/01_flash_5hz.mkv -c:v libx264 -pix_fmt yuv420p 01_flash.mp4
```
변환한 `01_flash.mp4` 를 폰 갤러리에 저장.
