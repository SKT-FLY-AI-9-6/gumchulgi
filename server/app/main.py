from fastapi import FastAPI

from app import auth, dashboard, feed, users, videos
from app.config import validate_production

validate_production()

app = FastAPI(title="gumchulgi platform")
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(videos.router)
app.include_router(feed.router)
app.include_router(dashboard.router)


@app.get("/health")
def health():
    return {"ok": True}
