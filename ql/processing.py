"""Core processing logic for Questlog.

This module handles image processing, activity summarization, project resolution,
and task classification.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple, Iterable, Optional

import requests

from ql import db as qldb
from ql import system as qls
from ql.text import redact, find_artifacts, extract_clues, build_ollama_prompt


logger = logging.getLogger("questlog")


# Default task classification by application name
DEFAULT_TASK_BY_APP = {
    "Code": "Coding",
    "Visual Studio Code": "Coding",
    "Xcode": "Coding",
    "Terminal": "Coding",
    "iTerm2": "Coding",
    "PyCharm": "Coding",
    "WebStorm": "Coding",
    "GoLand": "Coding",
    "DataGrip": "Coding",
    "Safari": "Research",
    "Google Chrome": "Research",
    "Arc": "Research",
    "Firefox": "Research",
    "Slack": "Comms",
    "Discord": "Comms",
    "Mail": "Comms",
    "Spark": "Comms",
    "Obsidian": "Notes",
    "Notes": "Notes",
    "Figma": "Design",
    "Calendar": "Meeting",
}


def guess_task(app: str, ocr_text: str) -> str:
    """Classify task type based on application and OCR content.

    Uses heuristics to determine the task category. For terminal apps, analyzes
    OCR text for specific keywords. For other apps, uses a lookup table.

    Args:
        app: Name of the active application.
        ocr_text: Lowercased OCR text content for keyword matching.

    Returns:
        Task category string: "Coding", "Test", "Build", "Research", "Comms",
        "Notes", "Design", "Meeting", "Admin", "Idle", or "Unknown".
    """
    if app in ("Terminal", "iTerm2"):
        test_keywords = ("pytest", "coverage", "unittest", "rspec")
        build_keywords = ("docker", "compose", "kubectl", "terraform", "ansible")
        coding_keywords = ("git ", "vim ", "nvim ", "code ", "gcc", "make ", "pip ", "uv ")

        if any(keyword in ocr_text for keyword in test_keywords):
            return "Test"
        if any(keyword in ocr_text for keyword in build_keywords):
            return "Build"
        if any(keyword in ocr_text for keyword in coding_keywords):
            return "Coding"
    return DEFAULT_TASK_BY_APP.get(app, "Unknown")


def resolve_project(
    projects: List[str],
    aliases: Dict[str, List[str]],
    window_title: str,
    ocr_lines: List[str],
    clues: Dict[str, Any],
) -> Tuple[Optional[str], float]:
    """Match window content to a known project using fuzzy matching.

    Analyzes window title, OCR text, domains, and repository tokens to find
    the best matching project from the configured list. Uses fuzzy string
    matching to handle variations in naming.

    Args:
        projects: List of known project names.
        aliases: Dictionary mapping project names to lists of alias strings.
        window_title: Title of the active window.
        ocr_lines: OCR-extracted text lines.
        clues: Dictionary containing domains and repo_tokens.

    Returns:
        Tuple of (project_name, confidence_score) where:
        - project_name: Best matching project name, or None if no good match.
        - confidence_score: Match quality from 0.0 to 1.0.
    """
    from rapidfuzz import process, fuzz

    search_text = " ".join([window_title] + ocr_lines).lower()
    tokens = set(re.split(r"[\s/\\]+", search_text))
    tokens |= set(clues.get("domains", []))
    tokens |= set(clues.get("repo_tokens", []))

    best_match_name = None
    best_match_score = 0.0

    # Build candidate list: (project_name, search_string)
    candidates: List[Tuple[str, str]] = []
    for project in projects or []:
        candidates.append((project, project))
        for alias in (aliases or {}).get(project, []):
            candidates.append((project, alias))

    # Find best fuzzy match
    for project_name, candidate in candidates:
        match_result = process.extractOne(
            candidate.lower(),
            tokens,
            scorer=fuzz.partial_ratio
        )
        if match_result:
            score = match_result[1]
            if score > best_match_score:
                best_match_score = score
                best_match_name = project_name

    confidence = best_match_score / 100.0
    return best_match_name, confidence


def summarize(
    cfg: Dict[str, Any],
    app: str,
    window_title: str,
    ocr_top: List[str],
    project_guess: Tuple[Optional[str], float],
    clues: Dict[str, Any],
) -> Tuple[str, str, float]:
    """Generate activity summary, task classification, and confidence score.

    Creates a concise summary of what the user was doing based on app context,
    window title, and OCR content. Uses LLM if enabled for better quality,
    with intelligent model selection and fallbacks.

    Args:
        cfg: Configuration dictionary with Ollama/OpenAI settings.
        app: Name of the active application.
        window_title: Title of the active window.
        ocr_top: Top OCR lines extracted from the screenshot.
        project_guess: Tuple of (project_name, confidence) from project resolution.
        clues: Dictionary of extracted clues (URLs, domains, tokens).

    Returns:
        Tuple of (summary, coarse_task, confidence) where:
        - summary: Concise activity description (max 160 chars).
        - coarse_task: Task category (Coding, Research, Comms, etc.).
        - confidence: Confidence score from 0.0 to 1.0.
    """

    ocr_text = " ".join(ocr_top).lower()
    coarse_task = guess_task(app, ocr_text)

    summ = window_title if window_title and window_title != "Unknown" else (ocr_top[0] if ocr_top else "")
    summ = summ.strip() or (f"{coarse_task} in {app}" if coarse_task != "Unknown" else f"Using {app}")

    conf = 0.5
    if project_guess[0]:
        conf += 0.15
    if coarse_task != "Unknown":
        conf += 0.15
    if clues.get("urls"):
        conf += 0.05
    conf = min(conf, 0.95)

    if cfg.get("ollama", {}).get("enabled", False):
        try:
            payload = build_ollama_prompt(cfg, app, window_title, ocr_top, cfg.get("projects", []), clues)

            endpoint_cfg = cfg["ollama"].get("endpoint", "http://localhost:11434")
            # Normalize URLs
            def _join(u: str, path: str) -> str:
                return u.rstrip("/") + path
            gen_url = endpoint_cfg if endpoint_cfg.endswith("/api/generate") else _join(endpoint_cfg, "/api/generate")

            # Use summarization model for text generation
            summarization_cfg = cfg["ollama"].get("summarization", {})
            model = summarization_cfg.get("model", "deepseek-r1:7b-qwen-distill-q4_K_M")

            # Prefer a locally available model when the configured one is missing
            try:
                tags_url = gen_url.replace("/api/generate", "/api/tags")
                tags = requests.get(tags_url, timeout=2)
                names = set()
                if tags.ok:
                    tj = tags.json()
                    listing = tj.get("models") if isinstance(tj, dict) else (tj if isinstance(tj, list) else [])
                    for m in listing or []:
                        if isinstance(m, dict) and m.get("name"):
                            names.add(m["name"])
                if model not in names:
                    # Fallback to available text models
                    if "deepseek-r1:7b-qwen-distill-q4_K_M" in names:
                        model = "deepseek-r1:7b-qwen-distill-q4_K_M"
                    elif "mistral:latest" in names:
                        model = "mistral:latest"
                    elif "llama2:latest" in names:
                        model = "llama2:latest"
            except Exception:
                pass

            raw_response_text = None

            # Summarization models work with text only, not images
            gen_payload = {
                "model": model,
                "prompt": payload,
                "stream": False,
            }
            gen_resp = requests.post(
                gen_url,
                json=gen_payload,
                timeout=15,
            )
            gen_resp.raise_for_status()
            raw_response_text = (gen_resp.json() or {}).get("response", "")
            if not raw_response_text:
                # CLI fallback if HTTP yields empty/unsupported
                try:
                    cli_out = subprocess.check_output([
                        "ollama", "run", model, "-p", payload
                    ], text=True, timeout=15)
                    raw_response_text = cli_out.strip()
                except Exception:
                    pass

            if raw_response_text:
                # Try JSON parse first
                try:
                    j = json.loads(raw_response_text)
                    summ = j.get("summary", summ)
                    coarse_task = j.get("coarse_task", coarse_task)
                    conf = float(j.get("confidence", conf))
                except Exception:
                    # Use raw text as summary if not JSON
                    summ = (raw_response_text or summ).strip()[:160]
                    conf = min(max(conf, 0.7), 0.95)

        except Exception as e:
            logger.warning("ollama summarize failed: %s", e)
    return summ[:160], coarse_task, float(f"{conf:.2f}")


def process_image(
    conn: Any,  # sqlite3.Connection, avoiding circular import
    cfg: Dict[str, Any],
    file_path: Path,
    frontapp_bin: Path,
    ocr_bin: Path,
) -> Optional[int]:
    """Process a screenshot image and create a database entry.

    Extracts context from the image (app, window title, OCR text), generates
    a summary, and stores the entry in the database. Handles app blocklisting,
    window title fallback, and diagnostic logging.

    Args:
        conn: SQLite database connection.
        cfg: Configuration dictionary.
        file_path: Path to the screenshot image file.
        frontapp_bin: Path to the Swift frontapp binary.
        ocr_bin: Path to the Swift OCR binary.

    Returns:
        Entry ID if successfully processed, None if skipped (blocklisted app).
    """
    mtime = file_path.stat().st_mtime
    timestamp = dt.datetime.fromtimestamp(mtime).astimezone().isoformat(timespec="seconds")

    meta = qls.front_app_info(frontapp_bin)
    app = meta.get("app", "Unknown")
    blocklist = cfg.get("blocklist_apps") or []
    if app in blocklist:
        logger.info("skipping blocklisted app: %s", app)
        return None

    window_title = meta.get("window_title", "Unknown")

    # Try LLM-based OCR first, fall back to traditional OCR
    max_ocr_lines = cfg.get("max_ocr_lines", 12)
    ocr_top_raw = qls.ocr_with_llm(cfg, file_path, max_ocr_lines)
    if not ocr_top_raw:
        ocr_top_raw = qls.ocr_lines(ocr_bin, file_path, max_ocr_lines)
    redacted = [redact(line) for line in ocr_top_raw]

    # Improve window title if it's Unknown - use first meaningful OCR line
    if window_title == "Unknown" and redacted:
        for line in redacted:
            line_stripped = line.strip()
            if line_stripped and len(line_stripped) > 3:
                window_title = line_stripped[:80]  # Reasonable max length
                logger.debug("Using OCR fallback for window title: %s", window_title[:40])
                break

    clues = extract_clues(app, window_title, redacted)
    proj_guess = resolve_project(
        cfg.get("projects", []), cfg.get("project_aliases", {}), window_title, redacted, clues
    )
    summary, coarse_task, confidence = summarize(cfg, app, window_title, redacted, proj_guess, clues)
    artifacts = find_artifacts(window_title, redacted)

    # Diagnostic logging for Unknown entries
    if app == "Unknown" or window_title == "Unknown" or coarse_task == "Unknown":
        logger.warning(
            "Low-quality entry detected: app=%s, title=%s, task=%s, ocr_lines=%d, confidence=%.2f",
            app, window_title, coarse_task, len(redacted), confidence
        )
        if not redacted:
            logger.warning("  -> No OCR text extracted from %s", file_path.name)

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

    evidence_text = "\n".join([window_title] + redacted + clues.get("urls", []))
    entry_id = qldb.insert_entry(conn, entry, evidence_text, str(file_path), mtime)
    logger.info(
        "indexed %s (entry_id=%s, app=%s, task=%s, conf=%.2f)",
        file_path.name, entry_id, app, coarse_task, confidence
    )
    return entry_id


def iter_images(base_folder: Path) -> Iterable[Path]:
    """Iterate over image files in a directory tree.

    Recursively walks through the directory and yields paths to image files
    with supported extensions.

    Args:
        base_folder: Root directory to search for images.

    Yields:
        Path objects for each image file found (.png, .jpg, .jpeg).
    """
    if not base_folder.exists():
        return
    for root, dirs, files in os.walk(base_folder):
        for filename in files:
            file_path = Path(root) / filename
            if file_path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                yield file_path


