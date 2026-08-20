import time
import traceback

from app import db
from worker import pipeline

STALE_MIN = 30
POLL_S = 2


def claim_job(conn):
    return conn.execute(
        "UPDATE jobs SET status='running', started_at=datetime('now')"
        " WHERE id=(SELECT id FROM jobs WHERE status='queued'"
        "           ORDER BY id LIMIT 1)"
        " RETURNING id, video_id").fetchone()


def requeue_stale(conn):
    conn.execute(
        "UPDATE jobs SET status='queued', started_at=NULL"
        " WHERE status='running'"
        f" AND started_at < datetime('now','-{STALE_MIN} minutes')")
    conn.commit()


def run_once(conn) -> bool:
    job = claim_job(conn)
    conn.commit()
    if job is None:
        return False
    try:
        pipeline.process_video(conn, job["video_id"])
        conn.execute("UPDATE jobs SET status='done',"
                     " finished_at=datetime('now') WHERE id=?", (job["id"],))
    except Exception as exc:
        traceback.print_exc()
        conn.execute("UPDATE videos SET status='failed' WHERE id=?",
                     (job["video_id"],))
        conn.execute("UPDATE jobs SET status='error', error_msg=?,"
                     " finished_at=datetime('now') WHERE id=?",
                     (str(exc)[:500], job["id"]))
    conn.commit()
    return True


def main():
    conn = db.connect()
    requeue_stale(conn)
    print("워커 시작 — 큐 폴링 중")
    while True:
        if not run_once(conn):
            time.sleep(POLL_S)


if __name__ == "__main__":
    main()
