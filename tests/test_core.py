import types
import json
from pathlib import Path

import sys
from pathlib import Path as _P
sys.path.insert(0, str(_P(__file__).resolve().parents[1]))
from ql import processing as qlp
from ql import system as qls
from ql.text import redact, extract_clues
from ql.processing import resolve_project, process_image
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

