"""Text processing utilities for Questlog.

This module handles text redaction, clue extraction, and LLM prompt construction.
"""

import os
import re
from typing import List, Dict, Any, Optional

from ql.vocabulary import OCR_CONTEXT_PRESERVE_SIGNALS


# Regular expressions for privacy-sensitive patterns
RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
RE_LONGNUM = re.compile(r"(?<!\d)(\d{4}[\s-]?){3}\d{4}(?!\d)")
RE_URL = re.compile(r"https?://[^\s)>\]]+", re.IGNORECASE)
RE_PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)")
RE_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|passwd|pwd)\s*[:=]\s*[^\s,;]+"
)
RE_URL_QUERY = re.compile(r"(https?://[^\s)>\]?]+)\?[^\s)>\]]+", re.IGNORECASE)


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
    text = RE_PHONE.sub("[redacted-phone]", text)
    text = RE_SECRET_ASSIGNMENT.sub(lambda m: f"{m.group(1)}=[redacted-secret]", text)
    return text


def redact_for_display(text: str) -> str:
    """Redact text before displaying it in user-facing restart notes."""
    text = redact(text)
    text = RE_URL_QUERY.sub(r"\1?[redacted-query]", text)
    return text


def filter_ocr_cruft(lines: List[str]) -> List[str]:
    """Filter out unhelpful OCR content like menu bars, UI elements, etc.

    Aggressively removes lines that are unclear or mostly noise:
    - Menu bar items (File, Edit, View, etc.) even if garbled
    - Lines with too many special characters or symbols
    - Timestamps and date strings
    - Very short or meaningless lines
    - Lines that don't have enough readable text
    - Garbled text with mixed symbols and letters

    Args:
        lines: List of OCR-extracted text lines.

    Returns:
        Filtered list with cruft removed.
    """
    filtered = []

    def _line_has_context_signal(line: str) -> bool:
        lower = line.lower()
        return any(signal in lower for signal in OCR_CONTEXT_PRESERVE_SIGNALS)

    # Patterns to filter out
    menu_patterns = [
        r"^(File|Edit|View|History|Bookmarks|Develop|Window|Help|Go|Format|Insert|Tools|Window|Help)",
        r"^@\s*(File|Edit|View|History|Bookmarks|Develop|Window|Help|DrawThings)",
        r"^[A-Z][a-z]+\s+(Nov|Dec|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct)\s+\d{1,2}",  # Date strings
        r"^\d{1,2}:\d{2}(:\d{2})?\s*(AM|PM|UTC)?$",  # Time strings
        r"^[^\w\s]{3,}$",  # Mostly symbols
        r"^.{0,2}$",  # Very short lines (0-2 chars)
        r"^[^\w]*\d+[^\w]*$",  # Mostly numbers with symbols
    ]

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        if _line_has_context_signal(line_stripped):
            filtered.append(line_stripped)
            continue

        # Skip if matches any filter pattern
        skip = False
        for pattern in menu_patterns:
            if re.match(pattern, line_stripped, re.IGNORECASE):
                skip = True
                break

        if skip:
            continue

        # Count readable characters vs noise
        letters = len(re.findall(r'[a-zA-Z]', line_stripped))
        digits = len(re.findall(r'\d', line_stripped))
        symbols = len(re.findall(r'[^\w\s]', line_stripped))
        total_chars = len(line_stripped)

        # Skip empty or very short lines
        if total_chars < 3:
            continue

        # Skip lines that are mostly symbols (more than 35% symbols)
        if total_chars > 0 and symbols / total_chars > 0.35:
            continue

        # Skip lines with too few letters relative to length
        # Need at least 40% letters for meaningful content (more aggressive)
        if total_chars > 5 and letters / total_chars < 0.4:
            continue

        # Skip lines that are mostly numbers
        if total_chars > 8 and digits / total_chars > 0.5:
            continue

        # Skip lines with garbled menu bar patterns (menu words + lots of symbols)
        menu_words = ['file', 'edit', 'view', 'window', 'help', 'tools', 'format', 'insert', 'drawthings']
        has_menu_word = any(word in line_stripped.lower() for word in menu_words)
        if has_menu_word and (symbols > letters * 1.5 or symbols > 5):
            continue

        # Skip lines that start with symbols followed by menu words
        if re.match(r'^[@#\$%\^&\*\(\)\[\]\{\}]+.*(file|edit|view|window|help)', line_stripped, re.IGNORECASE):
            continue

        # Skip lines that look like timestamps or dates
        if re.search(r'\d{1,2}[:/]\d{1,2}([:/]\d{1,4})?', line_stripped) and letters < 4:
            continue

        # Skip lines that look like system stats/overlays (GPU, CPU, memory stats)
        # e.g., "PU GPU FS LOA U 12.808 U 21" or "47.095"
        if re.search(r'\b(gpu|cpu|mem|ram|fs|loa)\b', line_stripped, re.IGNORECASE) and digits > letters:
            continue
        if re.match(r'^[\d\s\.]+$', line_stripped) and len(line_stripped) < 20:  # Just numbers and dots
            continue
        if re.search(r'\b\d+\.\d{3,}\b', line_stripped) and letters < 3:  # Decimal numbers like 12.808, 47.095
            continue

        # Skip lines that are mostly single characters separated by symbols
        # e.g., "r ; 2 Snowflakes" or "F) 5 © ° %"
        words = line_stripped.split()
        single_char_words = sum(1 for w in words if len(w) == 1)
        if len(words) > 0 and single_char_words / len(words) > 0.5 and total_chars < 20:
            continue

        # Skip lines that start with symbols followed by garbled text
        # e.g., "@ Ciera vist Snowflakes By kK Tools 3"
        if re.match(r'^[@#\$%\^&\*\(\)\[\]\{\}]+', line_stripped) and symbols > letters * 0.8:
            continue

        # Skip lines with excessive symbol density (more than 1 symbol per 3 chars)
        if total_chars > 15 and symbols > total_chars / 3:
            continue

        # Final check: if line is "garbled" (too many symbols interspersed), skip it
        # Count consecutive symbol sequences - if there are many, it's probably garbled
        symbol_sequences = len(re.findall(r'[^\w\s]{2,}', line_stripped))
        if symbol_sequences > 3 and symbols > letters * 0.5:
            continue

        # Skip lines where symbols are densely packed (more than 2 symbols in a row appears multiple times)
        dense_symbol_pattern = r'[^\w\s]{3,}'
        dense_symbols = len(re.findall(dense_symbol_pattern, line_stripped))
        if dense_symbols > 2:
            continue

        # Skip lines with too many special characters mixed in (garbled text)
        # If more than 30% of non-space chars are symbols, it's probably noise
        non_space = total_chars - line_stripped.count(' ')
        if non_space > 0 and symbols / non_space > 0.3:
            # But allow if it has a URL or email pattern
            if not (RE_URL.search(line_stripped) or RE_EMAIL.search(line_stripped)):
                continue

        # Skip lines that are just symbols and numbers with minimal text
        if letters < 3 and symbols + digits > letters * 2:
            continue

        # Keep lines that have enough readable content
        filtered.append(line_stripped)

    return filtered


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
    vision_result: Optional[Dict[str, Any]] = None,
) -> str:
    """Build a prompt for LLM-based activity summarization.

    Constructs a structured prompt that guides the LLM to analyze screenshot
    context and generate a concise summary with task classification.
    Includes vision analysis context if available.

    Args:
        cfg: Configuration dictionary containing max_ocr_lines and other settings.
        app: Name of the active application.
        window_title: Title of the active window.
        ocr_top: Top OCR lines extracted from the screenshot.
        projects: List of known project names for context.
        clues: Dictionary of extracted clues (URLs, domains, tokens).
        vision_result: Optional vision analysis result dictionary.

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

    # Include vision analysis context if available
    vision_context = ""
    if vision_result:
        vision_apps = vision_result.get("apps_visible", [])
        vision_layout = vision_result.get("layout_description", "")
        vision_activity = vision_result.get("primary_activity", "")
        if vision_apps or vision_layout or vision_activity:
            vision_context = "\n\nVISION ANALYSIS CONTEXT (from image understanding):"
            if vision_apps:
                vision_context += f"\n- Apps visible: {', '.join(vision_apps)}"
            if vision_layout:
                vision_context += f"\n- Layout: {vision_layout}"
            if vision_activity:
                vision_context += f"\n- Primary activity detected: {vision_activity}"
            vision_context += "\n(Use this visual understanding to enhance your analysis)"

    prompt = f"""You are labeling a work activity snapshot. Analyze the context and return a JSON response.

