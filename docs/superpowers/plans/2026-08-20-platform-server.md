# 플랫폼 백엔드 서버 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 업로드 → PSE 검출·보정 → 피드 서빙 → 광 노출 대시보드까지 실동작하는 FastAPI 백엔드 + 워커.

**Architecture:** FastAPI(api)와 폴링 워커(worker)가 같은 코드베이스·같은 Docker 이미지에서 프로세스만 분리되어 SQLite(WAL)와 `/data` 볼륨을 공유한다. 워커는 `psepipe_v3_seam`의 pse_bt1702(검출)·pselive3 STRONG(보정)을 직접 import 한다.

**Tech Stack:** Python 3.12+, FastAPI, uvicorn, 표준 sqlite3(ORM 없음), bcrypt, PyJWT, OpenCV(headless)+numpy, ffmpeg(자막·인코딩), pytest+httpx, Docker Compose.

**스펙:** `docs/superpowers/specs/2026-08-20-platform-mvp-design.md`

## Global Constraints

- 작업 브랜치 `platform-mvp`, 코드는 전부 `server/` 아래 (파이프라인 `psepipe_v3_seam/`은 수정 금지, import 만).
- Python 표준 sqlite3 사용, ORM 금지. DB 파일 `{DATA_DIR}/db.sqlite3`, WAL 모드.
- 업로드 상한: 200MB · 180초. 표준화: H.264/AAC mp4, faststart, 가로폭 720 상한.
- 노출 규칙 (risk × 설정 → variant): safe→original 항상 / auto_skip ON 이면 risk≠safe 전부 제외 / filter_on ON: corrected→filtered, uncorrected→제외 / filter_on OFF: original.
- 상태 라벨: percent<50 `good`, 50≤percent<80 `caution`, ≥80 `warning`. 일일 노출 예산 기본 300초(`DAILY_BUDGET_S`).
- "오늘" = `date(created_at,'localtime') = date('now','localtime')`, 컨테이너 TZ=Asia/Seoul.
- 자극 축 매핑 (violation_segments의 rule 문자열 prefix): 플래시→flash, 적색→red, 패턴→pattern, 화면전환→cut, 5초지속→flash. 그 외 무시.
- 파이프라인 모듈 인터페이스 (변경 금지, 이대로 사용):
  - `pse_bt1702.analyze(path) -> dict` — 키: `compliant`(bool), `failed_rules`(list[str]), `violation_segments`(list[{start_s,end_s,rule}]), `duration_s`, `fps`, `frames`
  - `pselive3.Cfg.strong() -> Cfg`, `pselive3.LiveFilter3(fps, (ah,aw), cfg)`, `.push(bgr, bgr_small) -> bgr` (보정된 풀해상도 프레임)
  - `pselive3.run()`은 전 프레임을 메모리에 버퍼링하므로 **워커에서 사용 금지** — Task 7 의 스트리밍 변형을 쓴다.
- 테스트는 `server/` 디렉토리에서 `python -m pytest tests/ -v` 로 실행. conftest 가 `psepipe_v3_seam`을 sys.path 에 추가한다.
- 커밋 메시지는 저장소 관례대로 한국어 요약 한 줄.

## API 계약 (Flutter 계획과 공유 — 두 계획 모두에 동일하게 기재)

```
POST /auth/signup  {email, password, nickname}      → 201 {token, user:{id,email,nickname}} / 409 이메일 중복
POST /auth/login   {email, password}                → 200 {token, user} / 401
GET  /me                                            → {id, email, nickname}
GET  /me/settings                                   → {filter_on: bool, auto_skip: bool}
PUT  /me/settings  {filter_on, auto_skip}           → 200 동일 바디
GET  /me/videos                                     → {videos:[{id,title,status,risk,thumb_url,duration_s,view_count,like_count,created_at}]}
POST /videos       multipart(file, title)           → 202 {video_id} / 413 크기 / 422 형식·길이
GET  /feed?cursor=<id>&limit=10                     → {videos:[FeedVideo], next_cursor: int|null}
     FeedVideo = {id, title, uploader_nickname, risk, variant, stream_url, thumb_url,
                  duration_s, like_count, view_count, liked_by_me, stimulus:{flash,red,pattern,cut}}
GET  /videos/{id}/stream?variant=original|filtered  → 200/206 video/mp4 (Range 지원)
GET  /videos/{id}/thumb                             → 200 image/jpeg
POST /videos/{id}/like                              → {like_count, liked: true}
DELETE /videos/{id}/like                            → {like_count, liked: false}
POST /videos/{id}/events {watched_s: float, variant}→ {today_percent: float, status: "good"|"caution"|"warning"}
GET  /dashboard/today  → {risky_views, exposure_s, percent, status, budget_s,
                          stimulus:{flash,red,pattern,cut}, curve:[{hour:int, percent:float}]}
GET  /dashboard/weekly → {days:[{date:"YYYY-MM-DD", risky_views:int}], avg: float}
```

