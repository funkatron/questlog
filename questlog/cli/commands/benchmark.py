"""Benchmark tool to show screenshot and collected information."""

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import typer

from questlog.config import load_config
from questlog.services import DatabaseService, ImageService, setup_logging
from questlog.services.fixture_eval import evaluate_fixtures, format_fixture_report

# Create command group
app = typer.Typer(name="benchmark", help="Benchmark and debug tools")

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def _format_markdown(data: dict, image_path: Path) -> str:
    """Format collected information as Markdown."""
    lines = []
    lines.append(f"# Benchmark Report: {image_path.name}")
    lines.append("")
    lines.append(f"**Generated:** {data.get('timestamp', 'N/A')}")
    lines.append("")

    # Image at the top
    lines.append("## Screenshot")
    lines.append("")
    # Use relative path if possible, otherwise absolute
    try:
        rel_path = image_path.relative_to(Path.cwd())
        lines.append(f"![Screenshot]({rel_path})")
    except ValueError:
        # If not relative, use absolute path
        lines.append(f"![Screenshot]({image_path})")
    lines.append("")

    # File info
    lines.append("## File Information")
    lines.append("")
    lines.append(f"- **Path:** `{data.get('file_path', 'N/A')}`")
    lines.append(f"- **Size:** {data.get('file_size', 'N/A')}")
    lines.append(f"- **Modified:** {data.get('timestamp', 'N/A')}")
    lines.append("")

    # OCR
    lines.append("## OCR Extraction")
    lines.append("")
    ocr_raw = data.get('ocr_raw', [])
    ocr_filtered = data.get('ocr_filtered', [])
    lines.append(f"**Raw OCR:** {len(ocr_raw)} lines")
    if ocr_raw:
        lines.append("")
        lines.append("```")
        for line in ocr_raw[:20]:
            lines.append(line)
        if len(ocr_raw) > 20:
            lines.append(f"... and {len(ocr_raw) - 20} more")
        lines.append("```")
        lines.append("")

    lines.append(f"**Filtered OCR:** {len(ocr_filtered)} lines")
    if ocr_filtered:
        lines.append("")
        lines.append("```")
        for line in ocr_filtered[:20]:
            lines.append(line)
        if len(ocr_filtered) > 20:
            lines.append(f"... and {len(ocr_filtered) - 20} more")
        lines.append("```")
        lines.append("")

    # Vision Analysis
    vision_result = data.get('vision_result', {})
    if vision_result:
        lines.append("## Vision Analysis (Primary)")
        lines.append("")
        lines.append(f"- **Primary App:** {vision_result.get('primary_app', 'Unknown')}")
        apps_visible = vision_result.get('apps_visible', [])
        if apps_visible:
            lines.append(f"- **Apps Visible:** {', '.join(apps_visible)}")
        lines.append(f"- **Primary Window Title:** `{vision_result.get('primary_window_title', 'Unknown')}`")
        window_titles = vision_result.get('window_titles', [])
        if window_titles:
            lines.append(f"- **Window Titles:** {', '.join([f'`{wt}`' for wt in window_titles])}")
        lines.append(f"- **Layout:** {vision_result.get('layout', 'N/A')}")
        layout_desc = vision_result.get('layout_description', '')
        if layout_desc:
            lines.append(f"- **Layout Description:** {layout_desc}")
        lines.append(f"- **Primary Activity:** {vision_result.get('primary_activity', 'N/A')}")
        secondary = vision_result.get('secondary_activities', [])
        if secondary:
            lines.append(f"- **Secondary Activities:** {', '.join(secondary)}")
        project_indicators = vision_result.get('project_indicators', [])
        if project_indicators:
            # Handle both string and dict formats
            indicator_strs = []
            for ind in project_indicators:
                if isinstance(ind, dict):
                    if 'url' in ind:
                        indicator_strs.append(ind['url'])
                    elif 'name' in ind:
                        indicator_strs.append(ind['name'])
                    elif 'path' in ind:
                        indicator_strs.append(ind['path'])
                    else:
                        indicator_strs.append(str(ind))
                else:
                    indicator_strs.append(str(ind))
            lines.append(f"- **Project Indicators:** {', '.join(indicator_strs)}")
        lines.append(f"- **Confidence:** {vision_result.get('confidence', 0.0):.2f}")
        lines.append("")

    # App detection
    lines.append("## App Detection")
    lines.append("")
    lines.append(f"- **App:** {data.get('app', 'Unknown')}")
    lines.append(f"- **Window Title:** `{data.get('window_title', 'Unknown')}`")
    lines.append(f"- **Method:** {data.get('detection_method', 'N/A')}")
    lines.append("")

    # Clues
    clues = data.get('clues', {})
    lines.append("## Extracted Clues")
    lines.append("")
    if clues.get('urls'):
        lines.append("**URLs:**")
        for url in clues.get('urls', []):
            lines.append(f"- {url}")
        lines.append("")
    if clues.get('domains'):
        lines.append("**Domains:**")
        for domain in clues.get('domains', []):
            lines.append(f"- {domain}")
        lines.append("")
    if clues.get('repo_tokens'):
        lines.append("**Repo Tokens:**")
        for token in clues.get('repo_tokens', [])[:10]:
            lines.append(f"- `{token}`")
        if len(clues.get('repo_tokens', [])) > 10:
            lines.append(f"- ... and {len(clues.get('repo_tokens', [])) - 10} more")
        lines.append("")

    # Project resolution
    lines.append("## Project Resolution")
    lines.append("")
    lines.append(f"- **Project:** {data.get('project', 'Unknown')}")
    lines.append(f"- **Confidence:** {data.get('project_confidence', 0.0):.2f}")
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Summary:** {data.get('summary', 'N/A')}")
    lines.append(f"- **Task:** `{data.get('coarse_task', 'Unknown')}`")
    lines.append(f"- **Confidence:** {data.get('confidence', 0.0):.2f}")
    lines.append("")

    # Artifacts
    artifacts = data.get('artifacts', [])
    if artifacts:
        lines.append("## Artifacts")
        lines.append("")
        for artifact in artifacts:
            lines.append(f"- `{artifact}`")
        lines.append("")

    # Full entry JSON
    lines.append("## Full Entry JSON")
    lines.append("")
    entry = data.get('entry', {})
    lines.append("```json")
    lines.append(json.dumps(entry, indent=2, ensure_ascii=False))
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


