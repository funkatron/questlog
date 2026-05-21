import types
import json
from pathlib import Path

import sys
from pathlib import Path as _P
sys.path.insert(0, str(_P(__file__).resolve().parents[1]))
from ql import processing as qlp
from ql import system as qls
from ql.text import redact, extract_clues
from ql.project import resolve_project
from ql.processing import (
    calibrate_confidence,
    normalize_app,
    normalize_window_title,
    process_image,
    validate_task,
)
from questlog.services import DatabaseService
from questlog.services.export import ExportService


def test_redact_email_and_numbers():
    s = "contact me at jane.doe@example.com or 4111-1111-1111-1111"
    r = redact(s)
    assert "[redacted-email]" in r
    assert "[redacted-num]" in r


def test_extract_clues_urls_and_tokens():
    lines = [
        "Check https://example.com/docs and repo my-project",
        "Another url http://sub.domain.tld/path",
    ]
    clues = extract_clues("Safari", "my-project — Code", lines)
    assert clues["urls"]
    assert any("example.com" in d for d in clues["domains"]) or any("domain.tld" in d for d in clues["domains"])
    # Hyphenated tokens are kept intact by extract_clues
    assert ("my-project" in clues["repo_tokens"]) or ("my" in clues["repo_tokens"]) or ("project" in clues["repo_tokens"])


def test_resolve_project_with_aliases():
    projects = ["Acme", "Zeus"]
    aliases = {"Acme": ["acme-api", "my-project"], "Zeus": ["hera"]}
    name, score = resolve_project(projects, aliases, "Working on acme-api", ["foo"], {"domains": [], "repo_tokens": ["acme", "api"]})
    assert name == "Acme"
    assert score > 0


def test_resolve_project_returns_none_for_weak_match():
    projects = ["Acme"]
    name, score = resolve_project(
        projects,
        {},
        "Reading unrelated notes",
        ["calendar agenda"],
        {"domains": [], "repo_tokens": []},
    )
    assert name is None
    assert score < 0.70


def test_quality_gate_normalizes_placeholders_and_tasks():
    assert normalize_app("AppName") == "Unknown"
    assert normalize_app("App2") == "Unknown"
    assert normalize_window_title("Main Window Title", "Cursor") == "Unknown"
    assert normalize_window_title("Google Chrome", "Google Chrome") == "Unknown"
    assert validate_task("Coding|Research|Build|Test", "Terminal", "pytest failed") == "Test"
    assert validate_task("Coding|Research|Build|Test", "Unknown", "") == "Unknown"


def test_confidence_calibration_caps_generic_high_confidence():
    confidence = calibrate_confidence(
        1.0,
        app="Unknown",
        window_title="Unknown",
        project=None,
        project_confidence=0.0,
        task="Unknown",
        summary="Working on a software project using various applications",
        clues={"urls": [], "domains": [], "repo_tokens": []},
        artifacts=[],
    )

    assert confidence <= 0.65


def test_confidence_calibration_rewards_concrete_evidence():
    confidence = calibrate_confidence(
        0.6,
        app="Cursor",
        window_title="resume.py — questlog",
        project="Questlog",
        project_confidence=0.95,
        task="Test",
        summary="Fixing failing resume tests",
        clues={"urls": ["https://github.com/funkatron/questlog/pull/1"], "domains": ["github.com"], "repo_tokens": ["questlog"]},
        artifacts=["questlog/services/resume.py"],
    )

    assert confidence >= 0.85


def test_sessionize_groups_by_key_and_gap():
    rows = [
        {"ts": "2025-01-01T10:00:00+00:00", "project": "P", "app": "A", "coarse_task": "Coding"},
        {"ts": "2025-01-01T10:01:00+00:00", "project": "P", "app": "A", "coarse_task": "Coding"},
        {"ts": "2025-01-01T10:10:00+00:00", "project": "P", "app": "A", "coarse_task": "Coding"},
    ]
    export_service = ExportService({"grace_gap_seconds": 120})
    sessions = export_service.sessionize(rows, grace_gap=120)
    assert len(sessions) == 2


def test_process_image_inserts_entry(tmp_path, monkeypatch):
    # Create a fake image file
    img = tmp_path / "shot.png"
    img.write_bytes(b"fake")

    # Stub dependencies at processing/system layer after refactor
    monkeypatch.setattr(qls, "ocr_lines", lambda p, n: ["Title Foo", "bar"])
    monkeypatch.setattr(qls, "front_app_info", lambda: {"app": "TestApp", "window_title": "Window Foo"})

    cfg = {
        "projects": ["TestProj"],
        "project_aliases": {"TestProj": ["foo"]},
        "max_ocr_lines": 12,
        "blocklist_apps": [],
    }

    # Use a temp DB
    db_service = DatabaseService(db_path=tmp_path / "test.db")
    db_service.ensure_schema()
    with db_service.connect() as conn:
        entry_id = process_image(conn, cfg, img)
        assert entry_id is not None
        cur = conn.execute("select project, app from entries where id=?", (entry_id,))
        row = cur.fetchone()
        assert row[0] == "TestProj"
        assert row[1] == "TestApp"


