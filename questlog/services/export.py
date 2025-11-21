"""Export service for Questlog."""

import csv
import datetime as dt
from pathlib import Path
from typing import Any

from questlog.config import QuestlogConfig


class ExportService:
    """Service for exporting questlog data."""

    def __init__(self, config: QuestlogConfig):
        """Initialize export service.

        Args:
            config: Questlog configuration.
        """
        self.config = config

    def sessionize(self, rows: list[dict], grace_gap: int | None = None) -> list[dict]:
        """Group entries into sessions based on time gaps.

        Args:
            rows: List of entry dictionaries.
            grace_gap: Seconds between entries to consider same session.
                       Defaults to config value.

        Returns:
            List of session dictionaries.
        """
        if grace_gap is None:
            grace_gap = self.config.grace_gap_seconds

        sessions = []
        cur = None
        last_ts = None
        for r in rows:
            t = dt.datetime.fromisoformat(r["ts"])
            key = (r["project"], r["app"], r["coarse_task"])
            if cur is None:
                cur = {"start": t, "end": t, "key": key, "items": [r]}
                last_ts = t
                continue
            delta = (t - last_ts).total_seconds()
            if key == cur["key"] and delta <= grace_gap:
                cur["end"] = t
                cur["items"].append(r)
            else:
                sessions.append(cur)
                cur = {"start": t, "end": t, "key": key, "items": [r]}
            last_ts = t
        if cur:
            sessions.append(cur)
        return sessions

    def export_markdown(self, conn, date: str) -> Path:
        """Export a daily Markdown timeline.

        Args:
            conn: Database connection.
            date: Date in YYYY-MM-DD format.

        Returns:
            Path to exported file.
        """
        cur = conn.execute(
            """
            SELECT id, ts, app, window_title, project, coarse_task, summary, confidence
            FROM entries
            WHERE date(ts) = ?
            ORDER BY ts ASC
        """,
            (date,),
        )
        rows = [dict(r) for r in cur.fetchall()]

        sessions = self.sessionize(rows)

        md_lines = [f"# Quest Log - {date}", ""]
        for s in sessions:
            proj, app, task = s["key"]
            start = s["start"].strftime("%H:%M:%S")
            end = s["end"].strftime("%H:%M:%S")
            md_lines.append(
                f"## {start}-{end} • {task or 'Unknown'} • {proj or 'Unknown'} • {app}"
            )
            md_lines.append("")
            for it in s["items"]:
                t = dt.datetime.fromisoformat(it["ts"]).strftime("%H:%M:%S")
                md_lines.append(
                    f"- {t} - {it['summary']} *(conf: {it['confidence']:.2f})*"
                )
            md_lines.append("")

        out_dir = Path("exports")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"questlog_{date}.md"
        out_path.write_text("\n".join(md_lines))
        return out_path

    def export_csv(self, conn, date: str) -> Path:
        """Export a daily CSV.

        Args:
            conn: Database connection.
            date: Date in YYYY-MM-DD format.

        Returns:
            Path to exported file.
        """
        cur = conn.execute(
            """
            SELECT ts, app, window_title, project, coarse_task, summary, confidence
            FROM entries
            WHERE date(ts) = ?
            ORDER BY ts ASC
        """,
            (date,),
        )
        rows = [dict(r) for r in cur.fetchall()]

        out_dir = Path("exports")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"questlog_{date}.csv"
        with open(out_path, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "ts",
                    "app",
                    "window_title",
                    "project",
                    "coarse_task",
                    "summary",
                    "confidence",
                ],
            )
            writer.writeheader()
            for r in rows:
                writer.writerow(r)
        return out_path

