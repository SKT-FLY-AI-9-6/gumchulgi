# SoftReel — 광과민성(PSE) 보호 숏폼 플랫폼 MVP (`platform-mvp_cpu`)

영상을 올리면 서버가 광과민성 발작 유발 자극(플래시·적색·패턴·컷)을 검출하고
보정본을 만든다. 앱은 세로 스와이프 피드에서 원본/보정본을 재생하며,
사용자의 하루 위험 노출량을 대시보드로 보여준다.

```
app/               Flutter 앱 (Android/iOS/web)
server/app/        FastAPI — 인증, 업로드, 피드, 스트리밍, 대시보드
server/worker/     큐 워커 — ffmpeg 정규화 → 검출 → 보정 사다리
psepipe_v3_seam/   검출기·필터 (pse_bt1702, pselive3, psegpu_full)
docs/              설계 스펙, 실행 가이드
```

## 빠른 시작 (노트북 = 서버, 폰 = 클라이언트)

### 준비 (1회)
- Python 3.10+, `ffmpeg`/`ffprobe` PATH 등록, Flutter SDK
- CUDA torch가 있으면 워커가 자동으로 GPU 필터(`psegpu_full`)를 쓰고, 없으면 CPU(`pselive3`)로 떨어진다 — 동작은 같고 느릴 뿐.

```powershell
pip install -r server\requirements.txt
copy server\.env.example server\.env      # JWT_SECRET 을 긴 임의 문자열로 변경
```

폰에서 접속하려면 방화벽 8000 포트를 열어야 한다 (관리자 PowerShell):

```powershell
netsh advfirewall firewall add rule name="gumchulgi-api" dir=in action=allow protocol=TCP localport=8000
```

### 서버 실행

한 번에 (API + 워커, `server\.env` 로드, 데이터는 `data\`):

```powershell
powershell -ExecutionPolicy Bypass -File run_server.ps1
```

또는 터미널 2개로 따로 (`scripts\run_api.ps1`, `scripts\run_worker.ps1`).
`http://localhost:8000/health` 가 `{"ok":true}` 면 준비 완료.

### 앱 빌드 → 폰 설치

서버 주소가 APK 안에 박히므로 노트북 IP(`ipconfig` → IPv4)를 넣어 빌드한다.
폰과 노트북은 **같은 와이파이**여야 하고, IP가 바뀌면 다시 빌드해야 한다.

```powershell
cd app
flutter pub get
flutter build apk --dart-define=API_BASE=http://192.168.0.7:8000
```

`app\build\app\outputs\flutter-apk\app-release.apk` 를 폰에 복사해 설치.
에뮬레이터는 `--dart-define` 없이 빌드하면 기본값 `http://10.0.2.2:8000` 으로 호스트에 붙는다.

### 사용 흐름
1. 회원가입 → 업로드 탭에서 갤러리 영상 선택(200MB·3분 제한) → 업로드
2. 워커가 검출·보정을 끝내면 홈 피드와 내 페이지에 표시 (홈 아이콘 재탭 / 당겨서 새로고침)
3. 화면 탭 = 일시정지/재생. 우상단 필터 아이콘 → **필터 기능 켜기** 토글로 보던 자리에서 원본↔보정본 전환
4. 위험 영상 원본 시청이 하루 예산의 80%를 넘고 필터가 꺼져 있으면 경고 배너 → 대시보드에서 노출 추이 확인

## 데이터 위치
`data\db.sqlite3` (계정·영상 메타·시청 기록) + `data\media\{id}\` (원본/보정본/썸네일/리포트).
서버를 꺼도 유지되며, 초기화하려면 `data\` 폴더를 지운다. `.env` 와 `data\` 는 커밋하지 않는다.

## 테스트
```powershell
cd server; python -m pytest tests -q
cd app;    flutter analyze; flutter test
```

## 더 읽기
- `docs/superpowers/specs/2026-08-20-platform-mvp-design.md` — MVP 설계 스펙(노출 규칙, API)
- `docs/노트북-서버-실행.md` — GPU 노트북 실행 상세
- `docs/아키텍처-개요.md`, `docs/검출기-통합.md` — 구조와 검출기 통합 경위
- `server/README.md` — Docker / EC2 배포(CPU 경로)

## 브랜치 규칙 (저장소 공통)
`main` 은 비워 둔다. 작업은 자기 이름/기능 브랜치에서 하고 push 한다.