def _format_html(data: dict, image_path: Path) -> str:
    """Format collected information as HTML."""
    html = []
    html.append("<!DOCTYPE html>")
    html.append("<html>")
    html.append("<head>")
    html.append('<meta charset="UTF-8">')
    html.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    html.append(f"<title>Benchmark: {image_path.name}</title>")
    html.append("""
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            line-height: 1.6;
            color: #333;
        }
        h1 { color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }
        h2 { color: #34495e; margin-top: 30px; border-bottom: 1px solid #ecf0f1; padding-bottom: 5px; }
        code { background: #f4f4f4; padding: 2px 6px; border-radius: 3px; font-family: 'Monaco', 'Courier New', monospace; }
        pre { background: #f8f8f8; padding: 15px; border-radius: 5px; overflow-x: auto; border-left: 4px solid #3498db; }
        ul { list-style-type: none; padding-left: 0; }
        li { margin: 5px 0; padding-left: 20px; }
        li:before { content: "• "; color: #3498db; font-weight: bold; }
        .badge { display: inline-block; padding: 3px 8px; border-radius: 3px; font-size: 0.85em; }
        .badge-success { background: #2ecc71; color: white; }
        .badge-warning { background: #f39c12; color: white; }
        .badge-info { background: #3498db; color: white; }
        table { width: 100%; border-collapse: collapse; margin: 15px 0; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid #ecf0f1; }
        th { background: #ecf0f1; font-weight: 600; }
    </style>
    """)
    html.append("</head>")
    html.append("<body>")

    html.append(f'<h1>Benchmark Report: {image_path.name}</h1>')
    html.append(f'<p><strong>Generated:</strong> {data.get("timestamp", "N/A")}</p>')

    # File info
    html.append("<h2>File Information</h2>")
    html.append("<table>")
    html.append(f'<tr><th>Path</th><td><code>{data.get("file_path", "N/A")}</code></td></tr>')
    html.append(f'<tr><th>Size</th><td>{data.get("file_size", "N/A")}</td></tr>')
    html.append(f'<tr><th>Modified</th><td>{data.get("timestamp", "N/A")}</td></tr>')
    html.append("</table>")

    # OCR
    html.append("<h2>OCR Extraction</h2>")
    ocr_raw = data.get('ocr_raw', [])
    ocr_filtered = data.get('ocr_filtered', [])
    html.append(f'<p><strong>Raw OCR:</strong> {len(ocr_raw)} lines</p>')
    if ocr_raw:
        html.append("<pre>")
        html.append("\n".join(ocr_raw[:20]))
        if len(ocr_raw) > 20:
            html.append(f"\n... and {len(ocr_raw) - 20} more")
        html.append("</pre>")

    html.append(f'<p><strong>Filtered OCR:</strong> {len(ocr_filtered)} lines</p>')
    if ocr_filtered:
        html.append("<pre>")
        html.append("\n".join(ocr_filtered[:20]))
        if len(ocr_filtered) > 20:
            html.append(f"\n... and {len(ocr_filtered) - 20} more")
        html.append("</pre>")

    # Vision Analysis
    vision_result = data.get('vision_result', {})
    if vision_result:
        html.append("<h2>Vision Analysis (Primary)</h2>")
        html.append("<table>")
        html.append(f'<tr><th>Primary App</th><td>{vision_result.get("primary_app", "Unknown")}</td></tr>')
        apps_visible = vision_result.get('apps_visible', [])
        if apps_visible:
            html.append(f'<tr><th>Apps Visible</th><td>{", ".join(apps_visible)}</td></tr>')
        html.append(f'<tr><th>Primary Window Title</th><td><code>{vision_result.get("primary_window_title", "Unknown")}</code></td></tr>')
        window_titles = vision_result.get('window_titles', [])
        if window_titles:
            html.append(f'<tr><th>Window Titles</th><td>{", ".join([f"<code>{wt}</code>" for wt in window_titles])}</td></tr>')
        html.append(f'<tr><th>Layout</th><td>{vision_result.get("layout", "N/A")}</td></tr>')
        layout_desc = vision_result.get('layout_description', '')
        if layout_desc:
            html.append(f'<tr><th>Layout Description</th><td>{layout_desc}</td></tr>')
        html.append(f'<tr><th>Primary Activity</th><td>{vision_result.get("primary_activity", "N/A")}</td></tr>')
        secondary = vision_result.get('secondary_activities', [])
        if secondary:
            html.append(f'<tr><th>Secondary Activities</th><td>{", ".join(secondary)}</td></tr>')
        project_indicators = vision_result.get('project_indicators', [])
        if project_indicators:
            # Handle both string and dict formats
            indicator_strs = []
            for ind in project_indicators:
                if isinstance(ind, dict):
                    if 'url' in ind:
                        indicator_strs.append(ind['url'])
                    elif 'name' in ind:
                        indicator_strs.append(ind['name'])
                    elif 'path' in ind:
                        indicator_strs.append(ind['path'])
                    else:
                        indicator_strs.append(str(ind))
                else:
                    indicator_strs.append(str(ind))
            html.append(f'<tr><th>Project Indicators</th><td>{", ".join(indicator_strs)}</td></tr>')
        conf = vision_result.get('confidence', 0.0)
        badge_class = 'badge-success' if conf > 0.7 else 'badge-warning' if conf > 0.4 else 'badge-info'
        html.append(f'<tr><th>Confidence</th><td><span class="badge {badge_class}">{conf:.2f}</span></td></tr>')
        html.append("</table>")

    # App detection
    html.append("<h2>App Detection</h2>")
    html.append("<table>")
    html.append(f'<tr><th>App</th><td>{data.get("app", "Unknown")}</td></tr>')
    html.append(f'<tr><th>Window Title</th><td><code>{data.get("window_title", "Unknown")}</code></td></tr>')
    html.append(f'<tr><th>Method</th><td>{data.get("detection_method", "N/A")}</td></tr>')
    html.append("</table>")

    # Clues
    clues = data.get('clues', {})
    html.append("<h2>Extracted Clues</h2>")
    if clues.get('urls'):
        html.append("<h3>URLs</h3><ul>")
        for url in clues.get('urls', []):
            html.append(f'<li><a href="{url}" target="_blank">{url}</a></li>')
        html.append("</ul>")
    if clues.get('domains'):
        html.append("<h3>Domains</h3><ul>")
        for domain in clues.get('domains', []):
            html.append(f'<li><code>{domain}</code></li>')
        html.append("</ul>")
    if clues.get('repo_tokens'):
        html.append("<h3>Repo Tokens</h3><ul>")
        for token in clues.get('repo_tokens', [])[:10]:
            html.append(f'<li><code>{token}</code></li>')
        if len(clues.get('repo_tokens', [])) > 10:
            html.append(f'<li>... and {len(clues.get("repo_tokens", [])) - 10} more</li>')
        html.append("</ul>")

    # Project resolution
    html.append("<h2>Project Resolution</h2>")
    html.append("<table>")
    html.append(f'<tr><th>Project</th><td>{data.get("project", "Unknown")}</td></tr>')
    conf = data.get('project_confidence', 0.0)
    badge_class = 'badge-success' if conf > 0.7 else 'badge-warning' if conf > 0.4 else 'badge-info'
    html.append(f'<tr><th>Confidence</th><td><span class="badge {badge_class}">{conf:.2f}</span></td></tr>')
    html.append("</table>")

    # Summary
    html.append("<h2>Summary</h2>")
    html.append("<table>")
    html.append(f'<tr><th>Summary</th><td>{data.get("summary", "N/A")}</td></tr>')
    html.append(f'<tr><th>Task</th><td><code>{data.get("coarse_task", "Unknown")}</code></td></tr>')
    conf = data.get('confidence', 0.0)
    badge_class = 'badge-success' if conf > 0.7 else 'badge-warning' if conf > 0.4 else 'badge-info'
    html.append(f'<tr><th>Confidence</th><td><span class="badge {badge_class}">{conf:.2f}</span></td></tr>')
    html.append("</table>")

    # Artifacts
    artifacts = data.get('artifacts', [])
    if artifacts:
        html.append("<h2>Artifacts</h2>")
        html.append("<ul>")
        for artifact in artifacts:
            html.append(f'<li><code>{artifact}</code></li>')
        html.append("</ul>")

    # Full entry JSON
    html.append("<h2>Full Entry JSON</h2>")
    entry = data.get('entry', {})
    html.append("<pre><code>")
    html.append(json.dumps(entry, indent=2, ensure_ascii=False))
    html.append("</code></pre>")

    html.append("</body>")
    html.append("</html>")

    return "\n".join(html)


