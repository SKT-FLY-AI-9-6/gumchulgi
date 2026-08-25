from app import db


def test_connect_applies_schema_and_wal(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite3")
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"users", "user_settings", "videos", "likes",
            "watch_events", "jobs"} <= tables
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()
