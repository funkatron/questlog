#!/usr/bin/env python3
"""Questlog CLI - Activity logging from screenshots.

This module provides the command-line interface for Questlog, including
commands for capturing screenshots, processing images, and exporting logs.
"""

import argparse
import csv
import datetime as dt
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional, Iterable

import requests
import yaml
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

import ql.db as qldb
import ql.processing as qlp
import ql.system as qls
from ql.processing import guess_task, resolve_project, summarize
from ql.text import build_ollama_prompt, extract_clues, find_artifacts, redact

# Configuration paths
CONFIG_PATH = Path("config.yaml")
DB_PATH = Path("questlog.db")
BIN_FRONTAPP = Path("bin/frontapp")
BIN_OCR = Path("bin/ocrshot")

# Supported image file extensions
IMAGE_EXTS = {".png", ".jpg", ".jpeg"}

logger = logging.getLogger("questlog")


def setup_logging(cfg: Dict[str, Any]) -> None:
    """Configure logging for the application.

    Sets up a rotating file handler based on configuration. Clears existing
    handlers to avoid duplicates if called multiple times.

    Args:
        cfg: Configuration dictionary with logfile, log_max_bytes, log_backups.
    """
    logger.setLevel(logging.INFO)
    # Avoid duplicate handlers if setup_logging is called multiple times
    if logger.handlers:
        logger.handlers.clear()
    logger.propagate = False
    logfile = cfg.get("logfile", "questlog.log")
    handler = RotatingFileHandler(
        logfile,
        maxBytes=cfg.get("log_max_bytes", 1_048_576),
        backupCount=cfg.get("log_backups", 2),
    )
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def load_config() -> Dict[str, Any]:
    """Load configuration from config.yaml.

    Returns:
        Configuration dictionary parsed from YAML file.

    Raises:
        FileNotFoundError: If config.yaml doesn't exist.
        yaml.YAMLError: If config file is invalid YAML.
    """
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def db() -> sqlite3.Connection:
    """Get a database connection.

    Returns:
        SQLite connection to the questlog database.
    """
    return qldb.connect(DB_PATH)


def front_app_info() -> Dict[str, str]:
    """Get information about the frontmost application.

    Returns:
        Dictionary with app name, bundle_id, and window_title.
    """
    return qls.front_app_info(BIN_FRONTAPP)


def ocr_lines(path: Path, max_lines: int) -> List[str]:
    """Extract text lines from an image using OCR.

    Args:
        path: Path to the image file.
        max_lines: Maximum number of lines to return.

    Returns:
        List of OCR-extracted text lines.
    """
    lines = qls.ocr_lines(BIN_OCR, path, max_lines)
    if not lines and not BIN_OCR.exists():
        logger.warning("ocr binary missing at %s", BIN_OCR)
    return lines


def init_db() -> None:
    """Initialize the database schema and print confirmation."""
    qldb.ensure_schema(Path("schema.sql").read_text(), DB_PATH)
    print("Initialized DB at", DB_PATH)


def ensure_schema() -> None:
    """Ensure database schema exists without printing output."""
    qldb.ensure_schema(Path("schema.sql").read_text(), DB_PATH)

def ensure_today_dir(base_folder: Path) -> Path:
    from datetime import date
    today_dir = base_folder / date.today().strftime("%Y-%m-%d")
    today_dir.mkdir(parents=True, exist_ok=True)
    return today_dir

def already_processed(conn: sqlite3.Connection, path: str) -> bool:
    return qldb.already_processed(conn, path)

def store_file_record(conn: sqlite3.Connection, path: str, mtime: float, entry_id: int) -> None:
    qldb.store_file_record(conn, path, mtime, entry_id)

def insert_entry(conn: sqlite3.Connection, entry: dict, evidence_text: str, file_path: str, mtime: float) -> int:
    return qldb.insert_entry(conn, entry, evidence_text, file_path, mtime)

