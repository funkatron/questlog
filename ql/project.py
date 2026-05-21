"""Project resolution from window content and OCR clues."""

from __future__ import annotations

import re
from typing import Any


def resolve_project(
    projects: list[str],
    aliases: dict[str, list[str]],
    window_title: str,
    ocr_lines: list[str],
    clues: dict[str, Any],
    min_confidence: float = 0.70,
) -> tuple[str | None, float]:
    """Match window content to a known project using fuzzy matching.

    Analyzes window title, OCR text, domains, and repository tokens to find
    the best matching project from the configured list.
    """
    from rapidfuzz import fuzz, process

    search_text = " ".join([window_title] + ocr_lines).lower()
    tokens = set(re.split(r"[\s/\\]+", search_text))
    for clue_key in ("domains", "repo_tokens", "tokens"):
        tokens |= {
            str(token).lower()
            for token in clues.get(clue_key, [])
            if str(token).strip()
        }

    for url in clues.get("urls", []):
        github_match = re.search(r"github\.com/[^/]+/([^/]+)", url.lower())
        if github_match:
            repo_name = github_match.group(1)
            tokens.add(repo_name)
            full_match = re.search(r"github\.com/([^/]+)/([^/]+)", url.lower())
            if full_match:
                tokens.add(f"{full_match.group(1)}/{full_match.group(2)}")

    github_url_match = re.search(r"github\.com/([^/\s]+)/([^/\s]+)", search_text)
    if github_url_match:
        tokens.add(github_url_match.group(2))
        tokens.add(f"{github_url_match.group(1)}/{github_url_match.group(2)}")

    best_match_name = None
    best_match_score = 0.0

    candidates: list[tuple[str, str]] = []
    for project in projects or []:
        candidates.append((project, project))
        for alias in (aliases or {}).get(project, []):
            candidates.append((project, alias))

    for project_name, candidate in candidates:
        match_result = process.extractOne(
            candidate.lower(),
            tokens,
            scorer=fuzz.partial_ratio,
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
