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

ALLOWED_TASKS = {
    "Coding",
    "Research",
    "Comms",
    "Build",
    "Test",
    "Design",
    "Meeting",
    "Admin",
    "Idle",
    "Notes",
    "Unknown",
}

PLACEHOLDER_APPS = {
    "",
    "unknown",
    "app",
    "appname",
    "application",
}

PLACEHOLDER_TITLES = {
    "",
    "unknown",
    "main window",
    "main window title",
    "window",
    "window title",
}

GENERIC_SUMMARY_BITS = (
    "appears to be",
    "possibly",
    "may also",
    "various applications",
    "working on a project",
    "working on a software project",
    "coding or research",
    "developing and monitoring project progress",
    "likely developing or debugging code",
)

THIRD_PERSON_PREFIXES = (
    "the user appears to be ",
    "the user is ",
    "the user was ",
    "a user is ",
    "a user was ",
)

CONCRETE_OPEN_LOOP_TERMS = (
    "blocked",
    "broken",
    "debug",
    "error",
    "fail",
    "failed",
    "fix",
    "issue",
    "pr ",
    "pull request",
    "review",
    "test",
    "timeout",
    "todo",
    "wip",
)


def _norm_text(value: str) -> str:
    """Normalize text for loose heuristic matching."""
    return " ".join((value or "").strip().lower().split())


def is_placeholder_app(value: str) -> bool:
    """Return whether an app value is a model placeholder rather than evidence."""
    norm = _norm_text(value)
    return norm in PLACEHOLDER_APPS or bool(re.fullmatch(r"app\s*\d+", norm))


def normalize_app(value: str) -> str:
    """Normalize app names while preserving real unknown app names."""
    value = (value or "").strip()
    return "Unknown" if is_placeholder_app(value) else value


def is_weak_title(value: str, app: str = "") -> bool:
    """Return whether a window title is too generic to use as concrete context."""
    norm = _norm_text(value)
    app_norm = _norm_text(app)
    if norm in PLACEHOLDER_TITLES:
        return True
    if app_norm and norm == app_norm:
        return True
    return norm in {
        "google chrome",
        "chrome - google chrome",
        "safari",
        "cursor",
        "visual studio code",
    }


def normalize_window_title(value: str, app: str = "") -> str:
    """Normalize weak or placeholder window titles to Unknown."""
    value = (value or "").strip()
    return "Unknown" if is_weak_title(value, app) else value


def clean_summary(value: str) -> str:
    """Clean model-style prose into a short, neutral stored summary."""
    summary = re.sub(r"\s+", " ", (value or "").strip())
    lower = summary.lower()

    for prefix in THIRD_PERSON_PREFIXES:
        if lower.startswith(prefix):
            summary = summary[len(prefix):].strip()
            if summary:
                summary = summary[0].upper() + summary[1:]
            break

    parts = re.split(r"(?<=[.!?])\s+", summary)
    if len(parts) > 1 and any(bit in lower for bit in GENERIC_SUMMARY_BITS):
        summary = parts[0]

    replacements = {
        "They may also be engaged in research and communication activities.": "",
        "possibly involving code in a file named 'file.py'": "working in code",
        "possibly involving code in a file named file.py": "working in code",
    }
    for old, new in replacements.items():
        summary = summary.replace(old, new)

    summary = summary.strip(" -.")
    return summary or "Recent activity captured"


def is_generic_summary(value: str) -> bool:
    """Return whether a summary is too broad to treat as strong evidence."""
    norm = _norm_text(value)
    if not norm:
        return True
    if norm in {"unknown", "recent activity captured", "using unknown"}:
        return True
    return any(bit in norm for bit in GENERIC_SUMMARY_BITS)


def validate_task(raw_task: str, app: str, ocr_text: str) -> str:
    """Return one supported task label, inferring only when deterministic."""
    task = (raw_task or "").strip()
    if task in ALLOWED_TASKS:
        return task
    inferred = guess_task(app, ocr_text.lower())
    return inferred if inferred != "Unknown" else "Unknown"