def _process_single_image(image_path: Path, cfg, image_service: ImageService) -> dict:
    """Process a single image and return collected info."""
    # Get file info
    mtime = image_path.stat().st_mtime
    timestamp = dt.datetime.fromtimestamp(mtime).astimezone().isoformat(timespec="seconds")

    # PRIMARY: Vision-based analysis
    import ql.system as qls
    from ql.text import redact, filter_ocr_cruft, extract_clues, find_artifacts
    import ql.processing as qlp

    vision_result = qls.analyze_image_with_vision(cfg.to_dict(), image_path)
    vision_available = bool(vision_result)

    # SUPPLEMENTAL: Extract OCR (EasyOCR -> LLM OCR -> Tesseract)
    max_ocr_lines = cfg.max_ocr_lines
    ocr_raw = qls.ocr_with_easyocr(image_path, max_ocr_lines)
    if not ocr_raw:
        ocr_raw = qls.ocr_with_llm(cfg.to_dict(), image_path, max_ocr_lines)
    if not ocr_raw:
        ocr_raw = qls.ocr_lines(image_path, max_ocr_lines)

    ocr_filtered = filter_ocr_cruft(ocr_raw)
    redacted = [redact(line) for line in ocr_filtered]

    # Use vision results if available, otherwise infer from OCR
    if vision_available:
        app = vision_result.get("primary_app", "Unknown")
        window_title = vision_result.get("primary_window_title", "Unknown")
        detection_method = "vision_analysis"
    else:
        # Infer app and window title from OCR
        window_title = "Unknown"
        if redacted:
            for line in redacted:
                line_stripped = line.strip()
                if line_stripped and len(line_stripped) > 3:
                    window_title = line_stripped[:80]
                    break
        app = qlp.infer_app_from_content(window_title, redacted)
        detection_method = "ocr_inference"

    # Extract clues
    clues = extract_clues(app, window_title, redacted)

    # Merge vision project indicators with OCR clues
    if vision_available and vision_result.get("project_indicators"):
        vision_projects = vision_result.get("project_indicators", [])
        for proj_indicator in vision_projects:
            if "github.com" in proj_indicator or "http" in proj_indicator:
                if "urls" not in clues:
                    clues["urls"] = []
                if proj_indicator not in clues["urls"]:
                    clues["urls"].append(proj_indicator)

    # Resolve project
    proj_guess = qlp.resolve_project(
        cfg.projects,
        cfg.project_aliases,
        window_title,
        redacted,
        clues,
        cfg.project_match_threshold,
    )

    # Generate summary (use vision summary if available)
    if vision_available and vision_result.get("summary"):
        summary = vision_result.get("summary", "")
        coarse_task = vision_result.get("coarse_task", "Unknown")
        confidence = vision_result.get("confidence", 0.5)
    else:
        summary, coarse_task, confidence = qlp.summarize(
            cfg.to_dict(), app, window_title, redacted, proj_guess, clues, vision_result if vision_available else None
        )

    # Find artifacts
    artifacts = find_artifacts(window_title, redacted)

    # Build entry
    entry = {
        "ts": timestamp,
        "app": app,
        "window_title": window_title,
        "project": proj_guess[0],
        "coarse_task": coarse_task,
        "summary": summary,
        "artifacts": artifacts,
        "tags": [],
        "confidence": confidence,
        "clues": clues,
    }

    # Collect all info
    info = {
        "file_path": str(image_path),
        "file_size": f"{image_path.stat().st_size:,} bytes",
        "timestamp": timestamp,
        "vision_result": vision_result if vision_available else {},
        "ocr_raw": ocr_raw,
        "ocr_filtered": ocr_filtered,
        "app": app,
        "window_title": window_title,
        "detection_method": "inferred from content",
        "clues": clues,
        "project": proj_guess[0],
        "project_confidence": proj_guess[1],
        "summary": summary,
        "coarse_task": coarse_task,
        "confidence": confidence,
        "artifacts": artifacts,
        "entry": entry,
    }

    return info


