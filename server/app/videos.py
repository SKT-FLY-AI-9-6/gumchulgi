import os
import sqlite3
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app import storage
from app.auth import current_user, user_from_token
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


_bearer_opt = HTTPBearer(auto_error=False)


def media_user(cred: HTTPAuthorizationCredentials | None = Depends(_bearer_opt),
               token: str | None = None,
               conn: sqlite3.Connection = Depends(get_db)):
    """스트림·썸네일용 인증. 웹 <video>/<img>는 헤더를 못 보내므로
    운영 환경이 아닐 때만 ?token= 쿼리를 허용한다."""
    if cred is not None:
        return user_from_token(conn, cred.credentials)
    if token and settings.APP_ENV != "production":
        return user_from_token(conn, token)
    raise HTTPException(401, "인증이 필요합니다")


@router.get("/videos/{vid}/stream")
def stream(vid: int, request: Request,
           variant: Literal["original", "filtered"] = "original",
           user=Depends(media_user),
           conn: sqlite3.Connection = Depends(get_db)):
    row = _video_or_404(conn, vid)
    path = row["filtered_path"] if variant == "filtered" else row["original_path"]
    if not path or not os.path.exists(path):
        raise HTTPException(404, "해당 버전이 없습니다")
    size = os.path.getsize(path)
    rng = request.headers.get("range")
    start, end = 0, size - 1
    status = 200
    if rng and rng.startswith("bytes=") and "," not in rng:
        s, _, e = rng[6:].strip().partition("-")
        try:
            if s == "" and e == "":
                raise ValueError("빈 Range")
            if s == "":
                # 접미사 형태 "bytes=-N" — 마지막 N바이트 (RFC 7233)
                start, end = max(0, size - int(e)), size - 1
            else:
                start = int(s)
                end = min(int(e), size - 1) if e else size - 1
            if start > end or start >= size:
                raise HTTPException(416, "잘못된 Range",
                                    headers={"Content-Range": f"bytes */{size}"})
            status = 206
        except ValueError:
            # 숫자로 해석할 수 없는 Range는 무시하고 전체를 서빙
            start, end, status = 0, size - 1, 200

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
def thumb(vid: int, user=Depends(media_user),
          conn: sqlite3.Connection = Depends(get_db)):
    row = _video_or_404(conn, vid)
    if not row["thumb_path"] or not os.path.exists(row["thumb_path"]):
        raise HTTPException(404, "썸네일이 없습니다")
    return FileResponse(row["thumb_path"], media_type="image/jpeg")


class EventIn(BaseModel):
    watched_s: float
    variant: Literal["original", "filtered"]


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


# ── 업로더용 검출 리포트 ──────────────────────────────────────────

def _merged_segments(report: dict) -> list[dict]:
    """rule 별로 겹치거나 0.5초 이내로 이어지는 위반 구간을 병합한다."""
    by_rule: dict[str, list] = {}
    for seg in report.get("violation_segments", []):
        try:
            s, e = float(seg["start_s"]), float(seg["end_s"])
        except (KeyError, TypeError, ValueError):
            continue
        by_rule.setdefault(str(seg.get("rule", "")), []).append((s, e))
    out = []
    for rule, spans in by_rule.items():
        spans.sort()
        cur_s, cur_e = spans[0]
        for s, e in spans[1:]:
            if s <= cur_e + 0.5:
                cur_e = max(cur_e, e)
            else:
                out.append({"rule": rule, "start_s": round(cur_s, 2),
                            "end_s": round(cur_e, 2)})
                cur_s, cur_e = s, e
        out.append({"rule": rule, "start_s": round(cur_s, 2),
                    "end_s": round(cur_e, 2)})
    out.sort(key=lambda x: x["start_s"])
    return out


def _load_json(path) -> dict | None:
    if not path or not os.path.exists(path):
        return None
    import json
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@router.get("/videos/{vid}/report")
def video_report(vid: int, user=Depends(current_user),
                 conn: sqlite3.Connection = Depends(get_db)):
    row = _video_or_404(conn, vid)
    if row["uploader_id"] != user["id"] and not user["is_admin"]:
        raise HTTPException(403, "본인 영상만 볼 수 있습니다")
    report = _load_json(row["report_path"]) or {}
    filtered = _load_json(storage.report_filtered_path(vid))
    segments = _merged_segments(report)
    # 보정 후 잔존 위반과 겹치는 구간은 '부분 완화'
    residual = _merged_segments(filtered) if filtered else []
    for seg in segments:
        left = seg["start_s"] - 0.25
        right = seg["end_s"] + 0.25
        seg["resolved"] = row["risk"] == "safe" or (
            row["risk"] == "corrected" and not any(
                r["start_s"] < right and r["end_s"] > left
                for r in residual))
    filt = conn.execute(
        "SELECT SUM(CASE WHEN variant='filtered' THEN 1 ELSE 0 END) f,"
        " COUNT(*) n FROM watch_events WHERE video_id=?", (vid,)).fetchone()
    ratio = round(100.0 * (filt["f"] or 0) / filt["n"], 1) if filt["n"] else None
    return {
        "id": vid, "title": row["title"], "status": row["status"],
        "risk": row["risk"], "duration_s": row["duration_s"],
        "view_count": row["view_count"],
        "filter_level": row["filter_level"],
        "compliant_original": bool(report.get("compliant", True)),
        "segments": segments,
        "filter_on_watch_percent": ratio,
    }
