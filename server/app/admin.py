"""운영(관리자) 대시보드 — 필터 ON/OFF 의 사업 가치를 숫자로.

위험 영상(risk != 'safe') 시청 이벤트를 variant 로 갈라 비교한다:
  filtered = 보정본을 본 시청 (필터 ON 경험)
  original = 원본을 본 시청  (필터 OFF 경험)

지표
  views            시청 수
  avg_watch_ratio  평균 시청 유지율 (watched_s / 영상 길이, 1.0 상한)
  bounce_rate      이탈율 — 영상의 절반을 못 보고 넘긴 시청 비율

B2C 환산 (데모용 추정 모델 — 가정은 응답에 그대로 노출)
  지켜낸 시청시간 = (ON 유지율 − OFF 유지율) × 위험 노출수 × 평균 영상 길이
  절약 추정액   = 지켜낸 시청시간(분) × 분당 광고 노출(imp_per_min) × CPM/1000
"""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import current_user
from app.db import get_db

router = APIRouter()

BOUNCE_RATIO = 0.5          # 이 비율 미만 시청 = 이탈


def admin_user(user: sqlite3.Row = Depends(current_user)) -> sqlite3.Row:
    if not user["is_admin"]:
        raise HTTPException(403, "관리자 전용입니다")
    return user


def _group(conn, variant: str) -> dict:
    rows = conn.execute(
        "SELECT e.watched_s, v.duration_s FROM watch_events e"
        " JOIN videos v ON v.id = e.video_id"
        " WHERE e.variant = ? AND v.risk IS NOT NULL AND v.risk != 'safe'"
        " AND v.duration_s > 0", (variant,)).fetchall()
    n = len(rows)
    if n == 0:
        return {"views": 0, "avg_watch_ratio": 0.0, "bounce_rate": 0.0,
                "watch_s": 0.0, "avg_duration_s": 0.0}
    ratios = [min(r["watched_s"] / r["duration_s"], 1.0) for r in rows]
    return {
        "views": n,
        "avg_watch_ratio": round(sum(ratios) / n, 4),
        "bounce_rate": round(sum(1 for x in ratios if x < BOUNCE_RATIO) / n, 4),
        "watch_s": round(sum(r["watched_s"] for r in rows), 1),
        "avg_duration_s": round(sum(r["duration_s"] for r in rows) / n, 2),
    }


@router.get("/admin/metrics")
def metrics(cpm: float = Query(5000.0, ge=0),
            imp_per_min: float = Query(1.0, ge=0),
            user: sqlite3.Row = Depends(admin_user),
            conn: sqlite3.Connection = Depends(get_db)):
    on = _group(conn, "filtered")
    off = _group(conn, "original")

    delta_ratio = max(on["avg_watch_ratio"] - off["avg_watch_ratio"], 0.0)
    delta_bounce = max(off["bounce_rate"] - on["bounce_rate"], 0.0)
    avg_dur = (on["avg_duration_s"] or off["avg_duration_s"]) or 0.0

    def saved_krw(exposures: float) -> float:
        kept_min = delta_ratio * exposures * avg_dur / 60.0
        return kept_min * imp_per_min * cpm / 1000.0

    total_risky = on["views"] + off["views"]
    return {
        "groups": {"filtered": on, "original": off},
        "delta": {"watch_ratio_pp": round(delta_ratio * 100, 1),
                  "bounce_pp": round(delta_bounce * 100, 1)},
        "assumptions": {"cpm": cpm, "imp_per_min": imp_per_min,
                        "bounce_ratio": BOUNCE_RATIO,
                        "avg_duration_s": avg_dur},
        "savings": {
            "kept_min_actual": round(
                delta_ratio * off["views"] * avg_dur / 60.0, 1),
            "saved_krw_actual": round(saved_krw(off["views"])),
            "saved_krw_per_10k": round(saved_krw(10_000)),
            "saved_krw_per_1m": round(saved_krw(1_000_000)),
        },
        "total_risky_views": total_risky,
    }