def _generate_period_summary(benchmark_files: List[Path], period_start: dt.datetime, period_end: dt.datetime) -> str:
    """Generate a summary markdown for a time period from benchmark files."""
    lines = []
    lines.append(f"# Period Summary: {period_start.strftime('%Y-%m-%d %H:%M')} - {period_end.strftime('%H:%M')}")
    lines.append("")
    lines.append(f"**Duration:** {period_start.strftime('%Y-%m-%d %H:%M')} to {period_end.strftime('%H:%M')}")
    lines.append(f"**Images Processed:** {len(benchmark_files)}")
    lines.append("")

    # Collect data from all benchmark files
    activities = []
    projects = set()
    tasks = set()
    apps = set()

    for bm_file in benchmark_files:
        try:
            # Read the markdown file and extract key info
            content = bm_file.read_text()

            # Extract summary, task, project from markdown
            import re
            summary_match = re.search(r'\*\*Summary:\*\* (.+)', content)
            task_match = re.search(r'\*\*Task:\*\* `(.+)`', content)
            project_match = re.search(r'\*\*Project:\*\* (.+)', content)
            app_match = re.search(r'\*\*App:\*\* (.+)', content)

            if summary_match:
                activities.append({
                    "summary": summary_match.group(1),
                    "task": task_match.group(1) if task_match else "Unknown",
                    "project": project_match.group(1) if project_match else "Unknown",
                    "app": app_match.group(1) if app_match else "Unknown",
                    "file": bm_file.stem.replace("_benchmark", ""),
                })
                if project_match:
                    projects.add(project_match.group(1))
                if task_match:
                    tasks.add(task_match.group(1))
                if app_match:
                    apps.add(app_match.group(1))
        except Exception as e:
            continue

    # Summary statistics
    lines.append("## Summary Statistics")
    lines.append("")
    lines.append(f"- **Total Activities:** {len(activities)}")
    lines.append(f"- **Projects:** {', '.join(sorted(projects)) or 'Unknown'}")
    lines.append(f"- **Tasks:** {', '.join(sorted(tasks)) or 'Unknown'}")
    lines.append(f"- **Apps:** {', '.join(sorted(apps)) or 'Unknown'}")
    lines.append("")

    # Group by task
    lines.append("## Activities by Task")
    lines.append("")
    task_groups = {}
    for act in activities:
        task = act["task"]
        if task not in task_groups:
            task_groups[task] = []
        task_groups[task].append(act)

    for task, acts in sorted(task_groups.items()):
        lines.append(f"### {task} ({len(acts)} activities)")
        lines.append("")
        for act in acts[:10]:  # Limit to 10 per task
            lines.append(f"- {act['summary']} *(Project: {act['project']}, App: {act['app']})*")
        if len(acts) > 10:
            lines.append(f"- ... and {len(acts) - 10} more")
        lines.append("")

    # Group by project
    lines.append("## Activities by Project")
    lines.append("")
    project_groups = {}
    for act in activities:
        project = act["project"]
        if project not in project_groups:
            project_groups[project] = []
        project_groups[project].append(act)

    for project, acts in sorted(project_groups.items()):
        lines.append(f"### {project} ({len(acts)} activities)")
        lines.append("")
        for act in acts[:10]:
            lines.append(f"- {act['summary']} *(Task: {act['task']})*")
        if len(acts) > 10:
            lines.append(f"- ... and {len(acts) - 10} more")
        lines.append("")

    return "\n".join(lines)