TASK TAXONOMY (choose exactly one): {taxonomy}

CONTEXT:
- App: {app}
- Window Title: {window_title}
- OCR Text (visible on screen):
{ocr_block}
- URLs/Domains: {clues.get('urls', [])[:3]}{project_hint}{vision_context}

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


def build_vision_analysis_prompt(projects: List[str] = None) -> str:
    """Build a prompt for comprehensive vision-based image analysis.

    Creates a structured prompt that guides the vision model to understand
    the entire screenshot scene, not just extract text.

    Args:
        projects: Optional list of known project names for context.

    Returns:
        Formatted prompt string for vision analysis.
    """
    project_hint = ""
    if projects:
        project_hint = f"\n- Known Projects: {', '.join(projects)}"

    prompt = f"""Analyze this screenshot image comprehensively. Identify all visible applications, windows, and activities.

Return a JSON object with the following structure:

{{
  "apps_visible": ["App1", "App2"],
  "primary_app": "AppName",
  "window_titles": ["Window Title 1", "Window Title 2"],
  "primary_window_title": "Main Window Title",
  "layout": "single-window|dual-pane|multi-window|split-screen",
  "layout_description": "Brief description of screen layout",
  "primary_activity": "What the user is primarily doing",
  "secondary_activities": ["Activity 1", "Activity 2"],
  "project_indicators": ["github.com/user/repo", "project-name", "file.py"],
  "summary": "Concise description of the work activity (≤16 words)",
  "coarse_task": "Coding|Research|Comms|Build|Test|Design|Meeting|Admin|Idle|Unknown",
  "confidence": 0.0-1.0
}}

GUIDELINES:
1. Identify ALL visible applications (not just the frontmost)
2. For dual-pane/split screens, identify both sides
3. Extract window titles from visible windows (not just menu bars)
4. Distinguish between UI chrome (menus, toolbars) and actual content
5. Identify project indicators: GitHub URLs, repo names, file paths, project names
6. Primary activity should describe what the user is doing, not just the app name
7. Confidence should reflect how clear the activity is from visual context
8. If multiple apps visible, describe the primary focus{project_hint}

Return ONLY valid JSON, no other text."""
    return prompt


