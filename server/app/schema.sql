CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  nickname TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS user_settings(
  user_id INTEGER PRIMARY KEY REFERENCES users(id),
  filter_on INTEGER NOT NULL DEFAULT 1,
  auto_skip INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS videos(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  uploader_id INTEGER NOT NULL REFERENCES users(id),
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'processing',  -- processing|ready|failed
  risk TEXT,                                  -- safe|corrected|uncorrected
  filter_level TEXT,                          -- strong|base (사다리 채택 강도)
  seg_total_s REAL,                           -- 조각 길이 합
  seg_ratio REAL,                             -- 조각합 / 전체
  original_path TEXT, filtered_path TEXT, thumb_path TEXT, report_path TEXT,
  duration_s REAL,
  n_flash INTEGER NOT NULL DEFAULT 0, n_red INTEGER NOT NULL DEFAULT 0,
  n_pattern INTEGER NOT NULL DEFAULT 0, n_cut INTEGER NOT NULL DEFAULT 0,
  view_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS likes(
  user_id INTEGER NOT NULL, video_id INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY(user_id, video_id));
CREATE TABLE IF NOT EXISTS watch_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL, video_id INTEGER NOT NULL,
  watched_s REAL NOT NULL, variant TEXT NOT NULL,  -- original|filtered
  created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  video_id INTEGER NOT NULL UNIQUE REFERENCES videos(id),
  status TEXT NOT NULL DEFAULT 'queued',  -- queued|running|done|error
  error_msg TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  started_at TEXT, finished_at TEXT);
CREATE TABLE IF NOT EXISTS video_segments(
  video_id INTEGER NOT NULL REFERENCES videos(id),
  idx      INTEGER NOT NULL,
  start_s  REAL NOT NULL,
  end_s    REAL NOT NULL,
  path     TEXT NOT NULL,
  bytes    INTEGER,
  PRIMARY KEY(video_id, idx));
CREATE INDEX IF NOT EXISTS idx_seg_video ON video_segments(video_id, start_s);
