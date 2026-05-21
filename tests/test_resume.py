import datetime as dt
import json
from types import SimpleNamespace

import requests

from questlog.services import DatabaseService, ExportService, ResumeService


def _insert_entry(
    conn,
    *,
    ts: dt.datetime,
    app: str = "Cursor",
    project: str | None = "Questlog",
    task: str = "Coding",
    summary: str = "Editing resume service",
    title: str = "resume.py",
    confidence: float = 0.9,
    artifacts: list[str] | None = None,
):
    payload = {
        "ts": ts.isoformat(timespec="seconds"),
        "app": app,
        "window_title": title,
        "project": project,
        "coarse_task": task,
        "summary": summary,
        "confidence": confidence,
        "artifacts": artifacts or [],
    }
    cur = conn.execute(
        """INSERT INTO entries (ts, app, window_title, project, coarse_task, summary, confidence, json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            payload["ts"],
            app,
            title,
            project,
            task,
            summary,
            confidence,
            json.dumps(payload),
        ),
    )
    return cur.lastrowid


def _service():
    return ResumeService(SimpleNamespace(grace_gap_seconds=120, confidence_threshold=0.65))


def test_resume_empty_window(tmp_path):
    db = DatabaseService(db_path=tmp_path / "test.db")
    db.ensure_schema()
    now = dt.datetime(2026, 5, 13, 12, tzinfo=dt.timezone.utc)

    with db.connect() as conn:
        data = _service().build_resume(conn, now=now)

    assert data["entry_count"] == 0
    assert data["last_thread"] == "No recent activity found"
    assert "No recent activity found" in _service().render_text(data)


def test_resume_identifies_recent_thread_and_artifact(tmp_path):
    db = DatabaseService(db_path=tmp_path / "test.db")
    db.ensure_schema()
    now = dt.datetime(2026, 5, 13, 12, tzinfo=dt.timezone.utc)

    with db.connect() as conn:
        _insert_entry(
            conn,
            ts=now - dt.timedelta(minutes=20),
            summary="Fixing resume service tests",
            artifacts=["questlog/services/resume.py"],
        )
        conn.commit()
        data = _service().build_resume(conn, now=now)

    assert data["last_thread"] == "Questlog / Coding / Cursor"
    assert "Fixing resume service tests" in data["working_on"]
    assert "Artifact: questlog/services/resume.py" in data["working_on"]
    assert data["next_action"].startswith("Return to:")


def test_resume_filters_noisy_artifacts_and_cleans_third_person_summary(tmp_path):
    db = DatabaseService(db_path=tmp_path / "test.db")
    db.ensure_schema()
    now = dt.datetime(2026, 5, 13, 12, tzinfo=dt.timezone.utc)

    with db.connect() as conn:
        _insert_entry(
            conn,
            ts=now - dt.timedelta(minutes=10),
            summary=(
                "The user appears to be working on a coding project, possibly involving "
                "code in a file named 'file.py'. They may also be engaged in research "
                "and communication activities."
            ),
            title="Assess ADHD user needs questlog",
            artifacts=["e.g", "questlog/services/resume.py"],
        )
        conn.commit()
        data = _service().build_resume(conn, now=now)

    rendered = _service().render_text(data)
    assert "The user appears" not in rendered
    assert "They may also" not in rendered
    assert "Assess ADHD user needs questlog" in rendered
    assert "Artifact: e.g" not in rendered
    assert "Artifact: questlog/services/resume.py" in rendered


def test_resume_reports_context_switches_and_low_confidence(tmp_path):
    db = DatabaseService(db_path=tmp_path / "test.db")
    db.ensure_schema()
    now = dt.datetime(2026, 5, 13, 12, tzinfo=dt.timezone.utc)

    with db.connect() as conn:
        _insert_entry(
            conn,
            ts=now - dt.timedelta(minutes=50),
            app="Slack",
            project=None,
            task="Comms",
            summary="Reviewing PR discussion",
            confidence=0.55,
        )
        _insert_entry(
            conn,
            ts=now - dt.timedelta(minutes=20),
            app="Cursor",
            project="Questlog",
            task="Coding",
            summary="Fixing timeout failure",
            confidence=0.9,
        )
        conn.commit()
        data = _service().build_resume(conn, now=now)

    assert data["context_switches"]
    assert any("Slack" in item and "Cursor" in item for item in data["context_switches"])
    assert any("Reviewing PR discussion" in item for item in data["low_confidence"])
    assert "Fixing timeout failure" in data["open_loops"]


def test_resume_restart_point_prefers_latest_thread_over_older_open_loop(tmp_path):
    db = DatabaseService(db_path=tmp_path / "test.db")
    db.ensure_schema()
    now = dt.datetime(2026, 5, 13, 12, tzinfo=dt.timezone.utc)

    with db.connect() as conn:
        _insert_entry(
            conn,
            ts=now - dt.timedelta(minutes=50),
            app="Visual Studio Code",
            project="Questlog",
            task="Coding",
            summary="Debugging old failing test",
        )
        _insert_entry(
            conn,
            ts=now - dt.timedelta(minutes=5),
            app="Visual Studio Code",
            project="Questlog",
            task="Coding",
            title="Assess ADHD user needs questlog",
            summary="The user appears to be working on a coding project, possibly involving code.",
        )
        conn.commit()
        data = _service().build_resume(conn, now=now)

    assert "Debugging old failing test" in data["open_loops"]
    assert data["next_action"] == "Resume: Assess ADHD user needs questlog"


def test_resume_filters_broad_open_loop_without_concrete_context(tmp_path):
    db = DatabaseService(db_path=tmp_path / "test.db")
    db.ensure_schema()
    now = dt.datetime(2026, 5, 13, 12, tzinfo=dt.timezone.utc)

    with db.connect() as conn:
        _insert_entry(
            conn,
            ts=now - dt.timedelta(minutes=20),
            app="Visual Studio Code",
            project="Questlog",
            task="Coding",
            title="Main Window Title",
            summary="Working on a software project using Visual Studio Code, likely developing or debugging code",
        )
        conn.commit()
        data = _service().build_resume(conn, now=now)

    assert data["open_loops"] == []


def test_resume_low_confidence_items_explain_quality_reasons(tmp_path):
    db = DatabaseService(db_path=tmp_path / "test.db")
    db.ensure_schema()
    now = dt.datetime(2026, 5, 13, 12, tzinfo=dt.timezone.utc)

    with db.connect() as conn:
        _insert_entry(
            conn,
            ts=now - dt.timedelta(minutes=20),
            app="AppName",
            project="Questlog",
            task="Coding",
            title="Main Window Title",
            summary="Working on a software project using various applications",
            confidence=0.9,
        )
        conn.commit()
        data = _service().build_resume(conn, now=now)

    assert data["low_confidence"]
    item = data["low_confidence"][0]
    assert "unknown app" in item
    assert "weak title" in item
    assert "generic summary" in item


def test_resume_open_loops_require_concrete_evidence(tmp_path):
    db = DatabaseService(db_path=tmp_path / "test.db")
    db.ensure_schema()
    now = dt.datetime(2026, 5, 13, 12, tzinfo=dt.timezone.utc)

    with db.connect() as conn:
        _insert_entry(
            conn,
            ts=now - dt.timedelta(minutes=30),
            app="Cursor",
            project="Questlog",
            task="Coding",
            title="Main Window Title",
            summary="Developing Python code, debugging in shell, possibly for project work",
            confidence=0.9,
        )
        _insert_entry(
            conn,
            ts=now - dt.timedelta(minutes=10),
            app="Cursor",
            project="Questlog",
            task="Test",
            title="resume.py",
            summary="Fixing failing resume tests",
            confidence=0.9,
            artifacts=["questlog/services/resume.py"],
        )
        conn.commit()
        data = _service().build_resume(conn, now=now)

    assert data["open_loops"] == ["Fixing failing resume tests"]


def test_resume_redacts_display_text(tmp_path):
    db = DatabaseService(db_path=tmp_path / "test.db")
    db.ensure_schema()
    now = dt.datetime(2026, 5, 13, 12, tzinfo=dt.timezone.utc)

    with db.connect() as conn:
        _insert_entry(
            conn,
            ts=now - dt.timedelta(minutes=5),
            summary="Checking jane@example.com token=abcd https://example.com/path?secret=1",
            title="4111-1111-1111-1111",
        )
        conn.commit()
        data = _service().build_resume(conn, now=now)

    rendered = _service().render_text(data)
    assert "jane@example.com" not in rendered
    assert "token=abcd" not in rendered
    assert "secret=1" not in rendered
    assert "4111-1111-1111-1111" not in rendered
    assert "[redacted-email]" in rendered


def test_hour_summary_prompt_uses_neutral_restart_language(tmp_path, monkeypatch):
    db = DatabaseService(db_path=tmp_path / "test.db")
    db.ensure_schema()
    now = dt.datetime(2026, 5, 13, 12, tzinfo=dt.timezone.utc)
    captured = {}

    class _Config:
        grace_gap_seconds = 120

        def to_dict(self):
            return {
                "ollama": {
                    "enabled": True,
                    "endpoint": "http://localhost:11434/api/generate",
                    "summarization": {"model": "test-model"},
                }
            }

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": "Neutral restart brief"}

    def _fake_post(url, json=None, timeout=30):
        captured["prompt"] = json["prompt"]
        return _Response()

    monkeypatch.setattr(requests, "post", _fake_post)

    with db.connect() as conn:
        _insert_entry(
            conn,
            ts=now,
            summary="Reviewing resume command",
        )
        conn.commit()
        result = ExportService(_Config()).generate_hour_summary(conn, now)

    prompt = captured["prompt"].lower()
    assert result == "Neutral restart brief"
    assert "restart brief" in prompt
    assert "open loops" in prompt
    assert "productivity" not in prompt
    assert "engagement" not in prompt