def build_historian_prompt(ocr_lines: List[str]) -> str:
    """Build prompt for historian analysis.

    Creates a detailed prompt for generating a comprehensive activity historian
    report from OCR text extracted from a screenshot.

    Args:
        ocr_lines: List of OCR-extracted text lines from the screenshot.

    Returns:
        Formatted prompt string for historian analysis.
    """
    ocr_block = "\n".join(ocr_lines)
    return (
        "You are an activity historian. Analyze the OCR text from a screenshot and write a detailed account of what the user was doing, suitable for a work log.\n\n"
        "Return Markdown only (no preface, no extra commentary), using exactly these section headings:\n\n"
        "## What was happening\n- A clear description of the user's primary task (what they were doing) in 2-4 sentences.\n\n"
        "## Why (likely intent)\n- Briefly explain the plausible goal(s) driving this task.\n\n"
        "## Sub-tasks and steps\n- Bullet list of concrete actions or sub-steps visible or strongly implied.\n\n"
        "## Evidence (from the screenshot)\n- 4-8 bullets citing specific on-screen cues (UI labels, titles, text snippets, filenames, domains). Quote exact text where useful.\n\n"
        "## Tools and context\n- App(s) in focus and any notable services/sites. If multiple apps are visible, only name one as \"in focus\" if unambiguous; otherwise write \"Unclear.\"\n- Any visible files, repos, docs, or environments (quote exact names).\n\n"
        "## Related project(s)\n- Short project/repo/doc names if strongly indicated; otherwise \"Unknown\".\n\n"
        "## Time and scope estimate\n- Rough estimate of how long this kind of task block would take (e.g., \"~10-20 minutes\"), based only on what's visible.\n\n"
        "## Uncertainties\n- List any ambiguities and what additional signals would resolve them.\n\n"
        "## Likely next actions\n- 3-5 bullets of what the user would logically do next.\n\n"
        "Rules:\n- Be concrete and rely only on what's visible.\n- Do not infer editor/tool names unless visible; quote exact window/tab text when naming tools.\n- If something is unclear, say so under \"Uncertainties.\"\n- Keep the narrative precise and useful for future review.\n\n"
        f"OCR:\n{ocr_block}\n"
    )
