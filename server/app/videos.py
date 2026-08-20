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
