"""Resume/re-entry service for recent Questlog activity."""

from __future__ import annotations

import datetime as dt
import json
import re
from collections import Counter
from typing import Any

from ql.processing import (
    ALLOWED_TASKS,
    is_generic_summary,
    is_placeholder_app,
    normalize_app,
    normalize_window_title,
)
from ql.text import redact_for_display
from ql.state_probes import (
    format_probe_summary,
    gather_state_probes,
    resolve_allowed_roots,
)


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

ARTIFACT_RE = re.compile(r"^[\w./~ -]+\.[A-Za-z0-9]{2,8}$")
GENERIC_SUMMARY_BITS = (
    "possibly involving",
    "may also be",
    "appears to be",
    "engaged in research and communication activities",
    "likely developing or debugging code",
    "software developer working on a project",
)
GENERIC_SUMMARY_EXACT = (
    "working on a coding project",
    "working on a coding project, working in code",
    "working on a software project",
    "recent activity captured",
)
THIRD_PERSON_PREFIXES = (
    "the user appears to be ",
    "the user is ",
    "the user was ",
    "a user is ",
    "a user was ",
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
        last_session_open_loops = self._open_loops(last_session["items"]) if last_session else []
        local_state = self._local_state(last_session, artifacts)

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
            "next_action": self._next_action(last_session, last_session_open_loops, artifacts),
            "low_confidence": low_confidence[:5],
            "local_state": local_state,
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

        if resume.get("local_state"):
            lines.append("")
            lines.append("Local state (read-only, may be stale):")
            lines.extend(self._bullet_lines(resume["local_state"], fallback="No local state observed."))

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
            item["app"] = normalize_app(item.get("app") or "")
            item["window_title"] = normalize_window_title(item.get("window_title") or "", item["app"])
            if item.get("coarse_task") not in ALLOWED_TASKS:
                item["coarse_task"] = "Unknown"
            item["summary"] = self._clean_summary(item.get("summary") or "")
            item["window_title"] = redact_for_display(item.get("window_title") or "")
            item["artifacts"] = []
            item["clues"] = {}
            if item.get("json"):
                try:
                    payload = json.loads(item["json"])
                    item["artifacts"] = self._clean_artifacts(payload.get("artifacts", []))
                    item["clues"] = payload.get("clues", {}) or {}
                except Exception:
                    item["artifacts"] = []
                    item["clues"] = {}
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
            summary = self._row_text(row)
            if summary and not self._is_weak_summary(summary) and summary not in items:
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
                    self._row_text(row),
                    row.get("window_title") or "",
                    " ".join(row.get("artifacts", [])),
                ]
            )
            lower = f" {text.lower()} "
            if any(term in lower for term in OPEN_LOOP_TERMS):
                item = self._row_text(row) or "Review recent item"
                if self._is_broad_activity(item):
                    continue
                if not self._has_concrete_context(row):
                    continue
                if not self._is_weak_summary(item) and item not in loops:
                    loops.append(item)
        return loops

    def _artifacts(self, rows: list[dict[str, Any]]) -> list[str]:
        artifacts = []
        for row in reversed(rows):
            for artifact in row.get("artifacts", []):
                if self._is_valid_artifact(artifact) and artifact not in artifacts:
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
            title = row.get("window_title") or ""
            summary = row.get("summary") or ""
            reasons = []
            if confidence < threshold:
                reasons.append(f"confidence {confidence:.2f}")
            if project == "Unknown":
                reasons.append("unknown project")
            if task == "Unknown":
                reasons.append("unknown task")
            if app == "Unknown" or is_placeholder_app(app):
                reasons.append("unknown app")
            if self._is_weak_title(title):
                reasons.append("weak title")
            if is_generic_summary(summary):
                reasons.append("generic summary")
            if reasons:
                summary = self._row_text(row) or "Unclear activity"
                label = f"{summary} ({', '.join(reasons)})"
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

    def _local_state(
        self,
        session: dict[str, Any] | None,
        artifacts: list[str],
    ) -> list[str]:
        probe_cfg = getattr(self.config, "state_probes", None)
        enabled = bool(getattr(probe_cfg, "enabled", False))
        if not enabled or not session:
            return []

        session_artifacts: list[str] = []
        session_clues: dict[str, Any] = {
            "urls": [],
            "domains": [],
            "repo_tokens": [],
            "tokens": [],
        }
        for row in session["items"]:
            session_artifacts.extend(row.get("artifacts", []))
            clues = row.get("clues") or {}
            for key in session_clues:
                session_clues[key].extend(clues.get(key, []))

        probes = gather_state_probes(
            session_artifacts or artifacts,
            session_clues,
            enabled=True,
            allowed_roots=resolve_allowed_roots(getattr(probe_cfg, "allowed_roots", None)),
            max_repos=int(getattr(probe_cfg, "max_repos", 2)),
            timeout_seconds=float(getattr(probe_cfg, "timeout_seconds", 5.0)),
        )
        return [format_probe_summary(probe) for probe in probes]

    def _session_label(self, session: dict[str, Any]) -> str:
        project, app, task = session["key"]
        label = " / ".join(p for p in (project, task, app) if p and p != "Unknown")
        return label or self._best_summary(session["items"])

    def _best_summary(self, rows: list[dict[str, Any]]) -> str:
        summaries = [
            self._row_text(row)
            for row in rows
            if self._row_text(row) and not self._is_weak_summary(self._row_text(row))
        ]
        if not summaries:
            return "Recent activity captured"
        return Counter(summaries).most_common(1)[0][0]

    def _bullet_lines(self, items: list[str], *, fallback: str) -> list[str]:
        if not items:
            return [f"- {fallback}"]
        return [f"- {item}" for item in items]

    def _clean_summary(self, value: str) -> str:
        summary = redact_for_display(value).strip()
        summary = re.sub(r"\s+", " ", summary)
        lower = summary.lower()

        for prefix in THIRD_PERSON_PREFIXES:
            if lower.startswith(prefix):
                summary = summary[len(prefix):].strip()
                if summary:
                    summary = summary[0].upper() + summary[1:]
                break

        # Keep the concrete first sentence when vision adds speculative follow-up.
        parts = re.split(r"(?<=[.!?])\s+", summary)
        if len(parts) > 1 and any(bit in lower for bit in GENERIC_SUMMARY_BITS):
            summary = parts[0]

        replacements = {
            "They may also be engaged in research and communication activities.": "",
            "possibly involving code in a file named 'file.py'": "working in code",
            "possibly involving code in a file named file.py": "working in code",
        }
        for old, new in replacements.items():
            summary = summary.replace(old, new)

        summary = summary.strip(" -.")
        return summary or "Recent activity captured"

    def _clean_artifacts(self, artifacts: list[Any]) -> list[str]:
        cleaned = []
        for artifact in artifacts:
            value = redact_for_display(str(artifact)).strip()
            if self._is_valid_artifact(value) and value not in cleaned:
                cleaned.append(value)
        return cleaned[:5]

    def _is_valid_artifact(self, value: str) -> bool:
        value = (value or "").strip()
        if len(value) < 5 or value.lower() in {"e.g", "i.e", "etc."}:
            return False
        if not ARTIFACT_RE.match(value):
            return False
        if value.lower().endswith((".com", ".org", ".net")):
            return False
        return True

    def _is_weak_summary(self, value: str) -> bool:
        norm = " ".join((value or "").strip().lower().split())
        if not norm:
            return True
        if norm in {"recent activity captured", "unknown", "using unknown"}:
            return True
        if norm in GENERIC_SUMMARY_EXACT:
            return True
        if any(bit in norm for bit in GENERIC_SUMMARY_BITS) and len(norm) > 120:
            return True
        return False

    def _row_text(self, row: dict[str, Any]) -> str:
        summary = row.get("summary") or ""
        title = row.get("window_title") or ""
        if (
            title
            and not self._is_weak_title(title)
            and self._is_weak_summary(summary)
        ):
            return title
        if (
            title
            and not self._is_weak_title(title)
            and self._is_generic_model_summary(summary)
        ):
            return title
        return summary or title

    def _is_generic_model_summary(self, value: str) -> bool:
        norm = " ".join((value or "").strip().lower().split())
        if norm in GENERIC_SUMMARY_EXACT:
            return True
        return any(bit in norm for bit in GENERIC_SUMMARY_BITS)

    def _is_weak_title(self, value: str) -> bool:
        norm = " ".join((value or "").strip().lower().split())
        return norm in {
            "",
            "unknown",
            "main window",
            "main window title",
            "google chrome",
            "chrome - google chrome",
        }

    def _has_concrete_context(self, row: dict[str, Any]) -> bool:
        title = row.get("window_title") or ""
        if title and not self._is_weak_title(title):
            return True
        if any(self._is_valid_artifact(a) for a in row.get("artifacts", [])):
            return True
        clues = row.get("clues") or {}
        if clues.get("urls") or clues.get("domains") or clues.get("repo_tokens"):
            return True
        text = f"{self._row_text(row)} {title}".lower()
        if self._is_broad_activity(text):
            return False
        return any(term in f" {text} " for term in OPEN_LOOP_TERMS)

    def _is_broad_activity(self, value: str) -> bool:
        norm = " ".join((value or "").strip().lower().split())
        broad_bits = (
            "working on a software project",
            "software developer working on a project",
            "collaborating on project",
            "developing python code",
            "developing and monitoring project progress",
            "focused on coding, with some communication activity",
        )
        return any(bit in norm for bit in broad_bits)
