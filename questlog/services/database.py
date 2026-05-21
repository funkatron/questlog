"""Database service for Questlog."""

import sqlite3
from pathlib import Path

import ql.db as qldb


class DatabaseService:
    """Service for database operations."""

    def __init__(self, db_path: Path = Path("questlog.db")):
        """Initialize database service.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        """Get a database connection.

        Returns:
            SQLite connection to the questlog database.
        """
        return qldb.connect(self.db_path)

    def ensure_schema(self) -> None:
        """Ensure database schema exists."""
        schema_sql = Path("schema.sql").read_text()
        qldb.ensure_schema(schema_sql, self.db_path)

    def already_processed(self, conn: sqlite3.Connection, path: str) -> bool:
        """Check if a file has already been processed.

        Args:
            conn: Database connection.
            path: File path to check.

        Returns:
            True if already processed, False otherwise.
        """
        return qldb.already_processed(conn, path)

    def store_file_record(
        self, conn: sqlite3.Connection, path: str, mtime: float, entry_id: int
    ) -> None:
        """Store file record in database.

        Args:
            conn: Database connection.
            path: File path.
            mtime: Modification time.
            entry_id: Entry ID.
        """
        qldb.store_file_record(conn, path, mtime, entry_id)

    def insert_entry(
        self,
        conn: sqlite3.Connection,
        entry: dict,
        evidence_text: str,
        file_path: str,
        mtime: float,
    ) -> int:
        """Insert entry into database.

        Args:
            conn: Database connection.
            entry: Entry dictionary.
            evidence_text: Evidence text for FTS.
            file_path: File path.
            mtime: Modification time.

        Returns:
            Entry ID.
        """
        return qldb.insert_entry(conn, entry, evidence_text, file_path, mtime)

    def update_entry(
        self,
        conn: sqlite3.Connection,
        entry_id: int,
        entry: dict,
        evidence_text: str,
        file_path: str,
        mtime: float,
    ) -> int:
        """Update an existing entry in the database."""
        return qldb.update_entry(conn, entry_id, entry, evidence_text, file_path, mtime)
