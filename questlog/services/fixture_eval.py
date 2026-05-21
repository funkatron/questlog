"""Fixture evaluation for screenshot processing quality checks."""

from __future__ import annotations

import datetime as dt
import json
import tempfile
from pathlib import Path
from typing import Any

import ql.processing as qlp

from questlog.services import DatabaseService


def norm_text(value: str) -> str:
    """Normalize text for loose fixture matching."""
    return " ".join((value or "").strip().lower().split())


def expand_expected_values(value: str) -> list[str]:
    """Expand loose alternatives like 'Safari or browser' into matchable values."""
    norm = (value or "").strip()
    if not norm:
        return []
    parts = [norm]
    if " or " in norm.lower():
        parts.extend(part.strip() for part in norm.split(" or ") if part.strip())
    return parts


def contains_any(haystack: str, needles: list[str]) -> bool:
    """Whether normalized haystack contains any normalized needle."""
    norm_haystack = norm_text(haystack)
    expanded: list[str] = []
    for needle in needles:
        expanded.extend(expand_expected_values(needle))
    return any(norm_text(needle) in norm_haystack for needle in expanded if needle)


def evaluate_fixture_result(target: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Compare one fixture result to its target expectations."""
    checks = []

    app_expected = [target.get("frontmost_app_hint", "")]
    checks.append(
        {
            "name": "app",
            "passed": contains_any(result.get("app", ""), app_expected),
            "expected": target.get("frontmost_app_hint", ""),
            "actual": result.get("app", ""),
        }
    )

    visible_expected = list(target.get("visible_apps", []))
    visible_actual = " ".join(
        [
            result.get("app", ""),
            result.get("window_title", ""),
            result.get("summary", ""),
        ]
    )
    checks.append(
        {
            "name": "visible_apps",
            "passed": contains_any(visible_actual, visible_expected),
            "expected": ", ".join(visible_expected),
            "actual": visible_actual,
        }
    )

    title_expected = [target.get("primary_window_title_hint", "")]
    title_expected.extend(target.get("window_title_hints", []))
    checks.append(
        {
            "name": "window_title",
            "passed": contains_any(result.get("window_title", ""), title_expected),
            "expected": target.get("primary_window_title_hint", ""),
            "actual": result.get("window_title", ""),
        }
    )

    activity_expected = [target.get("primary_activity", ""), target.get("target_description", "")]
    activity_expected.extend(target.get("activity_hints", []))
    activity_actual = " ".join([result.get("summary", ""), result.get("window_title", "")])
    checks.append(
        {
            "name": "activity",
            "passed": contains_any(activity_actual, activity_expected),
            "expected": target.get("primary_activity", ""),
            "actual": result.get("summary", ""),
        }
    )

    task_expected = [target.get("coarse_task_hint", "")]
    checks.append(
        {
            "name": "task",
            "passed": contains_any(result.get("coarse_task", ""), task_expected),
            "expected": target.get("coarse_task_hint", ""),
            "actual": result.get("coarse_task", ""),
        }
    )

    passed = sum(1 for check in checks if check["passed"])
    return {
        "passed_checks": passed,
        "total_checks": len(checks),
        "checks": checks,
    }


MODE_KWARGS = {
    "never": dict(
        use_vision_analysis=False,
        use_llm_summarization=False,
        vision_fallback_on_low_confidence=False,
    ),
    "auto": dict(
        use_vision_analysis=True,
        use_llm_summarization=False,
        vision_fallback_on_low_confidence=True,
    ),
    "always": dict(
        use_vision_analysis=True,
        use_llm_summarization=False,
        vision_fallback_on_low_confidence=False,
    ),
}


def run_process_image_mode(
    image_path: Path,
    cfg: Any,
    *,
    mode: str,
) -> dict[str, Any]:
    """Run the processing pipeline for one fixture and return the stored row."""
    if mode not in MODE_KWARGS:
        raise ValueError(f"Unsupported mode: {mode}")

    with tempfile.TemporaryDirectory(prefix="questlog-fixture-") as tmpdir:
        db_service = DatabaseService(db_path=Path(tmpdir) / "fixtures.db")
        db_service.ensure_schema()
        with db_service.connect() as conn:
            started = dt.datetime.now()
            timer_start = dt.datetime.now().timestamp()
            entry_id = qlp.process_image(
                conn,
                cfg.to_dict(),
                image_path,
                use_app_detection=False,
                **MODE_KWARGS[mode],
            )
            elapsed = dt.datetime.now().timestamp() - timer_start
            row = conn.execute(
                "select app, window_title, project, coarse_task, summary, confidence from entries where id=?",
                (entry_id,),
            ).fetchone()

    return {
        "file": image_path.name,
        "mode": mode,
        "seconds": round(elapsed, 2),
        "app": row[0],
        "window_title": row[1],
        "project": row[2],
        "coarse_task": row[3],
        "summary": row[4],
        "confidence": row[5],
        "evaluated_at": started.isoformat(timespec="seconds"),
    }


def load_fixture_manifest(targets_path: Path) -> dict[str, Any]:
    """Load and validate the fixture target manifest."""
    manifest = json.loads(targets_path.read_text(encoding="utf-8"))
    fixtures = manifest.get("fixtures", [])
    if not fixtures:
        raise ValueError(f"No fixtures found in {targets_path}")
    return manifest


def evaluate_fixtures(
    fixture_dir: Path,
    cfg: Any,
    *,
    mode: str = "never",
) -> dict[str, Any]:
    """Run fixture evaluation and return structured results."""
    targets_path = fixture_dir / "targets.json"
    manifest = load_fixture_manifest(targets_path)
    results: list[dict[str, Any]] = []

    for fixture in manifest["fixtures"]:
        image_path = fixture_dir / fixture["file"]
        if not image_path.exists():
            raise FileNotFoundError(f"Missing fixture image: {image_path}")
        result = run_process_image_mode(image_path, cfg, mode=mode)
        evaluation = evaluate_fixture_result(fixture, result)
        results.append(
            {
                "target": fixture,
                "result": result,
                "evaluation": evaluation,
            }
        )

    total_checks = sum(item["evaluation"]["total_checks"] for item in results)
    passed_checks = sum(item["evaluation"]["passed_checks"] for item in results)
    return {
        "fixture_dir": fixture_dir,
        "mode": mode,
        "results": results,
        "passed_checks": passed_checks,
        "total_checks": total_checks,
    }


def format_fixture_report(report: dict[str, Any]) -> str:
    """Render fixture evaluation results as Markdown."""
    lines: list[str] = []
    lines.append(f"# Fixture Evaluation ({report['mode']})")
    lines.append("")
    lines.append(f"**Generated:** {dt.datetime.now().astimezone().isoformat(timespec='seconds')}")
    lines.append(f"**Fixture Dir:** `{report['fixture_dir']}`")
    lines.append(f"**Checks Passed:** {report['passed_checks']}/{report['total_checks']}")
    lines.append("")
    lines.append("| Fixture | Score | Seconds | App | Task | Summary |")
    lines.append("| --- | --- | ---: | --- | --- | --- |")

    for item in report["results"]:
        result = item["result"]
        evaluation = item["evaluation"]
        lines.append(
            f"| `{result['file']}` | {evaluation['passed_checks']}/{evaluation['total_checks']} | "
            f"{result['seconds']:.2f} | {result['app']} | {result['coarse_task']} | {result['summary'][:80]} |"
        )

    lines.append("")
    for item in report["results"]:
        target = item["target"]
        result = item["result"]
        evaluation = item["evaluation"]
        lines.append(f"## {result['file']}")
        lines.append("")
        lines.append(f"**Target:** {target['target_description']}")
        lines.append(
            f"**Observed:** app=`{result['app']}`, title=`{result['window_title']}`, "
            f"task=`{result['coarse_task']}`, confidence={result['confidence']}"
        )
        lines.append(f"**Summary:** {result['summary']}")
        lines.append("")
        lines.append("| Check | Status | Expected | Actual |")
        lines.append("| --- | --- | --- | --- |")
        for check in evaluation["checks"]:
            status = "PASS" if check["passed"] else "FAIL"
            lines.append(
                f"| {check['name']} | {status} | {check['expected']} | {check['actual']} |"
            )
        if target.get("notes"):
            lines.append("")
            lines.append("Notes:")
            for note in target["notes"]:
                lines.append(f"- {note}")
        lines.append("")

    return "\n".join(lines)
