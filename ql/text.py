"""Text processing utilities for Questlog.

This module handles text redaction, clue extraction, and LLM prompt construction.
"""

import os
import re
from typing import List, Dict, Any


# Regular expressions for privacy-sensitive patterns
RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
RE_LONGNUM = re.compile(r"(?<!\d)(\d{4}[\s-]?){3}\d{4}(?!\d)")
RE_URL = re.compile(r"https?://[^\s)>\]]+", re.IGNORECASE)


def redact(text: str) -> str:
    """Redact privacy-sensitive information from text.

    Replaces email addresses and long numeric sequences (like credit card numbers)
    with placeholder text to protect user privacy.

    Args:
        text: Input text that may contain sensitive information.

    Returns:
        Text with email addresses and long numbers redacted.
    """
    text = RE_EMAIL.sub("[redacted-email]", text)
    text = RE_LONGNUM.sub("[redacted-num]", text)
    return text


def find_artifacts(window_title: str, ocr_lines: List[str]) -> List[str]:
    """Extract file and artifact names from window title and OCR text.

    Looks for patterns that resemble filenames (text with extensions) in the
    combined window title and OCR content.

    Args:
        window_title: Title of the active window.
        ocr_lines: List of OCR-extracted text lines.

    Returns:
        List of up to 5 potential artifact/filename matches.
    """
    text = " ".join([window_title] + ocr_lines)
    candidates = re.findall(r"[\w\-\_/]+\.[A-Za-z0-9]{1,6}", text)
    unique_artifacts = []
    for candidate in candidates:
        if candidate not in unique_artifacts:
            unique_artifacts.append(candidate)
    return unique_artifacts[:5]


def extract_clues(
    app: str,
    window_title: str,
    lines: List[str]
) -> Dict[str, Any]:
    """Extract contextual clues from window title and OCR text.

    Identifies URLs, domains, and potential repository/project tokens that can
    help with project resolution and activity classification.

    Args:
        app: Name of the active application.
        window_title: Title of the active window.
        lines: List of OCR-extracted text lines.

    Returns:
        Dictionary containing:
        - urls: List of up to 5 URLs found in the text.
        - domains: List of up to 5 domain names extracted from URLs.
        - repo_tokens: List of up to 10 tokens from window title that might
          indicate repository or project names.
    """
    joined_text = "\n".join(lines)
    urls = RE_URL.findall(joined_text)
    domain_tokens = []
    for url in urls:
        try:
            domain = re.sub(r"^https?://", "", url).split("/")[0]
            if domain:
                domain_tokens.append(domain.lower())
        except Exception:
            pass
    repo_tokens = []
    for token in re.findall(r"[A-Za-z0-9_\-]+", window_title):
        if len(token) >= 3:
            repo_tokens.append(token.lower())
    return {
        "urls": urls[:5],
        "domains": domain_tokens[:5],
        "repo_tokens": repo_tokens[:10],
    }


def build_ollama_prompt(
    cfg: Dict[str, Any],
    app: str,
    window_title: str,
    ocr_top: List[str],
    projects: List[str],
    clues: Dict[str, Any],
) -> str:
    """Build a prompt for LLM-based activity summarization.

    Constructs a structured prompt that guides the LLM to analyze screenshot
    context and generate a concise summary with task classification.

    Args:
        cfg: Configuration dictionary containing max_ocr_lines and other settings.
        app: Name of the active application.
        window_title: Title of the active window.
        ocr_top: Top OCR lines extracted from the screenshot.
        projects: List of known project names for context.
        clues: Dictionary of extracted clues (URLs, domains, tokens).

    Returns:
        A formatted prompt string ready to send to the LLM.
    """
    max_lines = cfg.get("max_ocr_lines", 12)
    ocr_block = os.linesep.join(ocr_top[:max_lines])
    taxonomy = (
        "Coding, Research, Comms, Build, Test, Design, Meeting, Admin, Idle, Unknown"
    )

    # Build project hint if we have a match
    project_hint = ""
    if projects:
        project_hint = f"\n- Known Projects: {', '.join(projects)}"

    prompt = f"""You are labeling a work activity snapshot. Analyze the context and return a JSON response.

TASK TAXONOMY (choose exactly one): {taxonomy}

CONTEXT:
- App: {app}
- Window Title: {window_title}
- OCR Text (visible on screen):
{ocr_block}
- URLs/Domains: {clues.get('urls', [])[:3]}{project_hint}

RULES:
1. If window title is "Unknown", infer from OCR text and app name
2. Summary must be ≤ 16 words, action-oriented (what user is doing)
3. Activity is a short verb+noun phrase (≤ 4 words)
4. Confidence: 0.7+ if clear, 0.5-0.7 if inferred, <0.5 if very uncertain
5. Use app name + OCR content to determine task type

EXAMPLES:

Example 1:
Input: App=Cursor, Window="questlog.py — questlog", OCR=["def summarize(", "import requests"]
Output: {{"summary": "Editing questlog.py Python code", "coarse_task": "Coding", "confidence": 0.85}}

Example 2:
Input: App=Safari, Window="Unknown", OCR=["Amazon.com", "Shopping Cart", "Checkout"]
Output: {{"summary": "Shopping on Amazon website", "coarse_task": "Research", "confidence": 0.75}}

Example 3:
Input: App=Terminal, Window="~/src/project", OCR=["pytest", "3 passed", "test_main.py"]
Output: {{"summary": "Running pytest unit tests", "coarse_task": "Test", "confidence": 0.90}}

Example 4:
Input: App=Slack, Window="#general", OCR=["Hey team", "meeting at 3pm"]
Output: {{"summary": "Reading Slack messages in #general", "coarse_task": "Comms", "confidence": 0.80}}

REQUIRED OUTPUT FORMAT (JSON only):
{{
  "summary": "<concise action description, ≤16 words>",
  "coarse_task": "<one of: {taxonomy}>",
  "confidence": <0.0-1.0>
}}

Return ONLY valid JSON, no other text.""".strip()
    return prompt