인증: `Authorization: Bearer <JWT>` — /auth/* 외 전부 필수 (stream·thumb 포함).

## 파일 구조

```
server/
  requirements.txt  requirements-dev.txt  .env.example  Dockerfile
  app/
    __init__.py  config.py  db.py  schema.sql  main.py
    auth.py      # bcrypt·JWT·current_user 의존성 + /auth/*, /me
    users.py     # /me/settings, /me/videos
    videos.py    # 업로드·스트리밍(Range)·좋아요·이벤트
    feed.py      # /feed + pick_variant()
    dashboard.py # 노출 계산 + /dashboard/*
    storage.py   # /data 경로 규약
  worker/
    __init__.py  main.py       # 폴링 루프·claim/requeue
    pipeline.py                # process_video: 정규화→검출→보정→재판정→확정
    detect.py                  # pse_bt1702 래퍼
    filter_stream.py           # LiveFilter3 스트리밍 인코더 (O(1) 메모리)
    ffmpeg.py                  # probe/normalize/thumbnail
  tests/
    conftest.py  test_db.py  test_auth.py  test_settings.py  test_upload.py
    test_ffmpeg.py  test_detect.py  test_filter_stream.py  test_worker.py
    test_feed.py  test_stream_events.py  test_dashboard.py
docker-compose.yml   # 저장소 루트 (빌드 컨텍스트가 psepipe_v3_seam 포함해야 함)
```

---

### Task 1: 서버 뼈대 — 설정·DB 모듈·헬스체크

**Files:**
- Create: `server/requirements.txt`, `server/requirements-dev.txt`, `server/.env.example`
- Create: `server/app/__init__.py`, `server/app/config.py`, `server/app/schema.sql`, `server/app/db.py`, `server/app/main.py`
- Test: `server/tests/conftest.py`, `server/tests/test_db.py`

**Interfaces:**
- Produces: `config.settings` (DATA_DIR:Path, JWT_SECRET:str, DAILY_BUDGET_S:int, MAX_UPLOAD_MB:int, MAX_DURATION_S:int, TOKEN_DAYS:int) / `db.connect(db_path=None) -> sqlite3.Connection` (WAL·Row·스키마 적용) / `db.get_db()` FastAPI 의존성 / `main.app` FastAPI 인스턴스, `GET /health → {"ok": true}`
- Consumes: 없음 (첫 태스크)

- [ ] **Step 1: 의존성·설정 파일 작성**

`server/requirements.txt`:
```
fastapi>=0.115
uvicorn[standard]>=0.30
python-multipart>=0.0.9
PyJWT>=2.8
bcrypt>=4.1
numpy>=1.26
opencv-python-headless>=4.10
```

`server/requirements-dev.txt`:
```
-r requirements.txt
pytest>=8
httpx>=0.27
```

`server/.env.example`:
```
JWT_SECRET=change-me
DATA_DIR=./data
DAILY_BUDGET_S=300
MAX_UPLOAD_MB=200
MAX_DURATION_S=180
```

`server/app/config.py`:
```python
import os
from pathlib import Path


class Settings:
    def __init__(self):
        self.DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
        self.JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret")
        self.DAILY_BUDGET_S = int(os.environ.get("DAILY_BUDGET_S", "300"))
        self.MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "200"))
        self.MAX_DURATION_S = int(os.environ.get("MAX_DURATION_S", "180"))
        self.TOKEN_DAYS = int(os.environ.get("TOKEN_DAYS", "30"))


settings = Settings()
```

- [ ] **Step 2: 실패하는 DB 테스트 작성**

`server/tests/conftest.py`:
```python
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "server"))
sys.path.insert(0, str(REPO / "psepipe_v3_seam"))
```

`server/tests/test_db.py`:
```python
from app import db


def test_connect_applies_schema_and_wal(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite3")
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"users", "user_settings", "videos", "likes",
            "watch_events", "jobs"} <= tables
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()
```

- [ ] **Step 3: 실행해서 실패 확인**

Run: `cd server && python -m pytest tests/test_db.py -v`
Expected: FAIL (`app.db` 없음)

- [ ] **Step 4: schema.sql·db.py·main.py 구현**

`server/app/schema.sql`:
```sql
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  nickname TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS user_settings(
  user_id INTEGER PRIMARY KEY REFERENCES users(id),
  filter_on INTEGER NOT NULL DEFAULT 1,
  auto_skip INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS videos(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  uploader_id INTEGER NOT NULL REFERENCES users(id),
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'processing',  -- processing|ready|failed
  risk TEXT,                                  -- safe|corrected|uncorrected
  original_path TEXT, filtered_path TEXT, thumb_path TEXT, report_path TEXT,
  duration_s REAL,
  n_flash INTEGER NOT NULL DEFAULT 0, n_red INTEGER NOT NULL DEFAULT 0,
  n_pattern INTEGER NOT NULL DEFAULT 0, n_cut INTEGER NOT NULL DEFAULT 0,
  view_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS likes(
  user_id INTEGER NOT NULL, video_id INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY(user_id, video_id));
CREATE TABLE IF NOT EXISTS watch_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL, video_id INTEGER NOT NULL,
  watched_s REAL NOT NULL, variant TEXT NOT NULL,  -- original|filtered
  created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  video_id INTEGER NOT NULL UNIQUE REFERENCES videos(id),
  status TEXT NOT NULL DEFAULT 'queued',  -- queued|running|done|error
  error_msg TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  started_at TEXT, finished_at TEXT);
```

`server/app/db.py`:
```python
import sqlite3
from pathlib import Path

from app.config import settings

SCHEMA = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")


def connect(db_path=None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else settings.DATA_DIR / "db.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


def get_db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
```

`server/app/main.py`:
```python
from fastapi import FastAPI

app = FastAPI(title="gumchulgi platform")


@app.get("/health")
def health():
    return {"ok": True}
```

`server/app/__init__.py` 와 `server/tests/__init__.py`는 빈 파일.

- [ ] **Step 5: 테스트 통과 확인**

Run: `cd server && python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add server/
git commit -m "플랫폼 서버 뼈대 — 설정·SQLite 스키마·헬스체크"
```

---

### Task 2: 인증 — 가입·로그인·JWT

**Files:**
- Create: `server/app/auth.py`
- Modify: `server/app/main.py` (라우터 등록)
- Test: `server/tests/test_auth.py`, Modify: `server/tests/conftest.py` (client fixture)

**Interfaces:**
- Consumes: `db.get_db`, `config.settings`
- Produces: `auth.router` (POST /auth/signup·/auth/login, GET /me) / `auth.hash_pw(p:str)->str`, `auth.check_pw(p:str,h:str)->bool`, `auth.make_token(user_id:int)->str` / `auth.current_user` FastAPI 의존성 → sqlite3.Row(users 행). 이후 모든 태스크의 보호 엔드포인트가 사용.

- [ ] **Step 1: conftest 에 client fixture 추가**

`server/tests/conftest.py` 에 추가:
```python
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import db
    from app.config import settings
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers(client):
    def _make(email="u@t.co", nickname="유저"):
        r = client.post("/auth/signup", json={
            "email": email, "password": "pw123456", "nickname": nickname})
        assert r.status_code == 201, r.text
        return {"Authorization": f"Bearer {r.json()['token']}"}
    return _make
```

- [ ] **Step 2: 실패하는 인증 테스트 작성**

`server/tests/test_auth.py`:
```python
def test_signup_login_me(client):
    r = client.post("/auth/signup", json={
        "email": "a@b.co", "password": "pw123456", "nickname": "박"})
    assert r.status_code == 201
    assert r.json()["user"]["nickname"] == "박"

    dup = client.post("/auth/signup", json={
        "email": "a@b.co", "password": "x2345678", "nickname": "박2"})
    assert dup.status_code == 409

    r = client.post("/auth/login", json={"email": "a@b.co", "password": "pw123456"})
    assert r.status_code == 200
    token = r.json()["token"]

    bad = client.post("/auth/login", json={"email": "a@b.co", "password": "wrong"})
    assert bad.status_code == 401

    me = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["email"] == "a@b.co"
    assert client.get("/me").status_code in (401, 403)
```

- [ ] **Step 3: 실행해서 실패 확인**

Run: `cd server && python -m pytest tests/test_auth.py -v`
Expected: FAIL (404 — 라우터 없음)

- [ ] **Step 4: auth.py 구현 + 라우터 등록**

`server/app/auth.py`:
```python
import datetime as dt
import sqlite3

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.config import settings
from app.db import get_db

router = APIRouter()
bearer = HTTPBearer()


def hash_pw(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def check_pw(p: str, h: str) -> bool:
    return bcrypt.checkpw(p.encode(), h.encode())


def make_token(user_id: int) -> str:
    exp = dt.datetime.now(dt.UTC) + dt.timedelta(days=settings.TOKEN_DAYS)
    return jwt.encode({"sub": str(user_id), "exp": exp},
                      settings.JWT_SECRET, algorithm="HS256")


def current_user(cred: HTTPAuthorizationCredentials = Depends(bearer),
                 conn: sqlite3.Connection = Depends(get_db)) -> sqlite3.Row:
    try:
        payload = jwt.decode(cred.credentials, settings.JWT_SECRET,
                             algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "토큰이 유효하지 않습니다")
    row = conn.execute("SELECT * FROM users WHERE id=?",
                       (int(payload["sub"]),)).fetchone()
    if row is None:
        raise HTTPException(401, "사용자가 없습니다")
    return row


class SignupIn(BaseModel):
    email: str
    password: str
    nickname: str


class LoginIn(BaseModel):
    email: str
    password: str


def _user_out(row) -> dict:
    return {"id": row["id"], "email": row["email"], "nickname": row["nickname"]}


@router.post("/auth/signup", status_code=201)
def signup(body: SignupIn, conn: sqlite3.Connection = Depends(get_db)):
    if len(body.password) < 8:
        raise HTTPException(422, "비밀번호는 8자 이상")
    try:
        cur = conn.execute(
            "INSERT INTO users(email, password_hash, nickname) VALUES(?,?,?)",
            (body.email.lower(), hash_pw(body.password), body.nickname))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "이미 가입된 이메일입니다")
    uid = cur.lastrowid
    conn.execute("INSERT INTO user_settings(user_id) VALUES(?)", (uid,))
    row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return {"token": make_token(uid), "user": _user_out(row)}


@router.post("/auth/login")
def login(body: LoginIn, conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute("SELECT * FROM users WHERE email=?",
                       (body.email.lower(),)).fetchone()
    if row is None or not check_pw(body.password, row["password_hash"]):
        raise HTTPException(401, "이메일 또는 비밀번호가 틀립니다")
    return {"token": make_token(row["id"]), "user": _user_out(row)}


@router.get("/me")
def me(user: sqlite3.Row = Depends(current_user)):
    return _user_out(user)
```

`server/app/main.py` 수정:
```python
from fastapi import FastAPI

from app import auth

app = FastAPI(title="gumchulgi platform")
app.include_router(auth.router)


@app.get("/health")
def health():
    return {"ok": True}
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `cd server && python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add server/
git commit -m "인증 — 이메일 가입·로그인·JWT·current_user 의존성"
```

---

### Task 3: 사용자 설정 GET/PUT

**Files:**
- Create: `server/app/users.py`
- Modify: `server/app/main.py`
- Test: `server/tests/test_settings.py`

**Interfaces:**
- Consumes: `auth.current_user`, `db.get_db`
- Produces: `users.router` — GET/PUT `/me/settings` `{filter_on: bool, auto_skip: bool}`. (GET `/me/videos`는 Task 4 에서 이 라우터에 추가)

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_settings.py`:
```python
def test_settings_default_and_update(client, auth_headers):
    h = auth_headers()
    r = client.get("/me/settings", headers=h)
    assert r.status_code == 200
    assert r.json() == {"filter_on": True, "auto_skip": False}

    r = client.put("/me/settings", headers=h,
                   json={"filter_on": False, "auto_skip": True})
    assert r.status_code == 200
    assert client.get("/me/settings", headers=h).json() == {
        "filter_on": False, "auto_skip": True}
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `cd server && python -m pytest tests/test_settings.py -v`
Expected: FAIL (404)

- [ ] **Step 3: users.py 구현**

`server/app/users.py`:
```python
import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import current_user
from app.db import get_db

router = APIRouter()


class SettingsIO(BaseModel):
    filter_on: bool
    auto_skip: bool


def load_settings(conn, user_id: int) -> dict:
    row = conn.execute("SELECT filter_on, auto_skip FROM user_settings "
                       "WHERE user_id=?", (user_id,)).fetchone()
    return {"filter_on": bool(row["filter_on"]),
            "auto_skip": bool(row["auto_skip"])}


@router.get("/me/settings")
def get_settings(user=Depends(current_user),
                 conn: sqlite3.Connection = Depends(get_db)):
    return load_settings(conn, user["id"])


@router.put("/me/settings")
def put_settings(body: SettingsIO, user=Depends(current_user),
                 conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("UPDATE user_settings SET filter_on=?, auto_skip=? "
                 "WHERE user_id=?",
                 (int(body.filter_on), int(body.auto_skip), user["id"]))
    return body
```

`server/app/main.py`에 `from app import users` / `app.include_router(users.router)` 추가.

- [ ] **Step 4: 테스트 통과 확인 후 커밋**

Run: `cd server && python -m pytest tests/ -v` → PASS

```bash
git add server/
git commit -m "사용자 설정 — filter_on·auto_skip GET/PUT"
```

---

### Task 4: 저장 경로 규약 + 업로드 API + 내 영상 목록

**Files:**
- Create: `server/app/storage.py`, `server/worker/__init__.py`, `server/worker/ffmpeg.py` (probe 만)
- Create: `server/app/videos.py` (업로드만), Modify: `server/app/users.py` (/me/videos), `server/app/main.py`
- Test: `server/tests/test_upload.py`, Modify: `server/tests/conftest.py` (합성 mp4 fixture)

**Interfaces:**
- Consumes: `auth.current_user`, `db.get_db`, `config.settings`
- Produces: `storage.video_dir(vid:int)->Path` 및 `original_path/filtered_path/thumb_path/report_path/upload_path(vid, suffix:str)` (전부 `(vid:int)->Path`) / `ffmpeg.probe(path)->dict {duration_s: float, width: int, height: int, has_video: bool}` (실패 시 ValueError) / `POST /videos` → 202 `{video_id}` + jobs 큐잉 / `GET /me/videos`

- [ ] **Step 1: storage.py 구현** (테스트는 업로드 테스트로 겸함)

`server/app/storage.py`:
```python
from pathlib import Path

from app.config import settings


def video_dir(vid: int) -> Path:
    d = settings.DATA_DIR / "media" / str(vid)
    d.mkdir(parents=True, exist_ok=True)
    return d


def upload_path(vid: int, suffix: str) -> Path:
    return video_dir(vid) / f"upload{suffix}"


def original_path(vid: int) -> Path:
    return video_dir(vid) / "original.mp4"


def filtered_path(vid: int) -> Path:
    return video_dir(vid) / "filtered.mp4"


def thumb_path(vid: int) -> Path:
    return video_dir(vid) / "thumb.jpg"


def report_path(vid: int) -> Path:
    return video_dir(vid) / "report.json"
```

- [ ] **Step 2: ffmpeg.probe 구현**

`server/worker/ffmpeg.py`:
```python
import json
import subprocess


def probe(path) -> dict:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True)
    if p.returncode != 0:
        raise ValueError(f"ffprobe 실패: {p.stderr.strip()[:200]}")
    info = json.loads(p.stdout)
    vstreams = [s for s in info.get("streams", [])
                if s.get("codec_type") == "video"]
    if not vstreams:
        return {"duration_s": 0.0, "width": 0, "height": 0, "has_video": False}
    v = vstreams[0]
    dur = float(info.get("format", {}).get("duration") or 0.0)
    return {"duration_s": dur, "width": int(v.get("width", 0)),
            "height": int(v.get("height", 0)), "has_video": True}
```

- [ ] **Step 3: conftest 에 합성 mp4 fixture 추가**

`server/tests/conftest.py`에 추가:
```python
import subprocess


@pytest.fixture(scope="session")
def small_mp4(tmp_path_factory):
    """2초 360x640 회색 테스트 영상 (오디오 포함)."""
    p = tmp_path_factory.mktemp("clips") / "gray.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "color=c=gray:s=360x640:d=2:r=30",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", str(p)], check=True)
    return p
```

- [ ] **Step 4: 실패하는 업로드 테스트 작성**

`server/tests/test_upload.py`:
```python
def test_upload_queues_job(client, auth_headers, small_mp4):
    h = auth_headers()
    with open(small_mp4, "rb") as f:
        r = client.post("/videos", headers=h, data={"title": "테스트"},
                        files={"file": ("a.mp4", f, "video/mp4")})
    assert r.status_code == 202
    vid = r.json()["video_id"]

    mine = client.get("/me/videos", headers=h).json()["videos"]
    assert mine[0]["id"] == vid and mine[0]["status"] == "processing"


def test_upload_rejects_non_video(client, auth_headers):
    h = auth_headers()
    r = client.post("/videos", headers=h, data={"title": "x"},
                    files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 422
```

- [ ] **Step 5: 실행해서 실패 확인**

Run: `cd server && python -m pytest tests/test_upload.py -v`
Expected: FAIL (404)

- [ ] **Step 6: videos.py 업로드 구현 + /me/videos**

`server/app/videos.py`:
```python
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile

from app import storage
from app.auth import current_user
from app.config import settings
from app.db import get_db
from worker.ffmpeg import probe

router = APIRouter()
CHUNK = 1 << 20  # 1MB


@router.post("/videos", status_code=202)
def upload(file: UploadFile, title: str = Form(...),
           user=Depends(current_user),
           conn: sqlite3.Connection = Depends(get_db)):
    cur = conn.execute(
        "INSERT INTO videos(uploader_id, title) VALUES(?,?)",
        (user["id"], title.strip() or "무제"))
    vid = cur.lastrowid
    suffix = Path(file.filename or "v.mp4").suffix or ".mp4"
    dst = storage.upload_path(vid, suffix)

    limit = settings.MAX_UPLOAD_MB * (1 << 20)
    written = 0
    with open(dst, "wb") as out:
        while chunk := file.file.read(CHUNK):
            written += len(chunk)
            if written > limit:
                out.close(); dst.unlink(missing_ok=True)
                conn.execute("DELETE FROM videos WHERE id=?", (vid,))
                raise HTTPException(413, f"{settings.MAX_UPLOAD_MB}MB 초과")
            out.write(chunk)

    try:
        info = probe(dst)
    except ValueError:
        info = {"has_video": False, "duration_s": 0}
    if not info["has_video"]:
        dst.unlink(missing_ok=True)
        conn.execute("DELETE FROM videos WHERE id=?", (vid,))
        raise HTTPException(422, "영상 파일이 아닙니다")
    if info["duration_s"] > settings.MAX_DURATION_S:
        dst.unlink(missing_ok=True)
        conn.execute("DELETE FROM videos WHERE id=?", (vid,))
        raise HTTPException(422, f"{settings.MAX_DURATION_S}초 초과")

    conn.execute("INSERT INTO jobs(video_id) VALUES(?)", (vid,))
    return {"video_id": vid}
```

`server/app/users.py`에 추가:
```python
@router.get("/me/videos")
def my_videos(user=Depends(current_user),
              conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        "SELECT v.id, v.title, v.status, v.risk, v.duration_s, v.view_count,"
        " v.created_at,"
        " (SELECT COUNT(*) FROM likes l WHERE l.video_id=v.id) AS like_count"
        " FROM videos v WHERE v.uploader_id=? ORDER BY v.id DESC",
        (user["id"],)).fetchall()
    return {"videos": [
        {**dict(r), "thumb_url": f"/videos/{r['id']}/thumb"} for r in rows]}
```

`server/app/main.py`에 `from app import videos` / `app.include_router(videos.router)` 추가.

- [ ] **Step 7: 테스트 통과 확인 후 커밋**

Run: `cd server && python -m pytest tests/ -v` → PASS

```bash
git add server/
git commit -m "업로드 API — 크기·형식·길이 검증, jobs 큐잉, 내 영상 목록"
```

---

### Task 5: ffmpeg 정규화·썸네일

**Files:**
- Modify: `server/worker/ffmpeg.py`
- Test: `server/tests/test_ffmpeg.py`

**Interfaces:**
- Consumes: 없음 (subprocess 만)
- Produces: `ffmpeg.normalize(src, dst)` — H.264/AAC·faststart·yuv420p·가로 720 상한·짝수 해상도, 실패 시 RuntimeError / `ffmpeg.thumbnail(src, dst)` — 0.5s 지점 JPEG (영상이 더 짧으면 첫 프레임)

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_ffmpeg.py`:
```python
from worker import ffmpeg


def test_normalize_and_thumbnail(small_mp4, tmp_path):
    out = tmp_path / "norm.mp4"
    ffmpeg.normalize(small_mp4, out)
    info = ffmpeg.probe(out)
    assert info["has_video"] and info["width"] <= 720
    assert abs(info["duration_s"] - 2.0) < 0.5

    th = tmp_path / "t.jpg"
    ffmpeg.thumbnail(out, th)
    assert th.stat().st_size > 100
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `cd server && python -m pytest tests/test_ffmpeg.py -v`
Expected: FAIL (normalize 없음)

- [ ] **Step 3: 구현**

`server/worker/ffmpeg.py`에 추가:
```python
def _run(args):
    p = subprocess.run(["ffmpeg", "-y", "-v", "error", *args],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg 실패: {p.stderr.strip()[:300]}")


def normalize(src, dst):
    """H.264/AAC mp4 표준화. 가로 720 상한, 짝수 해상도, faststart."""
    _run(["-i", str(src),
          "-vf", "scale='min(720,iw)':-2",
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
          "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
          "-movflags", "+faststart", str(dst)])


def thumbnail(src, dst):
    try:
        _run(["-ss", "0.5", "-i", str(src), "-frames:v", "1",
              "-vf", "scale=360:-2", str(dst)])
    except RuntimeError:
        _run(["-i", str(src), "-frames:v", "1",
              "-vf", "scale=360:-2", str(dst)])
```

- [ ] **Step 4: 테스트 통과 확인 후 커밋**

Run: `cd server && python -m pytest tests/test_ffmpeg.py -v` → PASS

```bash
git add server/
git commit -m "ffmpeg 정규화·썸네일 — 720 상한 H.264/AAC faststart"
```

---

### Task 6: 검출 래퍼 — pse_bt1702 요약

**Files:**
- Create: `server/worker/detect.py`
- Test: `server/tests/test_detect.py`, Modify: `server/tests/conftest.py` (테스트 클립 fixture)

**Interfaces:**
- Consumes: `pse_bt1702.analyze(path)` (psepipe_v3_seam — conftest/PYTHONPATH 로 import 가능)
- Produces: `detect.detect(path) -> dict` — `{compliant: bool, axes: {flash:int, red:int, pattern:int, cut:int}, duration_s: float, report: dict}` (report = analyze 원본에서 `_spatial` 제거본) / `detect.save_report(report: dict, path)` — JSON 저장

- [ ] **Step 1: conftest 에 정답 클립 fixture 추가**

`server/tests/conftest.py`에 추가 (make_testclips 는 11편 전부 생성하므로 세션당 1회):
```python
@pytest.fixture(scope="session")
def testclips(tmp_path_factory):
    """legacy_detectors/make_testclips.py 로 정답 알려진 합성 클립 생성."""
    out = tmp_path_factory.mktemp("testclips")
    subprocess.run([sys.executable,
                    str(REPO / "legacy_detectors" / "make_testclips.py"),
                    str(out)], check=True, cwd=str(REPO))
    return out  # 00_safe_gradient.mkv(안전), 01_flash_5hz.mkv(플래시 위반) 등
```

- [ ] **Step 2: 실패하는 테스트 작성**

`server/tests/test_detect.py`:
```python
import json

from worker import detect


def test_safe_clip(testclips):
    r = detect.detect(testclips / "00_safe_gradient.mkv")
    assert r["compliant"] is True
    assert r["axes"] == {"flash": 0, "red": 0, "pattern": 0, "cut": 0}


def test_flash_clip(testclips, tmp_path):
    r = detect.detect(testclips / "01_flash_5hz.mkv")
    assert r["compliant"] is False
    assert r["axes"]["flash"] > 0

    p = tmp_path / "rep.json"
    detect.save_report(r["report"], p)
    assert json.loads(p.read_text(encoding="utf-8"))["compliant"] is False
```

- [ ] **Step 3: 실행해서 실패 확인**

Run: `cd server && python -m pytest tests/test_detect.py -v`
Expected: FAIL (detect 없음). (클립 생성 포함 1~2분 소요 정상)

- [ ] **Step 4: detect.py 구현**

`server/worker/detect.py`:
```python
import json
from pathlib import Path

import pse_bt1702

# violation_segments 의 rule 문자열 prefix → 대시보드 자극 축
_CAT = [("플래시", "flash"), ("적색", "red"), ("패턴", "pattern"),
        ("화면전환", "cut"), ("5초지속", "flash")]


def detect(path) -> dict:
    rep = pse_bt1702.analyze(str(path))
    rep.pop("_spatial", None)
    axes = {"flash": 0, "red": 0, "pattern": 0, "cut": 0}
    for seg in rep.get("violation_segments", []):
        for prefix, key in _CAT:
            if str(seg.get("rule", "")).startswith(prefix):
                axes[key] += 1
                break
    return {"compliant": bool(rep["compliant"]), "axes": axes,
            "duration_s": float(rep.get("duration_s") or 0.0), "report": rep}


def save_report(report: dict, path):
    Path(path).write_text(
        json.dumps(report, ensure_ascii=False, default=str),
        encoding="utf-8")
```

- [ ] **Step 5: 테스트 통과 확인 후 커밋**

Run: `cd server && python -m pytest tests/test_detect.py -v` → PASS

```bash
git add server/
git commit -m "검출 래퍼 — pse_bt1702 요약과 자극 축 매핑"
```

---

### Task 7: 스트리밍 보정 필터 (O(1) 메모리)

**Files:**
- Create: `server/worker/filter_stream.py`
- Test: `server/tests/test_filter_stream.py`

**Interfaces:**
- Consumes: `pselive3.Cfg.strong()`, `pselive3.LiveFilter3(fps,(ah,aw),cfg).push(f, sm)`
- Produces: `filter_stream.filter_video(src, dst) -> int` (처리 프레임 수). dst 는 H.264 faststart mp4, **src 의 오디오를 그대로 mux**. 실패 시 RuntimeError.

배경: `pselive3.run()`은 출력 프레임 전부를 리스트에 담아 3분 720p 기준 ~15GB 를 쓴다. 같은 알고리즘(LiveFilter3)을 쓰되 프레임을 ffmpeg stdin 으로 즉시 흘려보내는 변형이 필요하다. ffmpeg 인자는 run() 의 것을 그대로 재사용한다 (bt709 태그, `-map 1:a:0?` 오디오 copy 포함).

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_filter_stream.py`:
```python
from worker import ffmpeg
from worker.filter_stream import filter_video


def test_filter_flash_clip(testclips, tmp_path):
    src = tmp_path / "src.mp4"
    ffmpeg.normalize(testclips / "01_flash_5hz.mkv", src)
    dst = tmp_path / "flt.mp4"
    n = filter_video(src, dst)
    assert n > 0
    info = ffmpeg.probe(dst)
    assert info["has_video"]
    assert abs(info["duration_s"] - ffmpeg.probe(src)["duration_s"]) < 0.5


def test_audio_is_kept(small_mp4, tmp_path):
    dst = tmp_path / "flt.mp4"
    filter_video(small_mp4, dst)
    import json, subprocess
    p = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json",
                        "-show_streams", str(dst)],
                       capture_output=True, text=True, check=True)
    kinds = {s["codec_type"] for s in json.loads(p.stdout)["streams"]}
    assert "audio" in kinds
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `cd server && python -m pytest tests/test_filter_stream.py -v`
Expected: FAIL (filter_stream 없음)

- [ ] **Step 3: 구현**

`server/worker/filter_stream.py`:
```python
import subprocess

import cv2
import numpy as np

from pselive3 import Cfg, LiveFilter3


def filter_video(src, dst, cfg: Cfg | None = None) -> int:
    """pselive3 STRONG 을 스트리밍으로 적용. 메모리 O(1).

    pselive3.run() 과 같은 알고리즘·같은 인코딩 인자이지만 프레임을
    버퍼링하지 않고 ffmpeg stdin 으로 바로 흘린다. 오디오는 src 에서 copy.
    """
    cfg = cfg or Cfg.strong()
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise RuntimeError(f"영상을 열 수 없습니다: {src}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    s = cfg.short_side / min(W, H) if min(W, H) > cfg.short_side else 1.0
    aw, ah = max(2, int(W * s)), max(2, int(H * s))
    live = LiveFilter3(fps, (ah, aw), cfg)

    p = subprocess.Popen(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
         "-r", str(fps), "-i", "-",
         "-i", str(src), "-map", "0:v:0", "-map", "1:a:0?",
         "-c:a", "copy", "-shortest",
         "-sws_flags", "bicubic+accurate_rnd+full_chroma_int",
         "-c:v", "libx264", "-preset", "medium", "-crf", "16",
         "-pix_fmt", "yuv420p", "-colorspace", "bt709",
         "-color_primaries", "bt709", "-color_trc", "bt709",
         "-movflags", "+faststart", str(dst)],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    n = 0
    try:
        while True:
            ok, f = cap.read()
            if not ok:
                break
            sm = (cv2.resize(f, (aw, ah), interpolation=cv2.INTER_AREA)
                  if s != 1.0 else f)
            g = live.push(f, sm)
            p.stdin.write(np.ascontiguousarray(g).tobytes())
            n += 1
    finally:
        cap.release()
        p.stdin.close()
        err = p.stderr.read().decode(errors="replace")
        if p.wait() != 0:
            raise RuntimeError(f"ffmpeg 인코딩 실패: {err[:300]}")
    if n == 0:
        raise RuntimeError("프레임을 하나도 읽지 못했습니다")
    return n
```

- [ ] **Step 4: 테스트 통과 확인 후 커밋**

Run: `cd server && python -m pytest tests/test_filter_stream.py -v` → PASS

```bash
git add server/
git commit -m "스트리밍 보정 필터 — LiveFilter3 + ffmpeg 파이프, O(1) 메모리·오디오 유지"
```

---

### Task 8: 워커 — 파이프라인과 폴링 루프

**Files:**
- Create: `server/worker/pipeline.py`, `server/worker/main.py`
- Test: `server/tests/test_worker.py`

**Interfaces:**
- Consumes: `detect.detect/save_report`, `filter_stream.filter_video`, `ffmpeg.normalize/thumbnail`, `storage.*`, `db.connect`
- Produces: `pipeline.process_video(conn, video_id:int)` — 완료 시 videos 행 확정(status/risk/경로/축/duration), 예외는 호출자에게 전파 / `worker_main.claim_job(conn) -> sqlite3.Row|None`, `worker_main.requeue_stale(conn)`, `worker_main.run_once(conn) -> bool`(처리했으면 True), `worker_main.main()` 무한 루프

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_worker.py`:
```python
import sqlite3

from app import db, storage
from worker import main as worker_main
from worker import pipeline


def _setup(tmp_path, monkeypatch, clip):
    from app.config import settings
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    conn = db.connect()
    conn.execute("INSERT INTO users(email,password_hash,nickname) "
                 "VALUES('w@t.co','x','워커')")
    conn.execute("INSERT INTO videos(uploader_id,title) VALUES(1,'t')")
    vid = conn.execute("SELECT MAX(id) FROM videos").fetchone()[0]
    import shutil
    shutil.copy(clip, storage.upload_path(vid, clip.suffix))
    conn.execute("INSERT INTO jobs(video_id) VALUES(?)", (vid,))
    conn.commit()
    return conn, vid


def test_safe_clip_pipeline(tmp_path, monkeypatch, testclips):
    conn, vid = _setup(tmp_path, monkeypatch, testclips / "00_safe_gradient.mkv")
    assert worker_main.run_once(conn) is True
    v = conn.execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()
    assert v["status"] == "ready" and v["risk"] == "safe"
    assert v["filtered_path"] is None
    assert storage.original_path(vid).exists()
    assert storage.thumb_path(vid).exists()


def test_flash_clip_pipeline(tmp_path, monkeypatch, testclips):
    conn, vid = _setup(tmp_path, monkeypatch, testclips / "01_flash_5hz.mkv")
    assert worker_main.run_once(conn) is True
    v = conn.execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()
    assert v["status"] == "ready"
    assert v["risk"] in ("corrected", "uncorrected")   # 기계 동작 검증
    assert v["n_flash"] > 0
    assert storage.filtered_path(vid).exists()
    assert storage.report_path(vid).exists()
    job = conn.execute("SELECT * FROM jobs WHERE video_id=?", (vid,)).fetchone()
    assert job["status"] == "done"


def test_error_marks_failed(tmp_path, monkeypatch, small_mp4):
    conn, vid = _setup(tmp_path, monkeypatch, small_mp4)
    monkeypatch.setattr(pipeline, "detect",
                        type("D", (), {"detect": staticmethod(
                            lambda p: (_ for _ in ()).throw(RuntimeError("붐"))),
                            "save_report": staticmethod(lambda r, p: None)}))
    assert worker_main.run_once(conn) is True
    v = conn.execute("SELECT status FROM videos WHERE id=?", (vid,)).fetchone()
    assert v["status"] == "failed"
    job = conn.execute("SELECT * FROM jobs WHERE video_id=?", (vid,)).fetchone()
    assert job["status"] == "error" and "붐" in job["error_msg"]


def test_requeue_stale(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    conn = db.connect()
    conn.execute("INSERT INTO users(email,password_hash,nickname) "
                 "VALUES('r@t.co','x','재큐')")
    conn.execute("INSERT INTO videos(uploader_id,title) VALUES(1,'t')")
    conn.execute("INSERT INTO jobs(video_id,status,started_at) "
                 "VALUES(1,'running',datetime('now','-2 hours'))")
    worker_main.requeue_stale(conn)
    assert conn.execute("SELECT status FROM jobs").fetchone()[0] == "queued"
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `cd server && python -m pytest tests/test_worker.py -v`
Expected: FAIL (모듈 없음)

- [ ] **Step 3: pipeline.py 구현**

`server/worker/pipeline.py`:
```python
"""업로드 1건 처리: 정규화 → 검출 → (위반 시) 보정 → 재판정 → 확정.

스펙 2절의 워커 순서 그대로. 사다리(psepipe)는 MVP 범위 밖 —
재판정 불합격은 risk='uncorrected' 로 표시만 한다.
"""
from app import storage
from worker import detect, ffmpeg, filter_stream


def process_video(conn, video_id: int):
    vdir = storage.video_dir(video_id)
    upload = next(p for p in vdir.glob("upload.*"))
    orig = storage.original_path(video_id)

    ffmpeg.normalize(upload, orig)
    ffmpeg.thumbnail(orig, storage.thumb_path(video_id))

    first = detect.detect(orig)
    detect.save_report(first["report"], storage.report_path(video_id))

    if first["compliant"]:
        risk, filtered = "safe", None
    else:
        flt = storage.filtered_path(video_id)
        filter_stream.filter_video(orig, flt)
        second = detect.detect(flt)
        risk = "corrected" if second["compliant"] else "uncorrected"
        filtered = str(flt)

    a = first["axes"]
    conn.execute(
        "UPDATE videos SET status='ready', risk=?, original_path=?,"
        " filtered_path=?, thumb_path=?, report_path=?, duration_s=?,"
        " n_flash=?, n_red=?, n_pattern=?, n_cut=? WHERE id=?",
        (risk, str(orig), filtered, str(storage.thumb_path(video_id)),
         str(storage.report_path(video_id)), first["duration_s"],
         a["flash"], a["red"], a["pattern"], a["cut"], video_id))
    upload.unlink(missing_ok=True)
```

- [ ] **Step 4: worker/main.py 구현**

`server/worker/main.py`:
```python
import time
import traceback

from app import db
from worker import pipeline

STALE_MIN = 30
POLL_S = 2


def claim_job(conn):
    return conn.execute(
        "UPDATE jobs SET status='running', started_at=datetime('now')"
        " WHERE id=(SELECT id FROM jobs WHERE status='queued'"
        "           ORDER BY id LIMIT 1)"
        " RETURNING id, video_id").fetchone()


def requeue_stale(conn):
    conn.execute(
        "UPDATE jobs SET status='queued', started_at=NULL"
        " WHERE status='running'"
        f" AND started_at < datetime('now','-{STALE_MIN} minutes')")
    conn.commit()


def run_once(conn) -> bool:
    job = claim_job(conn)
    conn.commit()
    if job is None:
        return False
    try:
        pipeline.process_video(conn, job["video_id"])
        conn.execute("UPDATE jobs SET status='done',"
                     " finished_at=datetime('now') WHERE id=?", (job["id"],))
    except Exception as exc:
        traceback.print_exc()
        conn.execute("UPDATE videos SET status='failed' WHERE id=?",
                     (job["video_id"],))
        conn.execute("UPDATE jobs SET status='error', error_msg=?,"
                     " finished_at=datetime('now') WHERE id=?",
                     (str(exc)[:500], job["id"]))
    conn.commit()
    return True


def main():
    conn = db.connect()
    requeue_stale(conn)
    print("워커 시작 — 큐 폴링 중")
    while True:
        if not run_once(conn):
            time.sleep(POLL_S)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 테스트 통과 확인** (01 클립 보정+재판정 포함 수 분 소요 정상)

Run: `cd server && python -m pytest tests/test_worker.py -v`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add server/
git commit -m "워커 — 정규화→검출→STRONG 보정→재판정 파이프라인과 폴링 루프"
```

---

### Task 9: 피드 + 노출 규칙 + 좋아요

**Files:**
- Create: `server/app/feed.py`
- Modify: `server/app/videos.py` (좋아요), `server/app/main.py`
- Test: `server/tests/test_feed.py`

**Interfaces:**
- Consumes: `auth.current_user`, `users.load_settings`, `db.get_db`
- Produces: `feed.pick_variant(risk:str, filter_on:bool, auto_skip:bool) -> str|None` ("original"|"filtered"|None=제외) / `GET /feed` (커서 페이지네이션, ready 만, 최신순) / `POST·DELETE /videos/{id}/like`

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_feed.py`:
```python
import pytest

from app.feed import pick_variant


# 스펙 노출 규칙 표의 전 케이스 (risk 3종 × 설정 3조합)
@pytest.mark.parametrize("risk,filter_on,auto_skip,expected", [
    ("safe",        True,  False, "original"),
    ("safe",        False, False, "original"),
    ("safe",        False, True,  "original"),
    ("corrected",   True,  False, "filtered"),
    ("corrected",   False, False, "original"),
    ("corrected",   True,  True,  None),
    ("corrected",   False, True,  None),
    ("uncorrected", True,  False, None),
    ("uncorrected", False, False, "original"),
    ("uncorrected", False, True,  None),
])
def test_pick_variant(risk, filter_on, auto_skip, expected):
    assert pick_variant(risk, filter_on, auto_skip) == expected


def _insert_video(client, risk, title):
    from app import db
    conn = db.connect()
    conn.execute(
        "INSERT INTO videos(uploader_id,title,status,risk,original_path,"
        "filtered_path,n_flash) VALUES(1,?, 'ready',?, 'o.mp4',"
        " CASE WHEN ?='safe' THEN NULL ELSE 'f.mp4' END, 2)",
        (title, risk, risk))
    conn.commit(); conn.close()


def test_feed_applies_rules_and_pagination(client, auth_headers):
    h = auth_headers()
    for i, risk in enumerate(["safe", "corrected", "uncorrected"] * 2):
        _insert_video(client, risk, f"v{i}")

    # 기본 설정: filter_on=True, auto_skip=False → uncorrected 제외
    r = client.get("/feed?limit=10", headers=h).json()
    risks = [v["risk"] for v in r["videos"]]
    assert "uncorrected" not in risks
    assert all(v["variant"] == ("filtered" if v["risk"] == "corrected"
                                else "original") for v in r["videos"])
    assert all("stream_url" in v and "stimulus" in v for v in r["videos"])

    # 커서: limit=2 두 번 → 겹치지 않게 이어짐
    p1 = client.get("/feed?limit=2", headers=h).json()
    p2 = client.get(f"/feed?limit=2&cursor={p1['next_cursor']}", headers=h).json()
    ids1 = {v["id"] for v in p1["videos"]}
    assert ids1.isdisjoint({v["id"] for v in p2["videos"]})


def test_like_toggle(client, auth_headers):
    h = auth_headers()
    _insert_video(client, "safe", "좋아요용")
    vid = client.get("/feed?limit=1", headers=h).json()["videos"][0]["id"]
    r = client.post(f"/videos/{vid}/like", headers=h).json()
    assert r == {"like_count": 1, "liked": True}
    r = client.post(f"/videos/{vid}/like", headers=h).json()   # 멱등
    assert r == {"like_count": 1, "liked": True}
    r = client.delete(f"/videos/{vid}/like", headers=h).json()
    assert r == {"like_count": 0, "liked": False}
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `cd server && python -m pytest tests/test_feed.py -v`
Expected: FAIL

- [ ] **Step 3: feed.py 구현**

`server/app/feed.py`:
```python
import sqlite3

from fastapi import APIRouter, Depends

from app.auth import current_user
from app.db import get_db
from app.users import load_settings

router = APIRouter()


def pick_variant(risk: str, filter_on: bool, auto_skip: bool):
    """스펙 2절 노출 규칙 표. None = 피드에서 제외."""
    if risk == "safe":
        return "original"
    if auto_skip:
        return None
    if filter_on:
        return "filtered" if risk == "corrected" else None
    return "original"


def _row_to_feed(row, variant: str) -> dict:
    vid = row["id"]
    return {
        "id": vid, "title": row["title"],
        "uploader_nickname": row["nickname"], "risk": row["risk"],
        "variant": variant,
        "stream_url": f"/videos/{vid}/stream?variant={variant}",
        "thumb_url": f"/videos/{vid}/thumb",
        "duration_s": row["duration_s"],
        "like_count": row["like_count"], "view_count": row["view_count"],
        "liked_by_me": bool(row["liked"]),
        "stimulus": {"flash": row["n_flash"], "red": row["n_red"],
                     "pattern": row["n_pattern"], "cut": row["n_cut"]},
    }


@router.get("/feed")
def feed(cursor: int | None = None, limit: int = 10,
         user=Depends(current_user),
         conn: sqlite3.Connection = Depends(get_db)):
    st = load_settings(conn, user["id"])
    limit = max(1, min(limit, 30))
    out, cur = [], cursor
    while len(out) < limit:
        rows = conn.execute(
            "SELECT v.*, u.nickname,"
            " (SELECT COUNT(*) FROM likes l WHERE l.video_id=v.id) AS like_count,"
            " EXISTS(SELECT 1 FROM likes l2 WHERE l2.video_id=v.id"
            "        AND l2.user_id=?) AS liked"
            " FROM videos v JOIN users u ON u.id=v.uploader_id"
            " WHERE v.status='ready' AND (? IS NULL OR v.id < ?)"
            " ORDER BY v.id DESC LIMIT ?",
            (user["id"], cur, cur, limit * 3)).fetchall()
        if not rows:
            break
        for row in rows:
            cur = row["id"]
            variant = pick_variant(row["risk"], st["filter_on"], st["auto_skip"])
            if variant is not None:
                out.append(_row_to_feed(row, variant))
                if len(out) >= limit:
                    break
    return {"videos": out, "next_cursor": cur if out else None}
```

- [ ] **Step 4: 좋아요 엔드포인트 — videos.py 에 추가**

```python
def _like_count(conn, vid: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM likes WHERE video_id=?",
                        (vid,)).fetchone()[0]


@router.post("/videos/{vid}/like")
def like(vid: int, user=Depends(current_user),
         conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("INSERT OR IGNORE INTO likes(user_id, video_id) VALUES(?,?)",
                 (user["id"], vid))
    return {"like_count": _like_count(conn, vid), "liked": True}


@router.delete("/videos/{vid}/like")
def unlike(vid: int, user=Depends(current_user),
           conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("DELETE FROM likes WHERE user_id=? AND video_id=?",
                 (user["id"], vid))
    return {"like_count": _like_count(conn, vid), "liked": False}
```

`server/app/main.py`에 `from app import feed` / `app.include_router(feed.router)` 추가.

- [ ] **Step 5: 테스트 통과 확인 후 커밋**

Run: `cd server && python -m pytest tests/ -v` → PASS

```bash
git add server/
git commit -m "피드 — 노출 규칙 전 케이스·커서 페이지네이션·좋아요"
```

---

### Task 10: 스트리밍(Range)·썸네일·시청 이벤트

**Files:**
- Create: `server/app/dashboard.py` (노출 계산 함수만)
- Modify: `server/app/videos.py` (stream/thumb/events)
- Test: `server/tests/test_stream_events.py`

**Interfaces:**
- Consumes: `storage.*`, `auth.current_user`, `config.settings`
- Produces: `GET /videos/{id}/stream?variant=` 200/206 Range / `GET /videos/{id}/thumb` / `POST /videos/{id}/events` → `{today_percent, status}`, view_count +1, watch_events 기록 / `dashboard.exposure_today(conn, user_id:int) -> dict {risky_views:int, exposure_s:float, percent:float, status:str}` / `dashboard.status_for(percent:float) -> str`

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_stream_events.py`:
```python
from app import db, storage


def _ready_video(client, small_mp4, risk="corrected"):
    import shutil
    conn = db.connect()
    conn.execute("INSERT INTO videos(uploader_id,title,status,risk,"
                 "original_path,n_flash) VALUES(1,'t','ready',?,'x',1)", (risk,))
    vid = conn.execute("SELECT MAX(id) FROM videos").fetchone()[0]
    shutil.copy(small_mp4, storage.original_path(vid))
    conn.execute("UPDATE videos SET original_path=? WHERE id=?",
                 (str(storage.original_path(vid)), vid))
    conn.commit(); conn.close()
    return vid


def test_stream_supports_range(client, auth_headers, small_mp4):
    h = auth_headers()
    vid = _ready_video(client, small_mp4)
    r = client.get(f"/videos/{vid}/stream?variant=original", headers=h)
    assert r.status_code == 200
    assert r.headers["accept-ranges"] == "bytes"

    r = client.get(f"/videos/{vid}/stream?variant=original",
                   headers={**h, "Range": "bytes=0-99"})
    assert r.status_code == 206
    assert len(r.content) == 100
    assert r.headers["content-range"].startswith("bytes 0-99/")


def test_events_accumulate_exposure(client, auth_headers, small_mp4, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "DAILY_BUDGET_S", 100)
    h = auth_headers()
    vid = _ready_video(client, small_mp4, risk="corrected")

    r = client.post(f"/videos/{vid}/events", headers=h,
                    json={"watched_s": 30, "variant": "original"}).json()
    assert r["today_percent"] == 30.0 and r["status"] == "good"

    r = client.post(f"/videos/{vid}/events", headers=h,
                    json={"watched_s": 55, "variant": "original"}).json()
    assert r["today_percent"] == 85.0 and r["status"] == "warning"

    # 보정본 시청은 노출에 미포함
    r = client.post(f"/videos/{vid}/events", headers=h,
                    json={"watched_s": 60, "variant": "filtered"}).json()
    assert r["today_percent"] == 85.0

    # 조회수는 전부 +1
    from app import db as db2
    conn = db2.connect()
    assert conn.execute("SELECT view_count FROM videos WHERE id=?",
                        (vid,)).fetchone()[0] == 3
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `cd server && python -m pytest tests/test_stream_events.py -v`
Expected: FAIL

- [ ] **Step 3: dashboard.py 노출 계산 구현**

`server/app/dashboard.py`:
```python
import sqlite3

from fastapi import APIRouter, Depends

from app.auth import current_user
from app.config import settings
from app.db import get_db

router = APIRouter()

# 위험 노출 = risk≠safe 영상을 original 로 본 이벤트 (스펙 3절)
_RISKY = ("SELECT e.* FROM watch_events e JOIN videos v ON v.id=e.video_id"
          " WHERE e.user_id=? AND e.variant='original'"
          " AND v.risk IN ('corrected','uncorrected')")


def status_for(percent: float) -> str:
    if percent >= 80:
        return "warning"
    if percent >= 50:
        return "caution"
    return "good"


def exposure_today(conn: sqlite3.Connection, user_id: int) -> dict:
    row = conn.execute(
        f"SELECT COUNT(*) n, COALESCE(SUM(watched_s),0) s FROM ({_RISKY})"
        " WHERE date(created_at,'localtime')=date('now','localtime')",
        (user_id,)).fetchone()
    percent = round(row["s"] / settings.DAILY_BUDGET_S * 100, 1)
    return {"risky_views": row["n"], "exposure_s": round(row["s"], 1),
            "percent": percent, "status": status_for(percent)}
```

- [ ] **Step 4: stream/thumb/events — videos.py 에 추가**

```python
import os

from fastapi import Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app.dashboard import exposure_today


def _video_or_404(conn, vid: int):
    row = conn.execute("SELECT * FROM videos WHERE id=? AND status='ready'",
                       (vid,)).fetchone()
    if row is None:
        raise HTTPException(404, "영상이 없습니다")
    return row


@router.get("/videos/{vid}/stream")
def stream(vid: int, request: Request, variant: str = "original",
           user=Depends(current_user),
           conn: sqlite3.Connection = Depends(get_db)):
    row = _video_or_404(conn, vid)
    path = row["filtered_path"] if variant == "filtered" else row["original_path"]
    if not path or not os.path.exists(path):
        raise HTTPException(404, "해당 버전이 없습니다")
    size = os.path.getsize(path)
    rng = request.headers.get("range")
    start, end = 0, size - 1
    status = 200
    if rng and rng.startswith("bytes="):
        s, _, e = rng[6:].partition("-")
        start = int(s) if s else 0
        end = min(int(e), size - 1) if e else size - 1
        if start > end or start >= size:
            raise HTTPException(416, "잘못된 Range")
        status = 206

    def _iter(p=path, a=start, b=end):
        with open(p, "rb") as f:
            f.seek(a)
            left = b - a + 1
            while left > 0:
                chunk = f.read(min(CHUNK, left))
                if not chunk:
                    break
                left -= len(chunk)
                yield chunk

    headers = {"Accept-Ranges": "bytes",
               "Content-Length": str(end - start + 1)}
    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(_iter(), status_code=status, headers=headers,
                             media_type="video/mp4")


@router.get("/videos/{vid}/thumb")
def thumb(vid: int, user=Depends(current_user),
          conn: sqlite3.Connection = Depends(get_db)):
    row = _video_or_404(conn, vid)
    if not row["thumb_path"] or not os.path.exists(row["thumb_path"]):
        raise HTTPException(404, "썸네일이 없습니다")
    return FileResponse(row["thumb_path"], media_type="image/jpeg")


class EventIn(BaseModel):
    watched_s: float
    variant: str  # original | filtered


@router.post("/videos/{vid}/events")
def watch_event(vid: int, body: EventIn, user=Depends(current_user),
                conn: sqlite3.Connection = Depends(get_db)):
    _video_or_404(conn, vid)
    conn.execute("INSERT INTO watch_events(user_id,video_id,watched_s,variant)"
                 " VALUES(?,?,?,?)",
                 (user["id"], vid, max(0.0, body.watched_s), body.variant))
    conn.execute("UPDATE videos SET view_count=view_count+1 WHERE id=?", (vid,))
    ex = exposure_today(conn, user["id"])
    return {"today_percent": ex["percent"], "status": ex["status"]}
```

- [ ] **Step 5: 테스트 통과 확인 후 커밋**

Run: `cd server && python -m pytest tests/ -v` → PASS

```bash
git add server/
git commit -m "영상 스트리밍(Range)·썸네일·시청 이벤트와 노출 응답"
```

---

### Task 11: 대시보드 API

**Files:**
- Modify: `server/app/dashboard.py`, `server/app/main.py`
- Test: `server/tests/test_dashboard.py`

**Interfaces:**
- Consumes: `exposure_today`, `auth.current_user`
- Produces: `GET /dashboard/today`, `GET /dashboard/weekly` (계약서 형태 그대로)

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_dashboard.py`:
```python
from app import db


def _seed(client, uid_email, events):
    """events: (risk, watched_s, variant, days_ago, hour)"""
    conn = db.connect()
    for i, (risk, w, var, days, hour) in enumerate(events):
        conn.execute("INSERT INTO videos(uploader_id,title,status,risk,"
                     "n_flash,n_red) VALUES(1,'t','ready',?,1,1)", (risk,))
        vid = conn.execute("SELECT MAX(id) FROM videos").fetchone()[0]
        uid = conn.execute("SELECT id FROM users WHERE email=?",
                           (uid_email,)).fetchone()[0]
        conn.execute(
            "INSERT INTO watch_events(user_id,video_id,watched_s,variant,"
            "created_at) VALUES(?,?,?,?,"
            " datetime(datetime('now','localtime'),'start of day',"
            f" '-{days} days', '+{hour} hours', 'utc'))",
            (uid, vid, w, var))
    conn.commit(); conn.close()


def test_today_and_weekly(client, auth_headers, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "DAILY_BUDGET_S", 100)
    h = auth_headers(email="d@t.co")
    _seed(client, "d@t.co", [
        ("corrected", 40, "original", 0, 9),    # 오늘 09시
        ("uncorrected", 50, "original", 0, 10), # 오늘 10시
        ("corrected", 30, "filtered", 0, 11),   # 노출 미포함
        ("safe", 30, "original", 0, 12),        # 노출 미포함
        ("corrected", 20, "original", 2, 9),    # 이틀 전
    ])
    t = client.get("/dashboard/today", headers=h).json()
    assert t["risky_views"] == 2
    assert t["exposure_s"] == 90.0
    assert t["percent"] == 90.0 and t["status"] == "warning"
    assert t["budget_s"] == 100
    assert t["stimulus"]["flash"] == 2 and t["stimulus"]["red"] == 2
    # 곡선: 9시 40%, 10시 이후 90%
    curve = {c["hour"]: c["percent"] for c in t["curve"]}
    assert curve[9] == 40.0 and curve[10] == 90.0

    w = client.get("/dashboard/weekly", headers=h).json()
    assert len(w["days"]) == 7
    assert w["days"][-1]["risky_views"] == 2      # 오늘
    assert w["days"][-3]["risky_views"] == 1      # 이틀 전
    assert w["avg"] == round(3 / 7, 1)
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `cd server && python -m pytest tests/test_dashboard.py -v`
Expected: FAIL (404)

- [ ] **Step 3: 엔드포인트 구현 — dashboard.py 에 추가**

```python
@router.get("/dashboard/today")
def today(user=Depends(current_user),
          conn: sqlite3.Connection = Depends(get_db)):
    ex = exposure_today(conn, user["id"])
    stim = conn.execute(
        "SELECT COALESCE(SUM(v.n_flash),0) f, COALESCE(SUM(v.n_red),0) r,"
        " COALESCE(SUM(v.n_pattern),0) p, COALESCE(SUM(v.n_cut),0) c"
        " FROM watch_events e JOIN videos v ON v.id=e.video_id"
        " WHERE e.user_id=? AND e.variant='original'"
        " AND v.risk IN ('corrected','uncorrected')"
        " AND date(e.created_at,'localtime')=date('now','localtime')",
        (user["id"],)).fetchone()
    rows = conn.execute(
        "SELECT CAST(strftime('%H', e.created_at,'localtime') AS INT) h,"
        " SUM(e.watched_s) s"
        " FROM watch_events e JOIN videos v ON v.id=e.video_id"
        " WHERE e.user_id=? AND e.variant='original'"
        " AND v.risk IN ('corrected','uncorrected')"
        " AND date(e.created_at,'localtime')=date('now','localtime')"
        " GROUP BY h ORDER BY h", (user["id"],)).fetchall()
    acc, curve = 0.0, []
    for r in rows:
        acc += r["s"]
        curve.append({"hour": r["h"],
                      "percent": round(acc / settings.DAILY_BUDGET_S * 100, 1)})
    return {**ex, "budget_s": settings.DAILY_BUDGET_S,
            "stimulus": {"flash": stim["f"], "red": stim["r"],
                         "pattern": stim["p"], "cut": stim["c"]},
            "curve": curve}


@router.get("/dashboard/weekly")
def weekly(user=Depends(current_user),
           conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        "SELECT date(e.created_at,'localtime') d, COUNT(*) n"
        " FROM watch_events e JOIN videos v ON v.id=e.video_id"
        " WHERE e.user_id=? AND e.variant='original'"
        " AND v.risk IN ('corrected','uncorrected')"
        " AND date(e.created_at,'localtime')"
        "     >= date('now','localtime','-6 days')"
        " GROUP BY d", (user["id"],)).fetchall()
    by_day = {r["d"]: r["n"] for r in rows}
    days = conn.execute(
        "SELECT date('now','localtime', '-' || value || ' days') d"
        " FROM (SELECT 6 value UNION SELECT 5 UNION SELECT 4 UNION SELECT 3"
        "       UNION SELECT 2 UNION SELECT 1 UNION SELECT 0)"
        " ORDER BY value DESC").fetchall()
    out = [{"date": r["d"], "risky_views": by_day.get(r["d"], 0)} for r in days]
    total = sum(d["risky_views"] for d in out)
    return {"days": out, "avg": round(total / 7, 1)}
```

`server/app/main.py`에 `from app import dashboard` / `app.include_router(dashboard.router)` 추가.

- [ ] **Step 4: 테스트 통과 확인 후 커밋**

Run: `cd server && python -m pytest tests/ -v` → PASS

```bash
git add server/
git commit -m "광 노출 대시보드 API — 오늘 지표·시간대 곡선·주간 차트"
```

---

### Task 12: Docker 화 + 로컬 스모크

**Files:**
- Create: `server/Dockerfile`, `docker-compose.yml` (저장소 루트), `server/README.md`
- Modify: `server/.env.example` (없으면 갱신)

**Interfaces:**
- Consumes: 전체 서버 코드
- Produces: `docker compose up -d` 로 api(:8000)+worker 기동. 로컬·EC2 동일.

- [ ] **Step 1: Dockerfile 작성**

`server/Dockerfile`:
```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /repo
COPY psepipe_v3_seam/ psepipe_v3_seam/
COPY server/requirements.txt server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt
COPY server/ server/
ENV PYTHONPATH=/repo/server:/repo/psepipe_v3_seam
WORKDIR /repo/server
```

- [ ] **Step 2: docker-compose.yml 작성 (저장소 루트)**

```yaml
services:
  api:
    build: { context: ., dockerfile: server/Dockerfile }
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
    ports: ["8000:8000"]
    env_file: server/.env
    environment: { DATA_DIR: /data, TZ: Asia/Seoul }
    volumes: [ "./data:/data" ]
    restart: unless-stopped
  worker:
    build: { context: ., dockerfile: server/Dockerfile }
    command: python -m worker.main
    env_file: server/.env
    environment: { DATA_DIR: /data, TZ: Asia/Seoul }
    volumes: [ "./data:/data" ]
    restart: unless-stopped
```

- [ ] **Step 3: server/README.md 작성 — 실행·배포 절차**

내용에 반드시 포함:
```markdown
# 플랫폼 서버

## 로컬 실행
cp server/.env.example server/.env   # JWT_SECRET 수정
docker compose up -d --build
curl http://localhost:8000/health    # {"ok":true}

## 테스트
cd server && pip install -r requirements-dev.txt && python -m pytest tests/ -v

## EC2 배포 (Ubuntu)
1. Docker·compose 설치, git clone -b platform-mvp <repo>
2. server/.env 작성 (JWT_SECRET 필수 변경)
3. docker compose up -d --build
4. 보안그룹에서 8000/tcp 오픈 → 앱의 API_BASE 를 http://<EC2-IP>:8000 으로
```

- [ ] **Step 4: 스모크 테스트**

Run: `cp server/.env.example server/.env && docker compose up -d --build && sleep 5 && curl -s http://localhost:8000/health`
Expected: `{"ok":true}` — 이후 `docker compose logs worker | head -5` 에 "워커 시작" 확인.
(Docker 미설치 환경이면 venv 2개 터미널로 동일 스모크: `uvicorn app.main:app` + `python -m worker.main`)

- [ ] **Step 5: 커밋**

```bash
git add server/ docker-compose.yml
git commit -m "Docker 구성 — api+worker 컴포즈, EC2 배포 가이드"
```

---

## 완료 기준

- `cd server && python -m pytest tests/ -v` 전부 PASS
- compose 기동 후: 가입 → 01_flash 클립 업로드 → 워커 처리 → `/feed`에 corrected 로 노출 → `/videos/{id}/stream?variant=filtered` 재생 가능 → events 반복 → `/dashboard/today` percent 상승 → 80% 초과 시 status=warning