def has_concrete_evidence(
    *,
    app: str,
    window_title: str,
    summary: str,
    project: Optional[str],
    task: str,
    clues: Dict[str, Any],
    artifacts: List[str],
) -> bool:
    """Return whether an entry has concrete restart-grade evidence."""
    if artifacts:
        return True
    if project:
        return True
    if clues.get("urls") or clues.get("domains") or clues.get("repo_tokens"):
        return True
    text = f" {summary} {window_title} ".lower()
    if any(term in text for term in CONCRETE_OPEN_LOOP_TERMS):
        return True
    if app != "Unknown" and task != "Unknown" and not is_weak_title(window_title, app):
        return True
    return False


def calibrate_confidence(
    raw_confidence: float,
    *,
    app: str,
    window_title: str,
    project: Optional[str],
    project_confidence: float,
    task: str,
    summary: str,
    clues: Dict[str, Any],
    artifacts: List[str],
) -> float:
    """Compute confidence from concrete signals instead of trusting model output."""
    score = 0.20
    if app != "Unknown":
        score += 0.15
    if not is_weak_title(window_title, app):
        score += 0.15
    if task != "Unknown":
        score += 0.15
    if project:
        score += 0.10 if project_confidence >= 0.85 else 0.06
    if clues.get("urls") or clues.get("domains"):
        score += 0.08
    if clues.get("repo_tokens"):
        score += 0.04
    if artifacts:
        score += 0.12
    if summary and not is_generic_summary(summary):
        score += 0.10
    if has_concrete_evidence(
        app=app,
        window_title=window_title,
        summary=summary,
        project=project,
        task=task,
        clues=clues,
        artifacts=artifacts,
    ):
        score += 0.06

    caps = [0.95]
    if app == "Unknown":
        caps.append(0.70)
    if is_weak_title(window_title, app):
        caps.append(0.72)
    if task == "Unknown":
        caps.append(0.68)
    if project is None:
        caps.append(0.85)
    if is_generic_summary(summary):
        caps.append(0.65)
    if raw_confidence < 0.50:
        caps.append(0.60)

    confidence = min(score, *caps)
    return float(f"{max(0.0, min(confidence, 0.95)):.2f}")


