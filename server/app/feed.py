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
