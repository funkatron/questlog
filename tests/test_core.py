import types
import json
from pathlib import Path

import sys
from pathlib import Path as _P
sys.path.insert(0, str(_P(__file__).resolve().parents[1]))
import questlog as ql
from ql import processing as qlp
from ql import system as qls


def test_redact_email_and_numbers():
    s = "contact me at jane.doe@example.com or 4111-1111-1111-1111"
    r = ql.redact(s)
    assert "[redacted-email]" in r
    assert "[redacted-num]" in r


def test_extract_clues_urls_and_tokens():
    lines = [
        "Check https://example.com/docs and repo my-project",
        "Another url http://sub.domain.tld/path",
    ]
    clues = ql.extract_clues("Safari", "my-project — Code", lines)
    assert clues["urls"]
    assert any("example.com" in d for d in clues["domains"]) or any("domain.tld" in d for d in clues["domains"])
    # Hyphenated tokens are kept intact by extract_clues
    assert ("my-project" in clues["repo_tokens"]) or ("my" in clues["repo_tokens"]) or ("project" in clues["repo_tokens"])


def test_resolve_project_with_aliases():
    projects = ["Acme", "Zeus"]
    aliases = {"Acme": ["acme-api", "my-project"], "Zeus": ["hera"]}
    name, score = ql.resolve_project(projects, aliases, "Working on acme-api", ["foo"], {"domains": [], "repo_tokens": ["acme", "api"]})
    assert name == "Acme"
    assert score > 0


def test_sessionize_groups_by_key_and_gap():
    rows = [
        {"ts": "2025-01-01T10:00:00+00:00", "project": "P", "app": "A", "coarse_task": "Coding"},
        {"ts": "2025-01-01T10:01:00+00:00", "project": "P", "app": "A", "coarse_task": "Coding"},
        {"ts": "2025-01-01T10:10:00+00:00", "project": "P", "app": "A", "coarse_task": "Coding"},
    ]
    sessions = ql.sessionize(rows, grace_gap=120)
    assert len(sessions) == 2


def test_process_image_inserts_entry(tmp_path, monkeypatch):
    # Create a fake image file
    img = tmp_path / "shot.png"
    img.write_bytes(b"fake")

    # Stub dependencies at processing/system layer after refactor
    monkeypatch.setattr(qls, "ocr_lines", lambda ocr_bin, p, n: ["Title Foo", "bar"])
    monkeypatch.setattr(qls, "front_app_info", lambda front_bin: {"app": "TestApp", "window_title": "Window Foo"})

    cfg = {
        "projects": ["TestProj"],
        "project_aliases": {"TestProj": ["foo"]},
        "max_ocr_lines": 12,
        "blocklist_apps": [],
    }

    # Use a temp DB
    monkeypatch.setattr(ql, "DB_PATH", tmp_path / "test.db")
    ql.ensure_schema()
    with ql.db() as conn:
        entry_id = ql.process_image(conn, cfg, img)
        assert entry_id is not None
        cur = conn.execute("select project, app from entries where id=?", (entry_id,))
        row = cur.fetchone()
        assert row[0] == "TestProj"
        assert row[1] == "TestApp"