def build_historian_prompt(ocr_lines: List[str]) -> str:
    ocr_block = "\n".join(ocr_lines)
    return (
    "You are an activity historian. Analyze the OCR text from a screenshot and write a detailed account of what the user was doing, suitable for a work log.\n\n"
    "Return Markdown only (no preface, no extra commentary), using exactly these section headings:\n\n"
    "## What was happening\n- A clear description of the user’s primary task (what they were doing) in 2–4 sentences.\n\n"
    "## Why (likely intent)\n- Briefly explain the plausible goal(s) driving this task.\n\n"
    "## Sub‑tasks and steps\n- Bullet list of concrete actions or sub‑steps visible or strongly implied.\n\n"
    "## Evidence (from the screenshot)\n- 4–8 bullets citing specific on‑screen cues (UI labels, titles, text snippets, filenames, domains). Quote exact text where useful.\n\n"
    "## Tools and context\n- App(s) in focus and any notable services/sites. If multiple apps are visible, only name one as “in focus” if unambiguous; otherwise write “Unclear.”\n- Any visible files, repos, docs, or environments (quote exact names).\n\n"
    "## Related project(s)\n- Short project/repo/doc names if strongly indicated; otherwise “Unknown”.\n\n"
    "## Time and scope estimate\n- Rough estimate of how long this kind of task block would take (e.g., “~10–20 minutes”), based only on what’s visible.\n\n"
    "## Uncertainties\n- List any ambiguities and what additional signals would resolve them.\n\n"
    "## Likely next actions\n- 3–5 bullets of what the user would logically do next.\n\n"
    "Rules:\n- Be concrete and rely only on what’s visible.\n- Do not infer editor/tool names unless visible; quote exact window/tab text when naming tools.\n- If something is unclear, say so under “Uncertainties.”\n- Keep the narrative precise and useful for future review.\n\n"
    f"OCR:\n{ocr_block}\n"
    )

def process_image(conn: sqlite3.Connection, cfg: dict, file_path: Path) -> Optional[int]:
    return qlp.process_image(conn, cfg, file_path, BIN_FRONTAPP, BIN_OCR)

def iter_images(base_folder: Path) -> Iterable[Path]:
    return qlp.iter_images(base_folder)

class ShotHandler(FileSystemEventHandler):
    def __init__(self, cfg):
        self.cfg = cfg

    def _process_path(self, p: Path):
        if p.suffix.lower() not in IMAGE_EXTS:
            return
        # Give writers a moment to finish
        time.sleep(0.3)
        try:
            with db() as conn:
                if already_processed(conn, str(p)):
                    return
                logger.info("watch event processing: %s", p)
                process_image(conn, self.cfg, p)
        except Exception as e:
            logger.error("watch error on %s: %s", p, e)

    def on_created(self, event):
        if event.is_directory:
            return
        p = Path(event.src_path)
        self._process_path(p)

    def on_modified(self, event):
        if event.is_directory:
            return
        p = Path(event.src_path)
        self._process_path(p)

    def on_moved(self, event):
        if event.is_directory:
                return
        # Destination path is where the file ends up
        p = Path(getattr(event, 'dest_path', event.src_path))
        self._process_path(p)

def cmd_init_db(args: argparse.Namespace) -> None:
    init_db()

def cmd_backfill(args: argparse.Namespace) -> None:
    cfg = load_config()
    setup_logging(cfg)
    base = Path(cfg["base_folder"]).expanduser()
    cutoff = None
    if args.days is not None:
        cutoff = time.time() - (args.days * 86400)
    ensure_schema()
    with db() as conn:
        count = 0
        for p in sorted(iter_images(base)):
            try:
                if cutoff and p.stat().st_mtime < cutoff:
                    continue
                if already_processed(conn, str(p)):
                    continue
                process_image(conn, cfg, p)
                count += 1
                if count % 50 == 0:
                    print(f"Processed {count} files...")
            except Exception as e:
                logger.error("backfill error on %s: %s", p, e)
        print(f"Backfill complete. Processed {count} new screenshots. See {cfg.get('logfile','questlog.log')} for details.")

def cmd_watch(args: argparse.Namespace) -> None:
    cfg = load_config()
    setup_logging(cfg)
    base = Path(cfg["base_folder"]).expanduser()
    if not base.exists():
        print("Base folder does not exist:", base, file=sys.stderr)
        sys.exit(2)
    ensure_schema()
    event_handler = ShotHandler(cfg)
    obs = Observer()
    obs.schedule(event_handler, str(base), recursive=True)
    obs.start()
    print("Watching:", base)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        obs.stop()
        obs.join()

def sessionize(rows: List[dict], grace_gap: int = 120) -> List[dict]:
    sessions = []
    cur = None
    last_ts = None
    for r in rows:
        t = dt.datetime.fromisoformat(r["ts"])
        key = (r["project"], r["app"], r["coarse_task"])
        if cur is None:
            cur = {"start": t, "end": t, "key": key, "items": [r]}
            last_ts = t
            continue
        delta = (t - last_ts).total_seconds()
        if key == cur["key"] and delta <= grace_gap:
            cur["end"] = t
            cur["items"].append(r)
        else:
            sessions.append(cur)
            cur = {"start": t, "end": t, "key": key, "items": [r]}
        last_ts = t
    if cur:
        sessions.append(cur)
    return sessions