def test_process_image_can_skip_vision_and_llm(tmp_path, monkeypatch):
    img = tmp_path / "shot.png"
    img.write_bytes(b"fake")

    monkeypatch.setattr(qls, "ocr_with_easyocr", lambda p, n: ["questlog", "capture.py"])
    monkeypatch.setattr(qls, "ocr_with_llm", lambda cfg, p, n: ["should not be used"])
    monkeypatch.setattr(qls, "ocr_lines", lambda p, n: ["fallback"])
    monkeypatch.setattr(qls, "front_app_info", lambda: {"app": "Unknown", "window_title": "Unknown"})

    seen = {"vision": 0, "llm_summary_disabled": 0}

    def _fail_vision(cfg, path):
        seen["vision"] += 1
        raise AssertionError("vision path should be skipped")

    def _fake_summary(cfg, app, window_title, ocr_top, project_guess, clues, vision_result=None, use_llm=True):
        assert use_llm is False
        seen["llm_summary_disabled"] += 1
        return ("Working on questlog", "Coding", 0.7)

    monkeypatch.setattr(qls, "analyze_image_with_vision", _fail_vision)
    monkeypatch.setattr(qlp, "summarize", _fake_summary)

    cfg = {
        "projects": ["Questlog"],
        "project_aliases": {"Questlog": ["questlog"]},
        "max_ocr_lines": 12,
        "blocklist_apps": [],
    }

    db_service = DatabaseService(db_path=tmp_path / "test.db")
    db_service.ensure_schema()
    with db_service.connect() as conn:
        entry_id = process_image(
            conn,
            cfg,
            img,
            use_app_detection=False,
            use_vision_analysis=False,
            use_llm_summarization=False,
        )
        assert entry_id is not None
        cur = conn.execute("select project, app, summary from entries where id=?", (entry_id,))
        row = cur.fetchone()
        assert row[0] == "Questlog"
        assert row[1] == "Code"
        assert row[2]
        assert seen == {"vision": 0, "llm_summary_disabled": 1}


def test_process_image_auto_uses_vision_for_low_confidence_history(tmp_path, monkeypatch):
    img = tmp_path / "shot.png"
    img.write_bytes(b"fake")

    monkeypatch.setattr(qls, "ocr_with_easyocr", lambda p, n: [])
    monkeypatch.setattr(qls, "ocr_with_llm", lambda cfg, p, n: [])
    monkeypatch.setattr(qls, "ocr_lines", lambda p, n: [])
    monkeypatch.setattr(qls, "front_app_info", lambda: {"app": "Unknown", "window_title": "Unknown"})
    monkeypatch.setattr(
        qls,
        "analyze_image_with_vision",
        lambda cfg, path: {
            "primary_app": "Google Chrome",
            "primary_window_title": "questlog pull request",
            "project_indicators": ["questlog"],
            "summary": "Reviewing questlog changes in GitHub",
            "coarse_task": "Coding",
            "confidence": 0.9,
        },
    )

    cfg = {
        "projects": ["Questlog"],
        "project_aliases": {"Questlog": ["questlog"]},
        "max_ocr_lines": 12,
        "blocklist_apps": [],
        "confidence_threshold": 0.65,
    }

    db_service = DatabaseService(db_path=tmp_path / "test.db")
    db_service.ensure_schema()
    with db_service.connect() as conn:
        entry_id = process_image(
            conn,
            cfg,
            img,
            use_app_detection=False,
            use_vision_analysis=True,
            use_llm_summarization=False,
            vision_fallback_on_low_confidence=True,
        )
        cur = conn.execute("select project, app, summary, coarse_task from entries where id=?", (entry_id,))
        row = cur.fetchone()
        assert row[0] == "Questlog"
        assert row[1] == "Google Chrome"
        assert row[2] == "Reviewing questlog changes in GitHub"
        assert row[3] == "Coding"


