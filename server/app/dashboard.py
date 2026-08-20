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