@app.command(name="eval-fixtures")
def eval_fixtures(
    directory: str = typer.Option(
        "tests/fixtures/screenshots",
        "--directory",
        "-d",
        help="Fixture directory containing images and targets.json",
    ),
    mode: str = typer.Option(
        "never",
        "--mode",
        help="Processing mode to evaluate: never, auto, or always",
    ),
    output: str = typer.Option(
        "exports/fixture_eval.md",
        "--output",
        "-o",
        help="Markdown report output path",
    ),
) -> None:
    """Run the processing pipeline against local fixtures and compare to targets."""
    cfg = load_config()
    setup_logging(cfg, debug=True)

    fixture_dir = Path(directory)
    targets_path = fixture_dir / "targets.json"
    if not fixture_dir.exists():
        typer.echo(f"Fixture directory not found: {fixture_dir}", err=True)
        raise typer.Exit(1)
    if not targets_path.exists():
        typer.echo(f"Target manifest not found: {targets_path}", err=True)
        raise typer.Exit(1)

    mode = mode.lower().strip()
    if mode not in {"never", "auto", "always"}:
        typer.echo("Invalid --mode. Expected one of: never, auto, always.", err=True)
        raise typer.Exit(2)

    for fixture in json.loads(targets_path.read_text()).get("fixtures", []):
        image_path = fixture_dir / fixture["file"]
        if not image_path.exists():
            typer.echo(f"Missing fixture image: {image_path}", err=True)
            raise typer.Exit(1)
        typer.echo(f"Evaluating {image_path.name} ({mode})...")

    report = evaluate_fixtures(fixture_dir, cfg, mode=mode)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(format_fixture_report(report))
    typer.echo(
        f"Wrote fixture evaluation report: {output_path} "
        f"({report['passed_checks']}/{report['total_checks']} checks passed)"
    )


