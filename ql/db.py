"""Database operations for Questlog.

This module handles SQLite database connections, schema management, and entry storage.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Any
import sqlite3
import json


def connect(db_path: Path) -> sqlite3.Connection:
    """Create a database connection with row factory enabled.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        A database connection with Row factory for dict-like access.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(schema_sql: str, db_path: Path) -> None:
    """Create database tables if they don't exist.

    Args:
        schema_sql: SQL script containing CREATE TABLE statements.
        db_path: Path to the SQLite database file.
    """
    with connect(db_path) as conn:
        conn.executescript(schema_sql)


def already_processed(conn: sqlite3.Connection, path: str) -> bool:
    """Check if a file has already been processed.

    Args:
        conn: Database connection.
        path: File path to check.

    Returns:
        True if the file exists in the files table, False otherwise.
    """
    cur = conn.execute("SELECT 1 FROM files WHERE path = ?", (path,))
    return cur.fetchone() is not None


def store_file_record(
    conn: sqlite3.Connection,
    path: str,
    mtime: float,
    entry_id: int
) -> None:
    """Store or update a file record linking a screenshot to an entry.

    Args:
        conn: Database connection.
        path: File path of the screenshot.
        mtime: Modification time of the file.
        entry_id: ID of the associated entry.
    """
    conn.execute(
        "INSERT OR REPLACE INTO files(path, mtime, entry_id) VALUES(?,?,?)",
        (path, mtime, entry_id),
    )


def insert_entry(
    conn: sqlite3.Connection,
    entry: Dict[str, Any],
    evidence_text: str,
    file_path: str,
    mtime: float,
) -> int:
    """Insert a new activity entry into the database.

    Stores the entry in the entries table, adds evidence text to the FTS index,
    and creates a file record linking the screenshot to the entry.

    Args:
        conn: Database connection.
        entry: Dictionary containing entry data (ts, app, window_title, project,
               coarse_task, summary, confidence, and other metadata).
        evidence_text: Text content for full-text search indexing.
        file_path: Path to the source screenshot file.
        mtime: Modification time of the screenshot file.

    Returns:
        The ID of the newly created entry.
    """
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
    conn.execute(
        "INSERT INTO evidence_fts(entry_id, text) VALUES(?, ?)",
        (entry_id, evidence_text)
    )
    store_file_record(conn, file_path, mtime, entry_id)
    conn.commit()
    return entry_id