def test_process_image_quality_gate_rejects_placeholder_vision_output(tmp_path, monkeypatch):
    img = tmp_path / "shot.png"
    img.write_bytes(b"fake")

    monkeypatch.setattr(qls, "ocr_with_easyocr", lambda p, n: [])
    monkeypatch.setattr(qls, "ocr_with_llm", lambda cfg, p, n: [])
    monkeypatch.setattr(qls, "ocr_lines", lambda p, n: [])
    monkeypatch.setattr(qls, "front_app_info", lambda: {"app": "Unknown", "window_title": "Unknown"})
    monkeypatch.setattr(
        qls,
        "analyze_image_with_vision",
        lambda cfg, path: {
            "primary_app": "AppName",
            "primary_window_title": "Main Window Title",
            "summary": "The user appears to be working on a coding or research project using various applications.",
            "coarse_task": "Coding|Research|Build|Test",
            "confidence": 1.0,
        },
    )

    cfg = {
        "projects": ["Questlog"],
        "project_aliases": {"Questlog": ["questlog"]},
        "max_ocr_lines": 12,
        "blocklist_apps": [],
        "confidence_threshold": 0.65,
        "project_match_threshold": 0.70,
    }

    db_service = DatabaseService(db_path=tmp_path / "test.db")
    db_service.ensure_schema()
    with db_service.connect() as conn:
        entry_id = process_image(
            conn,
            cfg,
            img,
            use_app_detection=False,
            use_vision_analysis=True,
            use_llm_summarization=False,
            vision_fallback_on_low_confidence=True,
        )
        cur = conn.execute("select app, window_title, coarse_task, confidence, summary from entries where id=?", (entry_id,))
        row = cur.fetchone()

    assert row[0] == "Unknown"
    assert row[1] == "Unknown"
    assert row[2] == "Unknown"
    assert row[3] <= 0.65
    assert not row[4].lower().startswith("the user appears")


def test_process_image_quality_gate_preserves_concrete_output(tmp_path, monkeypatch):
    img = tmp_path / "shot.png"
    img.write_bytes(b"fake")

    monkeypatch.setattr(qls, "ocr_with_easyocr", lambda p, n: ["pytest failed", "questlog/services/resume.py"])
    monkeypatch.setattr(qls, "ocr_with_llm", lambda cfg, p, n: [])
    monkeypatch.setattr(qls, "ocr_lines", lambda p, n: [])
    monkeypatch.setattr(qls, "front_app_info", lambda: {"app": "Unknown", "window_title": "Unknown"})
    monkeypatch.setattr(
        qls,
        "analyze_image_with_vision",
        lambda cfg, path: {
            "primary_app": "Cursor",
            "primary_window_title": "resume.py — questlog",
            "project_indicators": ["questlog"],
            "summary": "Fixing failing resume tests",
            "coarse_task": "Test",
            "confidence": 0.7,
        },
    )

    cfg = {
        "projects": ["Questlog"],
        "project_aliases": {"Questlog": ["questlog"]},
        "max_ocr_lines": 12,
        "blocklist_apps": [],
        "confidence_threshold": 0.65,
        "project_match_threshold": 0.70,
    }

    db_service = DatabaseService(db_path=tmp_path / "test.db")
    db_service.ensure_schema()
    with db_service.connect() as conn:
        entry_id = process_image(
            conn,
            cfg,
            img,
            use_app_detection=False,
            use_vision_analysis=True,
            use_llm_summarization=False,
            vision_fallback_on_low_confidence=True,
        )
        cur = conn.execute("select app, window_title, project, coarse_task, confidence, summary from entries where id=?", (entry_id,))
        row = cur.fetchone()

    assert row[0] == "Cursor"
    assert row[1] == "resume.py — questlog"
    assert row[2] == "Questlog"
    assert row[3] == "Test"
    assert row[4] >= 0.85
    assert row[5] == "Fixing failing resume tests"


def test_process_image_can_replace_existing_entry(tmp_path, monkeypatch):
    img = tmp_path / "shot.png"
    img.write_bytes(b"fake")

    monkeypatch.setattr(qls, "ocr_with_easyocr", lambda p, n: ["questlog", "resume.py"])
    monkeypatch.setattr(qls, "ocr_with_llm", lambda cfg, p, n: [])
    monkeypatch.setattr(qls, "ocr_lines", lambda p, n: [])
    monkeypatch.setattr(qls, "front_app_info", lambda: {"app": "Unknown", "window_title": "Unknown"})
    monkeypatch.setattr(qls, "analyze_image_with_vision", lambda cfg, path: {})

    cfg = {
        "projects": ["Questlog"],
        "project_aliases": {"Questlog": ["questlog"]},
        "max_ocr_lines": 12,
        "blocklist_apps": [],
        "confidence_threshold": 0.65,
        "project_match_threshold": 0.70,
    }

    db_service = DatabaseService(db_path=tmp_path / "test.db")
    db_service.ensure_schema()
    with db_service.connect() as conn:
        entry_id = process_image(
            conn,
            cfg,
            img,
            use_app_detection=False,
            use_vision_analysis=False,
            use_llm_summarization=False,
        )
        replaced_id = process_image(
            conn,
            cfg,
            img,
            use_app_detection=False,
            use_vision_analysis=False,
            use_llm_summarization=False,
            replace_entry_id=entry_id,
        )
        assert replaced_id == entry_id
        cur = conn.execute("select count(*) from entries")
        assert cur.fetchone()[0] == 1
        cur = conn.execute("select count(*) from evidence_fts where entry_id=?", (entry_id,))
        assert cur.fetchone()[0] == 1
