from __future__ import annotations

from pathlib import Path
from typing import Dict
import sqlite3
import json


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(schema_sql: str, db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(schema_sql)


def already_processed(conn: sqlite3.Connection, path: str) -> bool:
    cur = conn.execute("SELECT 1 FROM files WHERE path = ?", (path,))
    return cur.fetchone() is not None


def store_file_record(conn: sqlite3.Connection, path: str, mtime: float, entry_id: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO files(path, mtime, entry_id) VALUES(?,?,?)",
        (path, mtime, entry_id),
    )


def insert_entry(
    conn: sqlite3.Connection,
    entry: Dict,
    evidence_text: str,
    file_path: str,
    mtime: float,
) -> int:
    cur = conn.execute(
        """INSERT INTO entries (ts, app, window_title, project, coarse_task, summary, confidence, json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            entry["ts"],
            entry["app"],
            entry["window_title"],
            entry["project"],
            entry["coarse_task"],
            entry["summary"],
            entry["confidence"],
            json.dumps(entry, ensure_ascii=False),
        ),
    )
    entry_id = cur.lastrowid
    conn.execute("INSERT INTO evidence_fts(entry_id, text) VALUES(?, ?)", (entry_id, evidence_text))
    store_file_record(conn, file_path, mtime, entry_id)
    conn.commit()
    return entry_id


