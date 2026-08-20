import os
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app import storage
from app.auth import current_user
from app.config import settings
from app.db import get_db
from app.dashboard import exposure_today
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
