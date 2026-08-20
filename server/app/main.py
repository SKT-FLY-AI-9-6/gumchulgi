from fastapi import FastAPI

from app import auth, users

app = FastAPI(title="gumchulgi platform")
app.include_router(auth.router)
app.include_router(users.router)


@app.get("/health")
def health():
    return {"ok": True}
