from fastapi import FastAPI

app = FastAPI(title="gumchulgi platform")


@app.get("/health")
def health():
    return {"ok": True}
