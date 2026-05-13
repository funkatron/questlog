"""Resume/re-entry service for recent Questlog activity."""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from typing import Any

from ql.text import redact_for_display


OPEN_LOOP_TERMS = (
    "blocked",
    "broken",
    "debug",
    "error",
    "fail",
    "failed",
    "fix",
    "issue",
    "pr ",
    "pull request",
    "review",
    "test",
    "timeout",
    "todo",
    "wip",
)


class ResumeService:
    """Build a neutral restart note from recent stored activity."""

    def __init__(self, config: Any):
        self.config = config

    def build_resume(
        self,
        conn,
        *,
        hours: float = 4.0,
        now: dt.datetime | None = None,
    ) -> dict[str, Any]:
        """Return structured resume data for the recent activity window."""
        now = now or dt.datetime.now().astimezone()
        if now.tzinfo is None:
            now = now.astimezone()
        window_start = now - dt.timedelta(hours=hours)

        rows = self._load_rows(conn, window_start, now)
        sessions = self._sessionize(rows)
        low_confidence = self._low_confidence_items(rows)
        open_loops = self._open_loops(rows)
        artifacts = self._artifacts(rows)
        last_session = sessions[-1] if sessions else None

        return {
            "window_start": window_start.isoformat(timespec="seconds"),
            "window_end": now.isoformat(timespec="seconds"),
            "hours": hours,
            "entry_count": len(rows),
            "last_thread": self._last_thread(last_session),
            "working_on": self._working_on(last_session, artifacts),
            "recent_sessions": [self._session_summary(s) for s in sessions[-5:]],
            "context_switches": self._context_switches(sessions),
            "open_loops": open_loops[:5],
            "next_action": self._next_action(last_session, open_loops, artifacts),
            "low_confidence": low_confidence[:5],
        }

    def render_text(self, resume: dict[str, Any]) -> str:
        """Render structured resume data as concise terminal text."""
        if resume["entry_count"] == 0:
            return "\n".join(
                [
                    "Last thread: No recent activity found",
                    f"Window: {resume['window_start']} to {resume['window_end']}",
                    "",
                    "Restart here:",
                    "- Capture or backfill recent screenshots, then run `questlog resume` again.",
                ]
            )

        lines = [
            f"Last thread: {resume['last_thread']}",
            "",
            "You were working on:",
        ]
        lines.extend(self._bullet_lines(resume["working_on"], fallback="Recent activity was captured, but the task is unclear."))

        lines.append("")
        lines.append("Possible open loops:")
        lines.extend(self._bullet_lines(resume["open_loops"], fallback="No obvious open loops found in the recent window."))

        lines.append("")
        lines.append("Context switches:")
        lines.extend(self._bullet_lines(resume["context_switches"], fallback="No major context switches found."))

        lines.append("")
        lines.append("Restart here:")
        lines.append(f"- {resume['next_action']}")

        lines.append("")
        lines.append("Low-confidence items:")
        lines.extend(self._bullet_lines(resume["low_confidence"], fallback="No low-confidence items found."))
        return "\n".join(lines)

    def _load_rows(
        self,
        conn,
        window_start: dt.datetime,
        now: dt.datetime,
    ) -> list[dict[str, Any]]:
        cur = conn.execute(
            """
            SELECT id, ts, app, window_title, project, coarse_task, summary, confidence, json
            FROM entries
            WHERE ts >= ? AND ts <= ?
            ORDER BY ts ASC
            """,
            (window_start.isoformat(timespec="seconds"), now.isoformat(timespec="seconds")),
        )
        rows = []
        for row in cur.fetchall():
            item = dict(row)
            item["summary"] = redact_for_display(item.get("summary") or "")
            item["window_title"] = redact_for_display(item.get("window_title") or "")
            item["artifacts"] = []
            if item.get("json"):
                try:
                    payload = json.loads(item["json"])
                    item["artifacts"] = [
                        redact_for_display(str(a)) for a in payload.get("artifacts", [])[:5]
                    ]
                except Exception:
                    item["artifacts"] = []
            rows.append(item)
        return rows

    def _sessionize(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grace_gap = int(getattr(self.config, "grace_gap_seconds", 120))
        sessions: list[dict[str, Any]] = []
        cur = None
        last_ts = None
        for row in rows:
            ts = dt.datetime.fromisoformat(row["ts"])
            key = (
                row.get("project") or "Unknown",
                row.get("app") or "Unknown",
                row.get("coarse_task") or "Unknown",
            )
            if cur is None:
                cur = {"start": ts, "end": ts, "key": key, "items": [row]}
                last_ts = ts
                continue
            gap = (ts - last_ts).total_seconds()
            if key == cur["key"] and gap <= grace_gap:
                cur["end"] = ts
                cur["items"].append(row)
            else:
                sessions.append(cur)
                cur = {"start": ts, "end": ts, "key": key, "items": [row]}
            last_ts = ts
        if cur:
            sessions.append(cur)
        return sessions

    def _session_summary(self, session: dict[str, Any]) -> dict[str, Any]:
        project, app, task = session["key"]
        return {
            "start": session["start"].isoformat(timespec="seconds"),
            "end": session["end"].isoformat(timespec="seconds"),
            "project": project,
            "app": app,
            "task": task,
            "summary": self._best_summary(session["items"]),
        }

    def _last_thread(self, session: dict[str, Any] | None) -> str:
        if not session:
            return "No recent activity found"
        project, app, task = session["key"]
        parts = [p for p in (project, task, app) if p and p != "Unknown"]
        return " / ".join(parts) if parts else self._best_summary(session["items"])

    def _working_on(
        self,
        session: dict[str, Any] | None,
        artifacts: list[str],
    ) -> list[str]:
        if not session:
            return []
        items = []
        for row in reversed(session["items"]):
            summary = row.get("summary") or row.get("window_title")
            if summary and summary not in items:
                items.append(summary)
            if len(items) >= 3:
                break
        for artifact in artifacts[:2]:
            label = f"Artifact: {artifact}"
            if label not in items:
                items.append(label)
        return items[:5]

    def _open_loops(self, rows: list[dict[str, Any]]) -> list[str]:
        loops = []
        for row in reversed(rows):
            text = " ".join(
                [
                    row.get("summary") or "",
                    row.get("window_title") or "",
                    " ".join(row.get("artifacts", [])),
                ]
            )
            lower = f" {text.lower()} "
            if any(term in lower for term in OPEN_LOOP_TERMS):
                item = row.get("summary") or row.get("window_title") or "Review recent item"
                if item not in loops:
                    loops.append(item)
        return loops

    def _artifacts(self, rows: list[dict[str, Any]]) -> list[str]:
        artifacts = []
        for row in reversed(rows):
            for artifact in row.get("artifacts", []):
                if artifact and artifact not in artifacts:
                    artifacts.append(artifact)
        return artifacts

    def _context_switches(self, sessions: list[dict[str, Any]]) -> list[str]:
        switches = []
        for prev, cur in zip(sessions, sessions[1:]):
            if prev["key"] == cur["key"]:
                continue
            prev_label = self._session_label(prev)
            cur_label = self._session_label(cur)
            switch = f"{cur['start'].strftime('%H:%M')} changed from {prev_label} to {cur_label}"
            switches.append(switch)
        return switches[-4:]

    def _low_confidence_items(self, rows: list[dict[str, Any]]) -> list[str]:
        threshold = float(getattr(self.config, "confidence_threshold", 0.65))
        items = []
        for row in reversed(rows):
            confidence = float(row.get("confidence") or 0.0)
            project = row.get("project") or "Unknown"
            task = row.get("coarse_task") or "Unknown"
            app = row.get("app") or "Unknown"
            if confidence < threshold or "Unknown" in {project, task, app}:
                summary = row.get("summary") or row.get("window_title") or "Unclear activity"
                label = f"{summary} ({confidence:.2f})"
                if label not in items:
                    items.append(label)
        return items

    def _next_action(
        self,
        session: dict[str, Any] | None,
        open_loops: list[str],
        artifacts: list[str],
    ) -> str:
        if open_loops:
            return f"Return to: {open_loops[0]}"
        if artifacts:
            return f"Open {artifacts[0]} and continue from the last captured context."
        if session:
            summary = self._best_summary(session["items"])
            return f"Resume: {summary}"
        return "Capture or backfill recent screenshots, then run `questlog resume` again."

    def _session_label(self, session: dict[str, Any]) -> str:
        project, app, task = session["key"]
        label = " / ".join(p for p in (project, task, app) if p and p != "Unknown")
        return label or self._best_summary(session["items"])

    def _best_summary(self, rows: list[dict[str, Any]]) -> str:
        summaries = [
            row.get("summary") or row.get("window_title") or ""
            for row in rows
            if row.get("summary") or row.get("window_title")
        ]
        if not summaries:
            return "Recent activity captured"
        return Counter(summaries).most_common(1)[0][0]

    def _bullet_lines(self, items: list[str], *, fallback: str) -> list[str]:
        if not items:
            return [f"- {fallback}"]
        return [f"- {item}" for item in items]
