import sqlite3
from pathlib import Path

from app.config import settings

SCHEMA = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")


def connect(db_path=None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else settings.DATA_DIR / "db.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    # FastAPI 스레드풀에서 의존성 setup/teardown 이 서로 다른 워커 스레드에서
    # 실행될 수 있다 — 요청당 연결이라 동시 사용은 없으므로 스레드 검사만 끈다.
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
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
    ucols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    if "is_admin" not in ucols:
        conn.execute(
            "ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
    _seed_admin(conn)


def _seed_admin(conn):
    """운영 대시보드용 관리자 계정. 이미 있으면 관리자 플래그만 보장한다."""
    row = conn.execute("SELECT id FROM users WHERE email=?",
                       ("admin@gumchulgi.app",)).fetchone()
    if row is None:
        import bcrypt
        h = bcrypt.hashpw(b"admin1234", bcrypt.gensalt()).decode()
        cur = conn.execute(
            "INSERT INTO users(email, password_hash, nickname, is_admin)"
            " VALUES(?,?,?,1)", ("admin@gumchulgi.app", h, "관리자"))
        conn.execute("INSERT INTO user_settings(user_id) VALUES(?)",
                     (cur.lastrowid,))
    else:
        conn.execute("UPDATE users SET is_admin=1 WHERE id=?", (row["id"],))
    conn.commit()


def get_db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