def cmd_export_md(args: argparse.Namespace) -> None:
    date = args.date
    cfg = load_config()
    with db() as conn:
        cur = conn.execute("""
            SELECT id, ts, app, window_title, project, coarse_task, summary, confidence
            FROM entries
            WHERE date(ts) = ?
            ORDER BY ts ASC
        """, (date,))
        rows = [dict(r) for r in cur.fetchall()]

    sessions = sessionize(rows, grace_gap=cfg.get("grace_gap_seconds", 120))

    md_lines = [f"# Quest Log — {date}", ""]
    for s in sessions:
        proj, app, task = s["key"]
        start = s["start"].strftime("%H:%M:%S")
        end = s["end"].strftime("%H:%M:%S")
        md_lines.append(f"## {start}–{end} • {task or 'Unknown'} • {proj or 'Unknown'} • {app}")
        md_lines.append("")
        for it in s["items"]:
            t = dt.datetime.fromisoformat(it["ts"]).strftime("%H:%M:%S")
            md_lines.append(f"- {t} — {it['summary']} *(conf: {it['confidence']:.2f})*")
        md_lines.append("")

    out_dir = Path("exports")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"questlog_{date}.md"
    out_path.write_text("\n".join(md_lines))
    print("Wrote", out_path)

def cmd_export_csv(args: argparse.Namespace) -> None:
    date = args.date
    with db() as conn:
        cur = conn.execute("""
            SELECT ts, app, window_title, project, coarse_task, summary, confidence
            FROM entries
            WHERE date(ts) = ?
            ORDER BY ts ASC
        """, (date,))
        rows = [dict(r) for r in cur.fetchall()]

    out_dir = Path("exports")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"questlog_{date}.csv"
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ts","app","window_title","project","coarse_task","summary","confidence"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    print("Wrote", out_path)

def cmd_snap(args: argparse.Namespace) -> None:
    cfg = load_config()
    setup_logging(cfg)
    base = Path(cfg["base_folder"]).expanduser()
    ensure_schema()
    today_dir = ensure_today_dir(base)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = today_dir / f"questlog_snap_{ts}.png"
    try:
        subprocess.run(["screencapture", "-x", str(out_path)], check=True)
    except subprocess.CalledProcessError as e:
        print("screencapture failed:", e, file=sys.stderr)
        print("If prompted, grant Screen Recording permission to your terminal.", file=sys.stderr)
        sys.exit(2)
    except FileNotFoundError:
        print("screencapture tool not found. This command requires macOS.", file=sys.stderr)
        sys.exit(2)

    with db() as conn:
        try:
            entry_id = process_image(conn, cfg, out_path)
        except Exception as e:
            logger.error("snap index failed: %s", e)
            entry_id = None
    print("Captured:", out_path)
    if entry_id:
        print("Indexed entry_id:", entry_id)

def cmd_doctor(args: argparse.Namespace) -> None:
    cfg = load_config()
    ok = True

    print("== QuestLog Doctor ==")
    print("Base folder:", cfg.get("base_folder"))
    base = Path(cfg.get("base_folder","")).expanduser()
    if not base.exists():
        print("  [!] base_folder does not exist.")
        ok = False
    else:
        # Check YYYY-MM-DD subdir exists
        from datetime import date
        today_dir = base / date.today().strftime("%Y-%m-%d")
        print("  Today subdir:", today_dir, "(exists:", today_dir.exists(), ")")

    # Binaries
    print("Frontapp binary:", BIN_FRONTAPP, "(exists:", BIN_FRONTAPP.exists(), ")")
    print("OCR binary:", BIN_OCR, "(exists:", BIN_OCR.exists(), ")")
    if not BIN_FRONTAPP.exists() or not BIN_OCR.exists():
        print("  [i] One or more Swift helpers missing. You can still run with degraded features.")

    # Try front app info (Swift binary if available, else AppleScript fallback)
    try:
        meta = front_app_info()
        print("  front app info; app:", meta.get("app"), "title:", meta.get("window_title"))
        if meta.get("window_title","Unknown") == "Unknown":
            print("  [i] Window title is 'Unknown' — check Accessibility permission for your terminal.")
    except Exception as e:
        print("  [!] front app info failed:", e)
        ok = False

    # Try OCR on any one file
    test_file = None
    if base.exists():
        for root, dirs, files in os.walk(base):
            for name in files:
                p = Path(root) / name
                if p.suffix.lower() in IMAGE_EXTS:
                    test_file = p
                    break
            if test_file: break
    if test_file and BIN_OCR.exists():
        try:
            lines = ocr_lines(test_file, cfg.get("max_ocr_lines",12))
            print(f"  OCR ok; {len(lines)} lines from {test_file.name}")
        except Exception as e:
            print("  [!] OCR test failed:", e)
            ok = False
    else:
        print("  [i] OCR sanity check skipped (no sample image or ocr helper missing).")

    print("Doctor result:", "OK" if ok else "Issues found. See README and questlog.log for guidance.")

