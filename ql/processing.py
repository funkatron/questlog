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
from ql.text import redact, find_artifacts, extract_clues, build_ollama_prompt, filter_ocr_cruft


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

    # Extract repo name from GitHub URLs (e.g., github.com/funkatron/questlog -> questlog)
    for url in clues.get("urls", []):
        github_match = re.search(r'github\.com/[^/]+/([^/]+)', url.lower())
        if github_match:
            repo_name = github_match.group(1)
            tokens.add(repo_name)
            # Also add owner/repo combo
            full_match = re.search(r'github\.com/([^/]+)/([^/]+)', url.lower())
            if full_match:
                tokens.add(f"{full_match.group(1)}/{full_match.group(2)}")

    # Also check OCR text directly for github.com URLs
    github_url_match = re.search(r'github\.com/([^/\s]+)/([^/\s]+)', search_text)
    if github_url_match:
        tokens.add(github_url_match.group(2))  # repo name
        tokens.add(f"{github_url_match.group(1)}/{github_url_match.group(2)}")  # owner/repo

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
    vision_result: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str, float]:
    """Generate activity summary, task classification, and confidence score.

    Creates a concise summary of what the user was doing based on app context,
    window title, OCR content, and vision analysis. Uses LLM if enabled for better quality,
    with intelligent model selection and fallbacks.

    Args:
        cfg: Configuration dictionary with Ollama/OpenAI settings.
        app: Name of the active application.
        window_title: Title of the active window.
        ocr_top: Top OCR lines extracted from the screenshot.
        project_guess: Tuple of (project_name, confidence) from project resolution.
        clues: Dictionary of extracted clues (URLs, domains, tokens).
        vision_result: Optional vision analysis result dictionary.

    Returns:
        Tuple of (summary, coarse_task, confidence) where:
        - summary: Concise activity description (max 160 chars).
        - coarse_task: Task category (Coding, Research, Comms, etc.).
        - confidence: Confidence score from 0.0 to 1.0.
    """
    # If vision analysis provided summary, use it (already handled in process_image)
    # This function is called as fallback when vision doesn't provide summary

    ocr_text = " ".join(ocr_top).lower()
    coarse_task = guess_task(app, ocr_text)

    # Enhance with vision context if available
    if vision_result:
        vision_task = vision_result.get("coarse_task", "")
        if vision_task and vision_task != "Unknown":
            coarse_task = vision_task
        vision_activity = vision_result.get("primary_activity", "")
        if vision_activity:
            # Use vision activity as additional context
            logger.debug("Vision detected activity: %s", vision_activity)

    summ = window_title if window_title and window_title != "Unknown" else (ocr_top[0] if ocr_top else "")
    summ = summ.strip() or (f"{coarse_task} in {app}" if coarse_task != "Unknown" else f"Using {app}")

    conf = 0.5
    if project_guess[0]:
        conf += 0.15
    if coarse_task != "Unknown":
        conf += 0.15
    if clues.get("urls"):
        conf += 0.05
    if vision_result:
        # Boost confidence if vision analysis was successful
        vision_conf = vision_result.get("confidence", 0.5)
        conf = max(conf, vision_conf * 0.8)  # Use vision confidence as upper bound
    conf = min(conf, 0.95)

    if cfg.get("ollama", {}).get("enabled", False):
        try:
            # Include vision context in prompt if available
            payload = build_ollama_prompt(cfg, app, window_title, ocr_top, cfg.get("projects", []), clues, vision_result)

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


