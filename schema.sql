PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS entries (
  id INTEGER PRIMARY KEY,
  ts DATETIME NOT NULL,
  app TEXT,
  window_title TEXT,
  project TEXT,
  coarse_task TEXT,
  summary TEXT,
  confidence REAL,
  json TEXT
);

CREATE TABLE IF NOT EXISTS files (
  path TEXT PRIMARY KEY,
  mtime REAL NOT NULL,
  entry_id INTEGER,
  FOREIGN KEY(entry_id) REFERENCES entries(id) ON DELETE SET NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(
  entry_id UNINDEXED,
  text
);
