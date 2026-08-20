from fastapi import FastAPI

from app import auth

app = FastAPI(title="gumchulgi platform")
app.include_router(auth.router)


@app.get("/health")
def health():
    return {"ok": True}
