"""업로더 스튜디오 API — 웹 콘솔(server/webstudio)이 쓰는 얇은 층.

기존 라우터와의 역할 구분:
  /feed          시청자용 — status='ready' 만, 노출 규칙 적용
  /videos/{id}/* 시청·리포트 — ready 전제
  /studio/api/*  업로더 본인 소유 영상을 **모든 상태**(processing/failed 포함)로
                 다룬다. 처리 중 폴링과 실패 사유(jobs.error_msg) 노출이 목적.

정적 웹은 main.py 가 /studio 에 마운트한다 — API 경로를 /studio/api/* 로
띄워 정적 파일과 절대 겹치지 않게 한다.
"""
import os
import shutil
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app import storage
from app.auth import current_user
from app.db import get_db

router = APIRouter(prefix="/studio/api")


def _row_out(row) -> dict:
    vid = row["id"]
    ready = row["status"] == "ready"
    return {
        "id": vid, "title": row["title"], "status": row["status"],
        "risk": row["risk"], "filter_level": row["filter_level"],
        "duration_s": row["duration_s"], "view_count": row["view_count"],
        "like_count": row["like_count"], "created_at": row["created_at"],
        "stimulus": {"flash": row["n_flash"], "red": row["n_red"],
                     "pattern": row["n_pattern"], "cut": row["n_cut"]},
        "has_filtered": bool(row["filtered_path"]),
        "thumb_url": f"/videos/{vid}/thumb" if ready and row["thumb_path"] else None,
        "job_status": row["job_status"], "job_error": row["error_msg"],
    }


@router.get("/videos")
def my_videos(all: int = 0, user=Depends(current_user),
              conn: sqlite3.Connection = Depends(get_db)):
    """내 업로드 전체 (관리자는 all=1 로 전 사용자 영상)."""
    where, args = "v.uploader_id=?", [user["id"]]
    if all and user["is_admin"]:
        where, args = "1=1", []
    rows = conn.execute(
        f"SELECT v.*, j.status AS job_status, j.error_msg,"
        f" (SELECT COUNT(*) FROM likes l WHERE l.video_id=v.id) AS like_count"
        f" FROM videos v LEFT JOIN jobs j ON j.video_id=v.id"
        f" WHERE {where} ORDER BY v.id DESC", args).fetchall()
    return {"videos": [_row_out(r) for r in rows]}


@router.delete("/videos/{vid}")
def delete_video(vid: int, user=Depends(current_user),
                 conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()
    if row is None:
        raise HTTPException(404, "영상이 없습니다")
    if row["uploader_id"] != user["id"] and not user["is_admin"]:
        raise HTTPException(403, "본인 영상만 지울 수 있습니다")
    job = conn.execute("SELECT status FROM jobs WHERE video_id=?",
                       (vid,)).fetchone()
    if job and job["status"] == "running":
        raise HTTPException(409, "처리 중인 영상은 지울 수 없습니다")
    for t in ("watch_events", "likes", "jobs"):
        conn.execute(f"DELETE FROM {t} WHERE video_id=?", (vid,))
    conn.execute("DELETE FROM videos WHERE id=?", (vid,))
    d = storage.video_dir(vid)
    if os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)
    return {"deleted": vid}