# Default task classification by application name
DEFAULT_TASK_BY_APP = {
    "Cursor": "Coding",
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
    "Draw Things": "Design",
    "Zoom Workplace": "Meeting",
    "Calendar": "Meeting",
    "Safari": "Research",
    "Browser": "Research",
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
    min_confidence: float = 0.70,
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
    for clue_key in ("domains", "repo_tokens", "tokens"):
        tokens |= {
            str(token).lower()
            for token in clues.get(clue_key, [])
            if str(token).strip()
        }

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
    if confidence < min_confidence:
        return None, confidence
    return best_match_name, confidence


def summarize(
    cfg: Dict[str, Any],
    app: str,
    window_title: str,
    ocr_top: List[str],
    project_guess: Tuple[Optional[str], float],
    clues: Dict[str, Any],
    vision_result: Optional[Dict[str, Any]] = None,
    use_llm: bool = True,
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
    if app and summ and _norm_text(summ) == _norm_text(app):
        for line in ocr_top:
            if line and _norm_text(line) != _norm_text(app):
                summ = line
                break
    ambient_summary = any(token in _norm_text(summ) for token in ("check in", "single image", "movies", "today", "now"))
    if ambient_summary and coarse_task != "Unknown":
        if app == "Slack":
            summ = "Slack check-in conversation"
        elif app == "Zoom Workplace":
            summ = "Meeting in Zoom Workplace"
        elif app == "Cursor":
            summ = "Coding in Cursor"
        elif app == "Safari":
            summ = f"{window_title} in Safari" if window_title and window_title != "Unknown" else "Browsing in Safari"
    if app == "Zoom Workplace" and _norm_text(summ) in {"workplace", "meeting"}:
        summ = "Meeting in Zoom Workplace"
    if app == "Safari" and _norm_text(summ) in {"workflow runs", "campaigns", "issues"}:
        summ = f"{summ} in Safari"
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

    if use_llm and cfg.get("ollama", {}).get("enabled", False):
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
                if not qls.ollama_model_available(endpoint_cfg, model):
                    # Fallback to known text models if the configured one is missing
                    for candidate in (
                        "deepseek-r1:7b-qwen-distill-q4_K_M",
                        "mistral:latest",
                        "llama2:latest",
                    ):
                        if qls.ollama_model_available(endpoint_cfg, candidate):
                            model = candidate
                            break
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
        "zoom workplace": ["zoom workplace", "zoom", "meeting"],
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
    if any(indicator in combined_text for indicator in app_indicators["draw things"]) or (
        "draw" in combined_text and "image" in combined_text and "window" in combined_text
    ):
        return "Draw Things"

    if "zoom" in combined_text and ("workplace" in combined_text or "meeting" in combined_text):
        return "Zoom Workplace"

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
    if any(token in combined_text for token in ["linear.app", "workflow runs", "accounts", "campaigns", "edit advertiser", "issues"]):
        return "Safari"

    return "Unknown"


def choose_window_title_from_ocr(app: str, ocr_lines: List[str]) -> str:
    """Pick a more informative window-title candidate from OCR text."""
    app_norm = _norm_text(app)
    generic = {
        "",
        "unknown",
        app_norm,
        "file",
        "edit",
        "view",
        "window",
        "help",
        "run",
        "terminal",
        "selection",
        "meeting",
        "zoom",
        "cursor",
        "slack",
        "draw",
        "image",
    }
    ambient_penalties = (
        "check in",
        "single image",
        "movies",
        "mon",
        "apr",
        "today",
        "now",
    )
    candidates = []
    for line in ocr_lines:
        norm = _norm_text(line)
        if norm in generic:
            continue
        if len(norm) < 4:
            continue
        score = len(norm)
        if " " in norm:
            score += 4
        if any(token in norm for token in ["issue", "workflow", "check in", "youtube", "campaign", "linear", "workplace"]):
            score += 6
        if any(token in norm for token in ambient_penalties):
            score -= 16
        if any(ch.isdigit() for ch in norm):
            score -= 8
        if app_norm == "slack" and "check in" in norm:
            score += 12
        if app_norm == "zoom workplace" and "meeting" in norm:
            score += 18
        if app_norm == "cursor" and norm in {"terminal", "run", "selection"}:
            score += 18
        if app_norm == "draw things" and ("cruft" in norm or "draw" in norm):
            score += 6
        if app_norm == "safari" and any(token in norm for token in ["workflow", "campaign", "issue", "accounts"]):
            score += 8
        candidates.append((score, line))
    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1][:80]
    return app if app and app != "Unknown" else "Unknown"


def _merge_vision_project_indicators(
    clues: Dict[str, Any],
    vision_result: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge project indicators discovered by vision into OCR-derived clues."""
    merged = {
        "urls": list(clues.get("urls", [])),
        "domains": list(clues.get("domains", [])),
        "repo_tokens": list(clues.get("repo_tokens", [])),
        "tokens": list(clues.get("tokens", [])),
    }
    for proj_indicator in vision_result.get("project_indicators", []):
        if isinstance(proj_indicator, dict):
            proj_indicator = (
                proj_indicator.get("url")
                or proj_indicator.get("name")
                or proj_indicator.get("path")
                or ""
            )
        proj_indicator = str(proj_indicator).strip()
        if not proj_indicator:
            continue
        if "github.com" in proj_indicator or "http" in proj_indicator:
            if proj_indicator not in merged["urls"]:
                merged["urls"].append(proj_indicator)
        else:
            if proj_indicator not in merged["tokens"]:
                merged["tokens"].append(proj_indicator)
    return merged


def _needs_vision_fallback(
    cfg: Dict[str, Any],
    app: str,
    window_title: str,
    ocr_lines: List[str],
    coarse_task: str,
    confidence: float,
    summary: str,
) -> bool:
    """Decide whether OCR-first analysis is weak enough to justify vision."""
    confidence_floor = max(float(cfg.get("confidence_threshold", 0.65)), 0.75)
    title_norm = _norm_text(window_title)
    summary_norm = _norm_text(summary)
    low_info_titles = {
        "",
        "unknown",
        "wwindow",
        "window",
        "workplace",
        "draw",
        "image",
    }
    if confidence < confidence_floor:
        return True
    if app == "Unknown" or window_title == "Unknown" or coarse_task == "Unknown":
        return True
    if len(ocr_lines) < 3:
        return True
    if title_norm in low_info_titles:
        return True
    if summary_norm in low_info_titles:
        return True
    if any(ch.isdigit() for ch in title_norm) and len(title_norm) < 10:
        return True
    return False


def process_image(
    conn: Any,  # sqlite3.Connection, avoiding circular import
    cfg: Dict[str, Any],
    file_path: Path,
    use_app_detection: bool = True,
    use_vision_analysis: bool = True,
    use_llm_summarization: bool = True,
    vision_fallback_on_low_confidence: bool = False,
    replace_entry_id: Optional[int] = None,
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

    if window_title == "Unknown" and redacted:
        title_app = app
        if title_app == "Unknown" and not use_app_detection:
            title_app = infer_app_from_content(window_title, redacted)
        # Fallback: Improve window title from OCR if still Unknown
        window_title = choose_window_title_from_ocr(title_app, redacted)
        logger.debug("Using OCR fallback for window title: %s", window_title[:40])

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

    clues = extract_clues(app, window_title, redacted)
    proj_guess = resolve_project(
        cfg.get("projects", []),
        cfg.get("project_aliases", {}),
        window_title,
        redacted,
        clues,
        float(cfg.get("project_match_threshold", 0.70)),
    )

    summary, coarse_task, confidence = summarize(
        cfg,
        app,
        window_title,
        redacted,
        proj_guess,
        clues,
        None,
        use_llm=use_llm_summarization,
    )

    should_run_vision = use_vision_analysis and (
        not vision_fallback_on_low_confidence
        or _needs_vision_fallback(cfg, app, window_title, redacted, coarse_task, confidence, summary)
    )
    vision_result: Dict[str, Any] = {}
    vision_available = False

    if should_run_vision:
        vision_result = qls.analyze_image_with_vision(cfg, file_path)
        vision_available = bool(vision_result)
        if vision_available:
            logger.debug("Vision analysis successful: %s", vision_result.get("primary_app", "Unknown"))
        else:
            logger.debug("Vision analysis unavailable, using OCR-based flow")
    else:
        logger.debug("Skipping vision analysis; OCR-based result was sufficient")

    if vision_available:
        if vision_result.get("primary_window_title") != "Unknown":
            window_title = vision_result.get("primary_window_title", window_title)
            logger.debug("Using vision-provided window title: %s", window_title[:40])
        if not use_app_detection and vision_result.get("primary_app") != "Unknown":
            app = vision_result.get("primary_app", app)
            if vision_result.get("apps_visible"):
                logger.debug("Vision detected apps: %s", vision_result.get("apps_visible"))

        clues = _merge_vision_project_indicators(clues, vision_result)
        proj_guess = resolve_project(
            cfg.get("projects", []),
            cfg.get("project_aliases", {}),
            window_title,
            redacted,
            clues,
            float(cfg.get("project_match_threshold", 0.70)),
        )

        if vision_result.get("summary"):
            summary = vision_result.get("summary", "")
            coarse_task = vision_result.get("coarse_task", coarse_task)
            confidence = vision_result.get("confidence", confidence)
            logger.debug(
                "Using vision-provided summary: %s (task=%s, conf=%.2f)",
                summary,
                coarse_task,
                confidence,
            )
        else:
            summary, coarse_task, confidence = summarize(
                cfg,
                app,
                window_title,
                redacted,
                proj_guess,
                clues,
                vision_result,
                use_llm=use_llm_summarization,
            )

    artifacts = find_artifacts(window_title, redacted)

    app = normalize_app(app)
    window_title = normalize_window_title(window_title, app)
    summary = clean_summary(summary)
    coarse_task = validate_task(coarse_task, app, " ".join(redacted))
    if is_generic_summary(summary) and not is_weak_title(window_title, app):
        summary = window_title
    confidence = calibrate_confidence(
        float(confidence or 0.0),
        app=app,
        window_title=window_title,
        project=proj_guess[0],
        project_confidence=float(proj_guess[1] or 0.0),
        task=coarse_task,
        summary=summary,
        clues=clues,
        artifacts=artifacts,
    )

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
    if replace_entry_id is not None:
        entry_id = qldb.update_entry(conn, replace_entry_id, entry, evidence_text, str(file_path), mtime)
    else:
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