def cmd_analyze_now(args: argparse.Namespace) -> None:
    cfg = load_config()
    setup_logging(cfg)
    base = Path(cfg["base_folder"]).expanduser()
    ensure_schema()
    today_dir = ensure_today_dir(base)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    shot = today_dir / f"questlog_snap_{ts}.png"
    try:
        subprocess.run(["screencapture", "-x", str(shot)], check=True)
    except Exception as e:
        print("screencapture failed:", e, file=sys.stderr)
        sys.exit(2)

    meta = front_app_info()
    app = meta.get("app", "Unknown")
    window_title = meta.get("window_title", "Unknown")
    ocr_top_raw = ocr_lines(shot, cfg.get("max_ocr_lines", 12))
    redacted = [redact(l) for l in ocr_top_raw]
    clues = extract_clues(app, window_title, redacted)
    proj_guess = resolve_project(cfg.get("projects", []), cfg.get("project_aliases", {}), window_title, redacted, clues)
    summary, coarse_task, confidence = summarize(cfg, app, window_title, redacted, proj_guess, clues)
    artifacts = find_artifacts(window_title, redacted)

    out = {
        "app": app,
        "window_title": window_title,
        "ocr_top": redacted,
        "clues": clues,
        "project": proj_guess[0],
        "coarse_task": coarse_task,
        "summary": summary,
        "confidence": confidence,
        "artifacts": artifacts,
        "image": str(shot),
    }
    print(json.dumps(out, ensure_ascii=False))

def cmd_what_image(args: argparse.Namespace) -> None:
    cfg = load_config()
    setup_logging(cfg)
    img = Path(args.image).expanduser()
    if not img.exists():
        print("Image not found:", img, file=sys.stderr)
        sys.exit(2)

    ocr_top = ocr_lines(img, cfg.get("max_ocr_lines", 40))
    prompt = build_historian_prompt(ocr_top)

    # Provider: OpenAI (if enabled) else Ollama generate
    text = ""
    try:
        if (cfg.get("openai", {}) or {}).get("enabled", False):
            if getattr(args, "vision", False):
                raise RuntimeError("--vision is not implemented for OpenAI in this command. Enable Ollama or omit --vision.")
            api_key_env = cfg["openai"].get("api_key_env", "OPENAI_API_KEY")
            api_key = os.environ.get(api_key_env)
            if not api_key:
                raise RuntimeError(f"Missing OpenAI API key in env var {api_key_env}")
            api_base = cfg["openai"].get("api_base", "https://api.openai.com/v1").rstrip("/")
            model = cfg["openai"].get("model", "gpt-4o-mini")
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            body = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
            }
            r = requests.post(f"{api_base}/chat/completions", headers=headers, json=body, timeout=60)
            r.raise_for_status()
            data = r.json() or {}
            choices = data.get("choices", [])
            if choices:
                text = (choices[0].get("message") or {}).get("content", "").strip()
        else:
            endpoint_cfg = cfg["ollama"].get("endpoint", "http://localhost:11434")
            gen_url = endpoint_cfg if endpoint_cfg.endswith("/api/generate") else endpoint_cfg.rstrip("/") + "/api/generate"
            model = cfg["ollama"].get("model", "mistral:latest")
            payload = {"model": model, "prompt": prompt, "stream": False}
            if getattr(args, "vision", False):
                payload["images"] = [str(img)]
            r = requests.post(gen_url, json=payload, timeout=60)
            r.raise_for_status()
            text = (r.json() or {}).get("response", "").strip()
    except Exception as e:
        print("Historian failed:", e, file=sys.stderr)
        sys.exit(1)

    out_dir = Path("exports"); out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"historian_{img.stem}.md"
    out_path.write_text(text or "(no response)")
    print("Wrote", out_path)

