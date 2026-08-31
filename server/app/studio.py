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


@router.get("/dashboard")
def dashboard(user=Depends(current_user),
              conn: sqlite3.Connection = Depends(get_db)):
    """채널 대시보드 집계 — 최근 28일 창 vs 직전 28일 창.

    반환:
      stats     총 조회·필터 ON 비율(각 증감), 안전 인증률, 시청자 수(구독자
                프록시 = 내 영상을 본 고유 시청자)
      weekly    최근 7일 일별 {조회수, 필터 ON 비율} — 차트용
      sensitivity  내 시청자의 민감 프로파일 구성 (user_settings 기반:
                   auto_skip=광과민성, filter_on=민감, 나머지=표준)
      insight   인증(safe·corrected) vs 미보정 영상의 평균 완주율 차이(%p)
    """
    uid = user["id"]
    base = ("FROM watch_events e JOIN videos v ON v.id=e.video_id"
            " WHERE v.uploader_id=?")
    cur = "date(e.created_at,'localtime') >= date('now','localtime','-27 days')"
    prev = ("date(e.created_at,'localtime') < date('now','localtime','-27 days')"
            " AND date(e.created_at,'localtime')"
            " >= date('now','localtime','-55 days')")

    def window(cond):
        r = conn.execute(
            f"SELECT COUNT(*) n, SUM(CASE WHEN e.variant='filtered'"
            f" THEN 1 ELSE 0 END) f {base} AND {cond}", (uid,)).fetchone()
        n, f = r["n"] or 0, r["f"] or 0
        return n, (round(100.0 * f / n, 1) if n else None)

    views, fpct = window(cur)
    pviews, pfpct = window(prev)
    views_delta = (round(100.0 * (views - pviews) / pviews, 1)
                   if pviews else None)
    filter_delta = (round(fpct - pfpct, 1)
                    if fpct is not None and pfpct is not None else None)

    c = conn.execute(
        "SELECT COUNT(*) t, SUM(CASE WHEN risk IN ('safe','corrected')"
        " THEN 1 ELSE 0 END) c FROM videos"
        " WHERE uploader_id=? AND status='ready'", (uid,)).fetchone()
    total_ready, certified = c["t"] or 0, c["c"] or 0
    n_videos = conn.execute("SELECT COUNT(*) n FROM videos WHERE uploader_id=?",
                            (uid,)).fetchone()["n"]

    viewers = conn.execute(
        f"SELECT COUNT(DISTINCT e.user_id) n {base}", (uid,)).fetchone()["n"] or 0
    viewers_prev = conn.execute(
        f"SELECT COUNT(DISTINCT e.user_id) n {base}"
        f" AND date(e.created_at,'localtime')"
        f" < date('now','localtime','-27 days')", (uid,)).fetchone()["n"] or 0

    rows = conn.execute(
        f"SELECT date(e.created_at,'localtime') d, COUNT(*) n,"
        f" SUM(CASE WHEN e.variant='filtered' THEN 1 ELSE 0 END) f {base}"
        f" AND date(e.created_at,'localtime')"
        f" >= date('now','localtime','-6 days') GROUP BY d", (uid,)).fetchall()
    by_day = {r["d"]: r for r in rows}
    weekly = []
    for i in range(6, -1, -1):
        d = conn.execute("SELECT date('now','localtime',?) d",
                         (f"-{i} days",)).fetchone()["d"]
        r = by_day.get(d)
        n = r["n"] if r else 0
        f = (r["f"] or 0) if r else 0
        weekly.append({"date": d, "views": n,
                       "filter_on_pct": round(100.0 * f / n, 1) if n else None})

    s = conn.execute(
        "SELECT COUNT(*) t,"
        " SUM(CASE WHEN COALESCE(s.auto_skip,0)=1 THEN 1 ELSE 0 END) p,"
        " SUM(CASE WHEN COALESCE(s.auto_skip,0)=0"
        "  AND COALESCE(s.filter_on,1)=1 THEN 1 ELSE 0 END) m"
        " FROM (SELECT DISTINCT e.user_id uid FROM watch_events e"
        "  JOIN videos v ON v.id=e.video_id WHERE v.uploader_id=?) u"
        " LEFT JOIN user_settings s ON s.user_id=u.uid", (uid,)).fetchone()
    st = s["t"] or 0
    photo, mig = s["p"] or 0, s["m"] or 0
    std = st - photo - mig

    def pct(x):
        return round(100.0 * x / st) if st else 0

    ins = conn.execute(
        "SELECT AVG(CASE WHEN v.risk IN ('safe','corrected')"
        "  THEN MIN(1.0, e.watched_s / v.duration_s) END) a,"
        " AVG(CASE WHEN v.risk='uncorrected'"
        "  THEN MIN(1.0, e.watched_s / v.duration_s) END) b"
        " FROM watch_events e JOIN videos v ON v.id=e.video_id"
        " WHERE v.uploader_id=? AND v.duration_s > 0"
        " AND date(e.created_at,'localtime')"
        " >= date('now','localtime','-27 days')", (uid,)).fetchone()
    insight = None
    if ins["a"] is not None and ins["b"] is not None:
        insight = {"cert_completion_pct": round(ins["a"] * 100, 1),
                   "uncert_completion_pct": round(ins["b"] * 100, 1),
                   "delta_pp": round((ins["a"] - ins["b"]) * 100, 1)}

    return {
        "period_days": 28,
        "stats": {
            "views": views, "views_delta_pct": views_delta,
            "filter_on_pct": fpct, "filter_on_delta_pp": filter_delta,
            "cert": {"certified": certified, "total": total_ready,
                     "pct": (round(100.0 * certified / total_ready)
                             if total_ready else None)},
            "viewers": viewers, "viewers_new": viewers - viewers_prev,
            "videos_total": n_videos,
        },
        "weekly": weekly,
        "sensitivity": {"standard_pct": pct(std), "sensitive_pct": pct(mig),
                        "photosensitive_pct": pct(photo), "viewers": st},
        "insight": insight,
    }


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
