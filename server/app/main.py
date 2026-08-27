from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import admin, auth, dashboard, feed, studio, users, videos
from app.config import validate_production

validate_production()

app = FastAPI(title="gumchulgi platform")
app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(videos.router)
app.include_router(feed.router)
app.include_router(dashboard.router)
app.include_router(studio.router)


@app.get("/health")
def health():
    return {"ok": True}


# 업로더 스튜디오 웹 콘솔 — /studio (API 는 /studio/api/*, 라우트가 먼저라
# 마운트에 가로채이지 않는다).
_STUDIO_DIR = Path(__file__).resolve().parents[1] / "webstudio"
if _STUDIO_DIR.exists():
    app.mount("/studio", StaticFiles(directory=_STUDIO_DIR, html=True),
              name="studio")

# Flutter 웹 빌드가 있으면 같은 출처로 정적 서빙 (데모·개발용).
# API 라우트가 먼저 등록되어 있어 /auth 등은 가로채지 않는다.
_WEB_DIR = Path(__file__).resolve().parents[2] / "app" / "build" / "web"
if _WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=_WEB_DIR, html=True), name="web")