def infer_app_from_content(window_title: str, ocr_lines: List[str]) -> str:
    """Infer application name from window title and OCR content.

    Uses heuristics to guess the application based on window title patterns
    and OCR text content (menu bars, UI elements, etc.).

    Args:
        window_title: Window title text.
        ocr_lines: OCR-extracted text lines.

    Returns:
        Inferred application name, or "Unknown" if no match.
    """
    combined_text = " ".join([window_title] + ocr_lines).lower()

    # Check for app indicators in OCR (menu bars, UI elements)
    app_indicators = {
        "safari": ["safari", "file edit view history bookmarks"],
        "chrome": ["chrome", "google chrome"],
        "firefox": ["firefox", "mozilla"],
        "cursor": ["cursor", "cursor editor"],
        "code": ["visual studio code", "code", "vscode"],
        "terminal": ["terminal", "iterm", "zsh", "bash"],
        "slack": ["slack"],
        "discord": ["discord"],
        "mail": ["mail", "apple mail"],
        "notes": ["notes"],
        "figma": ["figma"],
        "obsidian": ["obsidian"],
        "draw things": ["drawthings", "draw things", "edit image view window help", "version history", "local network"],
        "github": ["github.com", "github", "repository", "pull request", "issue"],
    }

    # Check for Draw Things first (has distinctive UI elements)
    if any(indicator in combined_text for indicator in app_indicators["draw things"]):
        return "Draw Things"

    # Check other apps
    for app_name, keywords in app_indicators.items():
        if app_name == "draw things":
            continue  # Already checked
        if any(keyword in combined_text for keyword in keywords):
            return app_name.title()

    # Check window title for common patterns
    title_lower = window_title.lower()
    if ".py" in title_lower or ".js" in title_lower or ".ts" in title_lower or ".md" in title_lower:
        if "cursor" in title_lower or "github.com" in combined_text:
            return "Cursor"
        return "Code"
    if "terminal" in title_lower or "iterm" in title_lower:
        return "Terminal"
    if "github.com" in combined_text or "repository" in combined_text:
        return "GitHub"
    if "readme" in combined_text and ("github" in combined_text or ".md" in combined_text):
        return "Cursor"  # Likely viewing README in Cursor/VS Code

    return "Unknown"