@app.command()
def show(
    image: str = typer.Argument(None, help="Path to screenshot image or directory"),
    directory: str = typer.Option(None, "--directory", "-d", help="Directory to scan for images"),
    open_image: bool = typer.Option(False, "--open", help="Open image in default viewer"),
) -> None:
    """Show screenshot and all collected information, or process a directory of images."""
    cfg = load_config()
    setup_logging(cfg, debug=True)
    image_service = ImageService(cfg)

    # Determine if we're processing a directory or single image
    if directory:
        scan_dir = Path(directory)
    elif image:
        scan_path = Path(image)
        if scan_path.is_dir():
            scan_dir = scan_path
        else:
            scan_dir = None
    else:
        typer.echo("Error: Must provide either an image path or --directory", err=True)
        raise typer.Exit(1)

    if scan_dir:
        # Process directory
        if not scan_dir.exists():
            typer.echo(f"Directory not found: {scan_dir}", err=True)
            raise typer.Exit(1)

        # Find all images
        image_files = sorted(scan_dir.rglob("*.jpg")) + sorted(scan_dir.rglob("*.png")) + sorted(scan_dir.rglob("*.jpeg"))
        typer.echo(f"Found {len(image_files)} images in {scan_dir}")

        # Group by 30-minute periods
        period_groups: Dict[dt.datetime, List[Path]] = {}
        benchmark_files_by_period: Dict[dt.datetime, List[Path]] = {}

        for img_file in image_files:
            mtime = img_file.stat().st_mtime
            img_time = dt.datetime.fromtimestamp(mtime).astimezone()
            # Round down to nearest 30 minutes
            period_start = img_time.replace(minute=(img_time.minute // 30) * 30, second=0, microsecond=0)

            if period_start not in period_groups:
                period_groups[period_start] = []
            period_groups[period_start].append(img_file)

        # Process images and generate summaries
        for period_start in sorted(period_groups.keys()):
            images_in_period = period_groups[period_start]
            period_end = period_start + dt.timedelta(minutes=30)

            typer.echo(f"\nProcessing period: {period_start.strftime('%Y-%m-%d %H:%M')} - {period_end.strftime('%H:%M')} ({len(images_in_period)} images)")

            benchmark_files = []
            for img_file in images_in_period:
                try:
                    # Check if benchmark already exists
                    bm_file = img_file.parent / f"{img_file.stem}_benchmark.md"
                    if bm_file.exists():
                        typer.echo(f"  Skipping {img_file.name} (benchmark exists)")
                        benchmark_files.append(bm_file)
                        continue

                    typer.echo(f"  Processing {img_file.name}...")
                    info = _process_single_image(img_file, cfg, image_service)

                    # Generate markdown
                    output_text = _format_markdown(info, img_file)
                    bm_file.write_text(output_text)
                    benchmark_files.append(bm_file)
                    typer.echo(f"    ✓ Saved benchmark")
                except Exception as e:
                    typer.echo(f"    ✗ Error: {e}", err=True)

            # Generate period summary
            if benchmark_files:
                typer.echo(f"\n  Generating period summary...")
                summary_text = _generate_period_summary(benchmark_files, period_start, period_end)
                summary_file = scan_dir / f"summary_{period_start.strftime('%Y-%m-%d_%H-%M')}.md"
                summary_file.write_text(summary_text)
                typer.echo(f"  ✓ Saved period summary: {summary_file.name}")

        typer.echo(f"\n✓ Completed processing {len(image_files)} images")
        return

    # Single image processing
    image_path = Path(image)
    if not image_path.exists():
        typer.echo(f"Image not found: {image_path}", err=True)
        raise typer.Exit(1)

    cfg = load_config()
    setup_logging(cfg, debug=True)
    db_service = DatabaseService()
    image_service = ImageService(cfg)

    # Open image if requested
    if open_image and HAS_PIL:
        try:
            img = Image.open(image_path)
            img.show()
        except Exception as e:
            typer.echo(f"Could not open image: {e}", err=True)
    elif open_image:
        import subprocess
        import platform
        try:
            if platform.system() == "Darwin":
                subprocess.run(["open", str(image_path)])
            elif platform.system() == "Linux":
                subprocess.run(["xdg-open", str(image_path)])
            elif platform.system() == "Windows":
                subprocess.run(["start", str(image_path)], shell=True)
        except Exception as e:
            typer.echo(f"Could not open image: {e}", err=True)

    # Process image to collect info
    typer.echo(f"\nProcessing: {image_path.name}\n")

    info = _process_single_image(image_path, cfg, image_service)

    # Generate output - always use markdown for visual image+summary
    output_text = _format_markdown(info, image_path)
    output_file = image_path.parent / f"{image_path.stem}_benchmark.md"

    # Save to file
    output_file.write_text(output_text)

    # Display summary
    typer.echo(f"\n✓ Processed: {image_path.name}")
    typer.echo(f"✓ Saved benchmark report to: {output_file}")
    typer.echo(f"\nThe markdown file includes the image and all collected information.")
    typer.echo(f"View it in any markdown viewer or editor to see the image alongside the summary.")