def cmd_analyze_file(args: argparse.Namespace) -> None:
    cfg = load_config()
    setup_logging(cfg)
    img = Path(args.image).expanduser()
    if not img.exists():
        print("Image not found:", img, file=sys.stderr)
        sys.exit(2)

    meta = front_app_info()
    app = meta.get("app", "Unknown")
    window_title = meta.get("window_title", "Unknown")
    ocr_top_raw = ocr_lines(img, cfg.get("max_ocr_lines", 12))
    redacted = [redact(l) for l in ocr_top_raw]
    clues = extract_clues(app, window_title, redacted)
    proj_guess = resolve_project(cfg.get("projects", []), cfg.get("project_aliases", {}), window_title, redacted, clues)
    summary, coarse_task, confidence = summarize(cfg, app, window_title, redacted, proj_guess, clues)
    artifacts = find_artifacts(window_title, redacted)

    out = {
        "app": app,
        "window_title": window_title,
        "ocr_top": redacted,
        "clues": clues,
        "project": proj_guess[0],
        "coarse_task": coarse_task,
        "summary": summary,
        "confidence": confidence,
        "artifacts": artifacts,
        "image": str(img),
    }
    print(json.dumps(out, ensure_ascii=False))

def cmd_capture(args: argparse.Namespace) -> None:
    cfg = load_config()
    setup_logging(cfg)
    base = Path(cfg["base_folder"]).expanduser()
    ensure_schema()
    interval = max(5, int(args.interval))
    print(f"Capturing every {interval}s. Press Ctrl+C to stop.")
    try:
        while True:
            ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            today_dir = ensure_today_dir(base)
            shot = today_dir / f"questlog_snap_{ts}.png"
            try:
                subprocess.run(["screencapture", "-x", str(shot)], check=True)
                with db() as conn:
                    process_image(conn, cfg, shot)
            except Exception as e:
                logger.error("capture cycle failed: %s", e)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("Stopped continuous capture.")

def main() -> None:
    ap = argparse.ArgumentParser(prog="questlog")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("init-db", help="Initialize the SQLite database")
    p1.set_defaults(func=lambda args: init_db())

    p2 = sub.add_parser("backfill", help="Scan historical screenshots and index them")
    p2.add_argument("--days", type=int, help="Only process last N days")
    p2.set_defaults(func=cmd_backfill)

    p3 = sub.add_parser("watch", help="Watch the folder for new screenshots")
    p3.set_defaults(func=cmd_watch)

    p4 = sub.add_parser("export-md", help="Export a daily Markdown timeline")
    p4.add_argument("--date", required=True, help="YYYY-MM-DD")
    p4.set_defaults(func=cmd_export_md)

    p5 = sub.add_parser("export-csv", help="Export a daily CSV")
    p5.add_argument("--date", required=True, help="YYYY-MM-DD")
    p5.set_defaults(func=cmd_export_csv)

    p6 = sub.add_parser("doctor", help="Run environment and config checks")
    p6.set_defaults(func=cmd_doctor)

    p7 = sub.add_parser("snap", help="Capture a screenshot and index it")
    p7.set_defaults(func=cmd_snap)


    p9 = sub.add_parser("capture", help="Continuously capture screenshots at an interval and index them")
    p9.add_argument("--interval", type=int, default=60, help="Seconds between captures (default: 60)")
    p9.set_defaults(func=cmd_capture)
    p8 = sub.add_parser("analyze-now", help="Capture and print a one-off JSON analysis (no DB write)")
    p8.set_defaults(func=cmd_analyze_now)

    p10 = sub.add_parser("analyze-file", help="Analyze an existing screenshot image (no DB write)")
    p10.add_argument("image", help="Path to screenshot image")
    p10.set_defaults(func=cmd_analyze_file)

    p11 = sub.add_parser("what-image", help="Generate historian Markdown for an image (OCR-only by default)")
    p11.add_argument("image", help="Path to screenshot image")
    p11.add_argument("--vision", action="store_true", help="Send the image to Ollama vision model (uses model in config)")
    p11.set_defaults(func=cmd_what_image)

    args = ap.parse_args()
    # Setup logging early for commands that need it
    if args.cmd in ("backfill","watch"):
        setup_logging(load_config())
    args.func(args)

if __name__ == "__main__":
    main()
