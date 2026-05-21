import datetime as dt
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from ql.state_probes import (
    collect_probe_candidates,
    find_git_root,
    format_probe_summary,
    gather_state_probes,
    is_path_allowed,
    probe_git_repository,
    resolve_allowed_roots,
)
from questlog.services import DatabaseService, ResumeService


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True, capture_output=True)


def test_collect_probe_candidates_from_artifacts_and_clues():
    candidates = collect_probe_candidates(
        ["questlog/services/resume.py"],
        {"tokens": ["docs/plan.md"], "repo_tokens": ["questlog"]},
    )
    paths = [str(path) for path in candidates]
    assert "questlog/services/resume.py" in paths
    assert "docs/plan.md" in paths
    assert "questlog" not in paths


def test_find_git_root_walks_up_from_nested_file(tmp_path):
    repo = tmp_path / "repo"
    nested = repo / "src" / "pkg"
    nested.mkdir(parents=True)
    _init_git_repo(repo)

    found = find_git_root(nested / "module.py")
    assert found == repo.resolve()


def test_is_path_allowed_respects_roots(tmp_path):
    allowed = [tmp_path.resolve()]
    inside = tmp_path / "inside.txt"
    inside.write_text("x")
    outside = Path("/tmp") / "outside.txt"

    assert is_path_allowed(inside, allowed) is True
    if outside.exists():
        assert is_path_allowed(outside, allowed) is False


def test_probe_git_repository_reports_branch_and_dirty_state(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("hello world\n")

    probe = probe_git_repository(repo)

    assert probe["branch"] in {"main", "master"}
    assert probe["clean"] is False
    assert "README.md" in probe["status_summary"]
    assert probe["confidence"] == "observed"
    rendered = format_probe_summary(probe)
    assert str(repo) in rendered
    assert "observed" in rendered


def test_gather_state_probes_skips_paths_outside_allowed_roots(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    nested = repo / "pkg"
    nested.mkdir(parents=True)
    _init_git_repo(repo)
    outside = tmp_path / "outside" / "file.py"
    outside.parent.mkdir(parents=True)
    outside.write_text("x")

    monkeypatch.chdir(tmp_path)
    probes = gather_state_probes(
        [str(outside)],
        {},
        enabled=True,
        allowed_roots=[repo.resolve()],
    )
    assert probes == []


def test_gather_state_probes_finds_repo_from_artifact(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    nested = repo / "questlog" / "services"
    nested.mkdir(parents=True)
    _init_git_repo(repo)
    artifact = nested / "resume.py"
    artifact.write_text("# file\n")

    monkeypatch.chdir(repo)
    probes = gather_state_probes(
        [str(artifact)],
        {},
        enabled=True,
        allowed_roots=resolve_allowed_roots([str(repo)]),
    )

    assert len(probes) == 1
    assert probes[0]["repo"] == str(repo.resolve())


def _insert_entry(conn, *, ts, artifacts=None, clues=None):
    payload = {
        "ts": ts.isoformat(timespec="seconds"),
        "app": "Cursor",
        "window_title": "resume.py",
        "project": "Questlog",
        "coarse_task": "Coding",
        "summary": "Editing resume service",
        "confidence": 0.9,
        "artifacts": artifacts or [],
        "clues": clues or {},
    }
    conn.execute(
        """INSERT INTO entries (ts, app, window_title, project, coarse_task, summary, confidence, json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            payload["ts"],
            payload["app"],
            payload["window_title"],
            payload["project"],
            payload["coarse_task"],
            payload["summary"],
            payload["confidence"],
            json.dumps(payload),
        ),
    )


def test_resume_includes_local_state_when_probes_enabled(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    nested = repo / "questlog" / "services"
    nested.mkdir(parents=True)
    _init_git_repo(repo)
    artifact = nested / "resume.py"
    artifact.write_text("# file\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    db = DatabaseService(db_path=tmp_path / "test.db")
    db.ensure_schema()
    now = dt.datetime(2026, 5, 13, 12, tzinfo=dt.timezone.utc)
    cfg = SimpleNamespace(
        grace_gap_seconds=120,
        confidence_threshold=0.65,
        state_probes=SimpleNamespace(
            enabled=True,
            allowed_roots=[str(repo)],
            max_repos=2,
            timeout_seconds=5.0,
        ),
    )

    monkeypatch.chdir(repo)
    with db.connect() as conn:
        _insert_entry(
            conn,
            ts=now - dt.timedelta(minutes=5),
            artifacts=[str(artifact)],
        )
        conn.commit()
        data = ResumeService(cfg).build_resume(conn, now=now)

    assert data["local_state"]
    rendered = ResumeService(cfg).render_text(data)
    assert "Local state (read-only, may be stale):" in rendered
    assert str(repo.resolve()) in rendered


def test_resume_omits_local_state_when_probes_disabled(tmp_path):
    db = DatabaseService(db_path=tmp_path / "test.db")
    db.ensure_schema()
    now = dt.datetime(2026, 5, 13, 12, tzinfo=dt.timezone.utc)
    cfg = SimpleNamespace(
        grace_gap_seconds=120,
        confidence_threshold=0.65,
        state_probes=SimpleNamespace(enabled=False, allowed_roots=[], max_repos=2, timeout_seconds=5.0),
    )

    with db.connect() as conn:
        _insert_entry(conn, ts=now - dt.timedelta(minutes=5), artifacts=["questlog/services/resume.py"])
        conn.commit()
        data = ResumeService(cfg).build_resume(conn, now=now)

    assert data["local_state"] == []
    assert "Local state" not in ResumeService(cfg).render_text(data)
