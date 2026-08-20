from fastapi import FastAPI

from app import auth, feed, users, videos

app = FastAPI(title="gumchulgi platform")
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(videos.router)
app.include_router(feed.router)


@app.get("/health")
def health():
    return {"ok": True}
