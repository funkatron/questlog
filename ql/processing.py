from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple, Iterable

import requests

from ql import db as qldb
from ql import system as qls
from ql.text import redact, find_artifacts, extract_clues, build_ollama_prompt


logger = logging.getLogger("questlog")


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
    if app in ("Terminal", "iTerm2"):
        if any(k in ocr_text for k in ("pytest", "coverage", "unittest", "rspec")):
            return "Test"
        if any(k in ocr_text for k in ("docker", "compose", "kubectl", "terraform", "ansible")):
            return "Build"
        if any(k in ocr_text for k in ("git ", "vim ", "nvim ", "code ", "gcc", "make ", "pip ", "uv ")):
            return "Coding"
    return DEFAULT_TASK_BY_APP.get(app, "Unknown")


def resolve_project(
    projects: List[str],
    aliases: Dict[str, List[str]],
    window_title: str,
    ocr_lines: List[str],
    clues: Dict[str, Any],
) -> Tuple[str, float]:
    from rapidfuzz import process, fuzz

    hay = " ".join([window_title] + ocr_lines).lower()
    tokens = set(re.split(r"[\s/\\]+", hay))
    tokens |= set(clues.get("domains", []))
    tokens |= set(clues.get("repo_tokens", []))

    best_name = None
    best_score = 0

    candidates: List[Tuple[str, str]] = []
    for p in projects or []:
        candidates.append((p, p))
        for a in (aliases or {}).get(p, []):
            candidates.append((p, a))

    for proj, cand in candidates:
        match = process.extractOne(cand.lower(), tokens, scorer=fuzz.partial_ratio)
        if match:
            s = match[1]
            if s > best_score:
                best_score = s
                best_name = proj
    return best_name, best_score / 100.0


def summarize(
    cfg: dict,
    app: str,
    window_title: str,
    ocr_top: List[str],
    project_guess: Tuple[str, float],
    clues: Dict[str, Any],
):
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
            resp = requests.post(
                cfg["ollama"]["endpoint"],
                json={"model": cfg["ollama"]["model"], "prompt": payload, "stream": False},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            try:
                j = json.loads(data.get("response", "{}"))
                summ = j.get("summary", summ)
                coarse_task = j.get("coarse_task", coarse_task)
                conf = float(j.get("confidence", conf))
            except Exception:
                pass
        except Exception as e:
            logger.warning("ollama summarize failed: %s", e)

    return summ[:160], coarse_task, float(f"{conf:.2f}")


def process_image(
    conn,
    cfg: dict,
    file_path: Path,
    frontapp_bin: Path,
    ocr_bin: Path,
):
    mtime = file_path.stat().st_mtime
    ts = dt.datetime.fromtimestamp(mtime).astimezone().isoformat(timespec="seconds")

    meta = qls.front_app_info(frontapp_bin)
    app = meta.get("app", "Unknown")
    if app in (cfg.get("blocklist_apps") or []):
        logger.info("skipping blocklisted app: %s", app)
        return None

    window_title = meta.get("window_title", "Unknown")

    ocr_top_raw = qls.ocr_lines(ocr_bin, file_path, cfg.get("max_ocr_lines", 12))
    redacted = [redact(l) for l in ocr_top_raw]

    clues = extract_clues(app, window_title, redacted)
    proj_guess = resolve_project(
        cfg.get("projects", []), cfg.get("project_aliases", {}), window_title, redacted, clues
    )
    summary, coarse_task, confidence = summarize(cfg, app, window_title, redacted, proj_guess, clues)
    artifacts = find_artifacts(window_title, redacted)

    entry = {
        "ts": ts,
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
    logger.info("indexed %s (entry_id=%s)", file_path.name, entry_id)
    return entry_id


def iter_images(base_folder: Path) -> Iterable[Path]:
    if not base_folder.exists():
        return []
    for root, dirs, files in os.walk(base_folder):
        for name in files:
            p = Path(root) / name
            if p.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                yield p


