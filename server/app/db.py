import sqlite3
from pathlib import Path

from app.config import settings

SCHEMA = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")


def connect(db_path=None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else settings.DATA_DIR / "db.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn):
    # CREATE IF NOT EXISTS 는 기존 테이블을 바꾸지 않는다 — 스키마에 뒤늦게
    # 추가된 컬럼은 기존 DB 에 ALTER 로 보충한다.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(videos)")}
    if "filter_level" not in cols:
        conn.execute("ALTER TABLE videos ADD COLUMN filter_level TEXT")


def get_db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
