import sqlite3

from fastapi import APIRouter, Depends

from app.auth import current_user
from app.config import settings
from app.db import get_db

router = APIRouter()

# 위험 노출 = risk≠safe 영상을 original 로 본 이벤트 (스펙 3절)
_RISKY = ("SELECT e.* FROM watch_events e JOIN videos v ON v.id=e.video_id"
          " WHERE e.user_id=? AND e.variant='original'"
          " AND v.risk IN ('corrected','uncorrected')")


def status_for(percent: float) -> str:
    if percent >= 80:
        return "warning"
    if percent >= 50:
        return "caution"
    return "good"


def exposure_today(conn: sqlite3.Connection, user_id: int) -> dict:
    row = conn.execute(
        f"SELECT COUNT(*) n, COALESCE(SUM(watched_s),0) s FROM ({_RISKY})"
        " WHERE date(created_at,'localtime')=date('now','localtime')",
        (user_id,)).fetchone()
    percent = round(row["s"] / settings.DAILY_BUDGET_S * 100, 1)
    return {"risky_views": row["n"], "exposure_s": round(row["s"], 1),
            "percent": percent, "status": status_for(percent)}


@router.get("/dashboard/today")
def today(user=Depends(current_user),
          conn: sqlite3.Connection = Depends(get_db)):
    ex = exposure_today(conn, user["id"])
    stim = conn.execute(
        "SELECT COALESCE(SUM(v.n_flash),0) f, COALESCE(SUM(v.n_red),0) r,"
        " COALESCE(SUM(v.n_pattern),0) p, COALESCE(SUM(v.n_cut),0) c"
        " FROM watch_events e JOIN videos v ON v.id=e.video_id"
        " WHERE e.user_id=? AND e.variant='original'"
        " AND v.risk IN ('corrected','uncorrected')"
        " AND date(e.created_at,'localtime')=date('now','localtime')",
        (user["id"],)).fetchone()
    rows = conn.execute(
        "SELECT CAST(strftime('%H', e.created_at,'localtime') AS INT) h,"
        " SUM(e.watched_s) s"
        " FROM watch_events e JOIN videos v ON v.id=e.video_id"
        " WHERE e.user_id=? AND e.variant='original'"
        " AND v.risk IN ('corrected','uncorrected')"
        " AND date(e.created_at,'localtime')=date('now','localtime')"
        " GROUP BY h ORDER BY h", (user["id"],)).fetchall()
    acc, curve = 0.0, []
    for r in rows:
        acc += r["s"]
        curve.append({"hour": r["h"],
                      "percent": round(acc / settings.DAILY_BUDGET_S * 100, 1)})
    return {**ex, "budget_s": settings.DAILY_BUDGET_S,
            "stimulus": {"flash": stim["f"], "red": stim["r"],
                         "pattern": stim["p"], "cut": stim["c"]},
            "curve": curve}


@router.get("/dashboard/weekly")
def weekly(user=Depends(current_user),
           conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        "SELECT date(e.created_at,'localtime') d, COUNT(*) n"
        " FROM watch_events e JOIN videos v ON v.id=e.video_id"
        " WHERE e.user_id=? AND e.variant='original'"
        " AND v.risk IN ('corrected','uncorrected')"
        " AND date(e.created_at,'localtime')"
        "     >= date('now','localtime','-6 days')"
        " GROUP BY d", (user["id"],)).fetchall()
    by_day = {r["d"]: r["n"] for r in rows}
    days = conn.execute(
        "SELECT date('now','localtime', '-' || value || ' days') d"
        " FROM (SELECT 6 value UNION SELECT 5 UNION SELECT 4 UNION SELECT 3"
        "       UNION SELECT 2 UNION SELECT 1 UNION SELECT 0)"
        " ORDER BY value DESC").fetchall()
    out = [{"date": r["d"], "risky_views": by_day.get(r["d"], 0)} for r in days]
    total = sum(d["risky_views"] for d in out)
    return {"days": out, "avg": round(total / 7, 1)}
