# 실행 환경 준비

## 서버 설정
- **서버 실행:** `cd server` 후 venv에서 다음 명령 실행:
  ```bash
  uvicorn app.main:app --host 0.0.0.0 --port 8000
  ```
- **워커 실행 (별도 터미널):**
  ```bash
  python -m worker.main
  ```
- **클라우드 배포 시:** EC2에서 `docker compose` 사용
- **배너 시연 빠르게:** `.env`의 `DAILY_BUDGET_S=60`으로 낮춰서 재기동

## APK 빌드 및 설치
- **APK 위치:** `C:/src/gcg/app/build/app/outputs/flutter-apk/app-debug.apk` (ASCII worktree에서 빌드됨)
- **실기기 설치:**
  1. USB 디버깅 활성화
  2. `adb install` 명령 또는 파일 복사로 설치

## 앱 API 주소 설정
- **에뮬레이터 (기본값):** `10.0.2.2:8000`
- **실기기 (필수):** PC와 같은 와이파이 연결 후 PC의 IP 주소로 접속 필요
  - 빌드 시 `--dart-define=API_BASE=http://<PC-IP>:8000` 필수
  
### 실기기용 재빌드 명령
```bash
cd /c/src/gcg/app && export TMP='C:\src\tmp' TEMP='C:\src\tmp' PUB_CACHE='C:\src\pub-cache' GRADLE_USER_HOME='C:\src\gradle-home' JAVA_HOME='C:\Program Files\Microsoft\jdk-17.0.20.8-hotspot' && C:/src/flutter/bin/flutter.bat build apk --debug --dart-define=API_BASE=http://<PC-IP>:8000
```

## 테스트 클립 준비
1. 테스트 클립 생성:
   ```bash
   python legacy_detectors/make_testclips.py <outdir>
   ```
   → `01_flash_5hz.mkv` 생성

2. MP4로 변환:
   ```bash
   ffmpeg -i 01_flash_5hz.mkv -c:v libx264 -pix_fmt yuv420p 01_flash.mp4
   ```

3. 폰 갤러리에 저장

---

# E2E 체크리스트 (실기기, 서버 compose 기동)
서버 준비: DAILY_BUDGET_S=60 으로 낮춰 재기동. make_testclips 01 클립을 mp4 로 변환해 폰에 저장.
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
