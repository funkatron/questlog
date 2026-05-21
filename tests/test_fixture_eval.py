import json
from pathlib import Path

import pytest

from questlog.cli.commands.benchmark import _evaluate_fixture_result


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "screenshots"
TARGETS_PATH = FIXTURE_DIR / "targets.json"


def _load_manifest() -> dict:
    return json.loads(TARGETS_PATH.read_text(encoding="utf-8"))


def test_targets_manifest_is_valid():
    manifest = _load_manifest()
    assert manifest.get("version") == 1
    fixtures = manifest.get("fixtures", [])
    assert len(fixtures) >= 5
    for fixture in fixtures:
        assert fixture.get("file")
        assert fixture.get("target_description")
        assert fixture.get("coarse_task_hint")


@pytest.mark.parametrize("fixture", _load_manifest()["fixtures"], ids=lambda item: item["file"])
def test_fixture_images_exist(fixture):
    image_path = FIXTURE_DIR / fixture["file"]
    if not image_path.exists():
        pytest.skip(f"Fixture image not present locally: {image_path}")
    assert image_path.stat().st_size > 0


def test_evaluate_fixture_result_passes_on_ideal_output():
    manifest = _load_manifest()
    target = manifest["fixtures"][0]
    result = {
        "app": target["frontmost_app_hint"],
        "window_title": target["primary_window_title_hint"],
        "coarse_task": target["coarse_task_hint"],
        "summary": target["primary_activity"],
        "confidence": 0.9,
    }
    evaluation = _evaluate_fixture_result(target, result)
    assert evaluation["passed_checks"] == evaluation["total_checks"]


def test_evaluate_fixture_result_flags_wrong_app():
    manifest = _load_manifest()
    target = manifest["fixtures"][0]
    result = {
        "app": "Totally Wrong App",
        "window_title": target["primary_window_title_hint"],
        "coarse_task": target["coarse_task_hint"],
        "summary": target["primary_activity"],
        "confidence": 0.9,
    }
    evaluation = _evaluate_fixture_result(target, result)
    app_check = next(check for check in evaluation["checks"] if check["name"] == "app")
    assert app_check["passed"] is False


def test_fixture_pipeline_never_mode_writes_entry(tmp_path, monkeypatch):
    manifest = _load_manifest()
    fixture = manifest["fixtures"][3]  # cursor-editor-terminal.jpg
    image_path = FIXTURE_DIR / fixture["file"]
    if not image_path.exists():
        pytest.skip(f"Fixture image not present locally: {image_path}")

    import ql.processing as qlp
    import ql.system as qls
    from questlog.services import DatabaseService

    monkeypatch.setattr(
        qls,
        "ocr_with_easyocr",
        lambda path, max_lines: [
            "Cursor",
            "resume.py — questlog",
            "Terminal",
            "pytest",
        ],
    )
    monkeypatch.setattr(qls, "ocr_with_llm", lambda cfg, path, max_lines: [])
    monkeypatch.setattr(qls, "ocr_lines", lambda path, max_lines: [])
    monkeypatch.setattr(qls, "front_app_info", lambda: {"app": "Unknown", "window_title": "Unknown"})

    def _fail_vision(cfg, path):
        raise AssertionError("vision should be disabled in never mode")

    monkeypatch.setattr(qls, "analyze_image_with_vision", _fail_vision)

    cfg = {
        "projects": ["Questlog"],
        "project_aliases": {"Questlog": ["questlog"]},
        "max_ocr_lines": 12,
        "blocklist_apps": [],
        "confidence_threshold": 0.65,
        "project_match_threshold": 0.70,
    }

    db_service = DatabaseService(db_path=tmp_path / "fixtures.db")
    db_service.ensure_schema()
    with db_service.connect() as conn:
        entry_id = qlp.process_image(
            conn,
            cfg,
            image_path,
            use_app_detection=False,
            use_vision_analysis=False,
            use_llm_summarization=False,
        )
        row = conn.execute(
            "select app, coarse_task, summary from entries where id=?",
            (entry_id,),
        ).fetchone()

    assert row is not None
    evaluation = _evaluate_fixture_result(
        fixture,
        {
            "app": row[0],
            "window_title": "Cursor",
            "coarse_task": row[1],
            "summary": row[2],
            "confidence": 0.8,
        },
    )
    assert evaluation["passed_checks"] >= 3