def process_image(
    conn: Any,  # sqlite3.Connection, avoiding circular import
    cfg: Dict[str, Any],
    file_path: Path,
    use_app_detection: bool = True,
) -> Optional[int]:
    """Process a screenshot image and create a database entry.

    Uses vision-based analysis as primary method, with OCR as supplemental context.
    Extracts context from the image (app, window title, OCR text), generates
    a summary, and stores the entry in the database. Handles app blocklisting,
    window title fallback, and diagnostic logging.

    Args:
        conn: SQLite database connection.
        cfg: Configuration dictionary.
        file_path: Path to the screenshot image file.
        use_app_detection: If True, detect current frontmost app. If False,
            infer app from OCR/window title (for historical screenshots).

    Returns:
        Entry ID if successfully processed, None if skipped (blocklisted app).
    """
    mtime = file_path.stat().st_mtime
    timestamp = dt.datetime.fromtimestamp(mtime).astimezone().isoformat(timespec="seconds")

    # PRIMARY: Vision-based analysis
    vision_result = qls.analyze_image_with_vision(cfg, file_path)
    vision_available = bool(vision_result)

    if vision_available:
        logger.debug("Vision analysis successful: %s", vision_result.get("primary_app", "Unknown"))
    else:
        logger.debug("Vision analysis unavailable, falling back to OCR-based flow")

    # App and window title detection
    if use_app_detection:
        meta = qls.front_app_info()
        app = meta.get("app", "Unknown")
        window_title = meta.get("window_title", "Unknown")
        blocklist = cfg.get("blocklist_apps") or []
        if app in blocklist:
            logger.info("skipping blocklisted app: %s", app)
            return None
    else:
        # For historical screenshots, use vision analysis if available
        if vision_available:
            app = vision_result.get("primary_app", "Unknown")
            window_title = vision_result.get("primary_window_title", "Unknown")
            # If vision found multiple apps, prefer the primary
            if vision_result.get("apps_visible"):
                logger.debug("Vision detected apps: %s", vision_result.get("apps_visible"))
        else:
            app = "Unknown"
            window_title = "Unknown"

    # SUPPLEMENTAL: OCR for additional text context
    # Try EasyOCR first (best quality), then LLM OCR, then Tesseract
    max_ocr_lines = cfg.get("max_ocr_lines", 12)
    ocr_top_raw = qls.ocr_with_easyocr(file_path, max_ocr_lines)
    if not ocr_top_raw:
        ocr_top_raw = qls.ocr_with_llm(cfg, file_path, max_ocr_lines)
    if not ocr_top_raw:
        ocr_top_raw = qls.ocr_lines(file_path, max_ocr_lines)

    # Log raw OCR output in debug mode
    logger.debug("OCR raw (%d lines): %s", len(ocr_top_raw), ocr_top_raw[:10])

    # Filter out cruft (menu bars, UI elements, system stats, etc.)
    ocr_filtered = filter_ocr_cruft(ocr_top_raw)
    logger.debug("OCR filtered (%d lines): %s", len(ocr_filtered), ocr_filtered[:10])

    redacted = [redact(line) for line in ocr_filtered]

    # MERGE: Combine vision analysis with OCR
    # If vision provided window title, use it (unless it's Unknown)
    if vision_available and vision_result.get("primary_window_title") != "Unknown":
        window_title = vision_result.get("primary_window_title", window_title)
        logger.debug("Using vision-provided window title: %s", window_title[:40])
    elif window_title == "Unknown" and redacted:
        # Fallback: Improve window title from OCR if still Unknown
        for line in redacted:
            line_stripped = line.strip()
            # Skip lines that look like system stats
            if re.search(r'\b(gpu|cpu|mem|ram|fs|loa|pu)\b', line_stripped, re.IGNORECASE) and len(re.findall(r'\d', line_stripped)) > 2:
                continue
            if re.match(r'^[\d\s\.]+$', line_stripped) and len(line_stripped) < 30:
                continue
            if line_stripped and len(line_stripped) > 3:
                window_title = line_stripped[:80]  # Reasonable max length
                logger.debug("Using OCR fallback for window title: %s", window_title[:40])
                break

    # Clean up window title if it looks like system stats (even if not "Unknown")
    if window_title and window_title != "Unknown":
        if re.search(r'\b(gpu|cpu|mem|ram|fs|loa|pu)\b', window_title, re.IGNORECASE) and len(re.findall(r'\d', window_title)) > 2:
            # Try to find a better window title from filtered OCR
            for line in redacted[:10]:
                line_stripped = line.strip()
                # Skip system stats
                if re.search(r'\b(gpu|cpu|mem|ram|fs|loa|pu)\b', line_stripped, re.IGNORECASE) and len(re.findall(r'\d', line_stripped)) > 2:
                    continue
                if re.match(r'^[\d\s\.]+$', line_stripped) and len(line_stripped) < 30:
                    continue
                # Prefer lines with actual content (files, URLs, readable text)
                if line_stripped and len(line_stripped) > 5:
                    # Prefer lines that look like file names, URLs, or readable text
                    if re.search(r'\.(md|py|js|ts|yaml|yml|json)', line_stripped) or \
                       re.search(r'github\.com', line_stripped) or \
                       len(re.findall(r'[a-zA-Z]', line_stripped)) > len(re.findall(r'\d', line_stripped)):
                        window_title = line_stripped[:80]
                        logger.debug("Replaced system stats window title with: %s", window_title[:40])
                        break

    # Infer app from content if we didn't detect it
    if app == "Unknown" and not use_app_detection:
        app = infer_app_from_content(window_title, redacted)

    # Merge vision project indicators with OCR clues
    clues = extract_clues(app, window_title, redacted)
    if vision_available and vision_result.get("project_indicators"):
        # Add vision-detected project indicators to clues
        vision_projects = vision_result.get("project_indicators", [])
        for proj_indicator in vision_projects:
            if "github.com" in proj_indicator or "http" in proj_indicator:
                if "urls" not in clues:
                    clues["urls"] = []
                if proj_indicator not in clues["urls"]:
                    clues["urls"].append(proj_indicator)
            else:
                # Could be a project name or token
                if "tokens" not in clues:
                    clues["tokens"] = []
                if proj_indicator not in clues["tokens"]:
                    clues["tokens"].append(proj_indicator)
        logger.debug("Merged vision project indicators: %s", vision_projects)

    proj_guess = resolve_project(
        cfg.get("projects", []), cfg.get("project_aliases", {}), window_title, redacted, clues
    )

    # Use vision summary if available, otherwise generate one
    if vision_available and vision_result.get("summary"):
        summary = vision_result.get("summary", "")
        coarse_task = vision_result.get("coarse_task", "Unknown")
        confidence = vision_result.get("confidence", 0.5)
        logger.debug("Using vision-provided summary: %s (task=%s, conf=%.2f)", summary, coarse_task, confidence)
    else:
        summary, coarse_task, confidence = summarize(cfg, app, window_title, redacted, proj_guess, clues, vision_result if vision_available else None)

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


