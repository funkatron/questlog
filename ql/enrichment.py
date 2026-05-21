"""Pattern-based OCR enrichment for app, title, task, and summary inference."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any


BROWSER_APPS = frozenset(
    {"Safari", "Google Chrome", "Arc", "Firefox", "Browser", "Chrome"}
)
CODING_APPS = frozenset(
    {
        "Cursor",
        "Code",
        "Visual Studio Code",
        "Xcode",
        "Terminal",
        "iTerm2",
        "PyCharm",
        "WebStorm",
        "GoLand",
        "DataGrip",
    }
)
MEETING_APPS = frozenset({"Zoom Workplace", "Zoom", "Calendar", "Google Meet", "Teams"})
COMMS_APPS = frozenset({"Slack", "Discord", "Mail", "Spark"})
NON_BROWSER_FRONTMOST_APPS = frozenset({"Draw Things", "Figma", "Photos", "Preview"})

APP_WHERE_NAME_IS_VALID_TITLE = frozenset({"cursor", "slack", "zoom workplace"})

AMBIENT_OCR_FRAGMENTS = (
    "check in",
    "single image",
    "movies",
    "mon",
    "apr",
    "may",
    "jun",
    "today",
    "now",
)

MENU_BAR_TOKENS = frozenset(
    {
        "file",
        "edit",
        "view",
        "window",
        "help",
        "run",
        "terminal",
        "selection",
        "zoom",
        "draw",
        "image",
        "history",
        "bookmarks",
        "go",
        "format",
        "tools",
    }
)

DEV_UI_TOKENS = frozenset({"selection", "run", "terminal", "unknown"})

MEETING_SIGNALS = (
    "zoom",
    "meeting",
    "participants",
    "workplace",
)

WORK_TRACKING_SIGNALS = (
    "workflow runs",
    "issues",
    "campaigns",
    "edit advertiser",
    "linear",
    "linear.app",
    "jira",
    "asana",
    "backlog",
)

BROWSER_CONTENT_SIGNALS = (
    "youtube",
    "github.com",
    "workflow runs",
    "linear.app",
    "icloud",
    "safari",
    "chrome",
    "http://",
    "https://",
    "www.",
    "tabs",
)

WORK_TRACKING_TOOL_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Linear", ("linear", "linear.app", "workflow runs")),
    ("Jira", ("jira", "sprint board")),
    ("Asana", ("asana",)),
)

TITLE_KEYWORD_BONUSES = (
    "issue",
    "workflow",
    "youtube",
    "campaign",
    "linear",
    "workplace",
    "meeting",
    "check in",
)

WEAK_BROWSER_TITLES = frozenset(
    {
        "google chrome",
        "chrome - google chrome",
        "visual studio code",
    }
)


def norm_text(value: str) -> str:
    """Normalize text for loose heuristic matching."""
    return " ".join((value or "").strip().lower().split())


def is_ambient_ocr_fragment(text: str) -> bool:
    """Return whether OCR text looks like clock/date/chrome rather than task content."""
    norm = norm_text(text)
    if not norm:
        return True
    return any(fragment in norm for fragment in AMBIENT_OCR_FRAGMENTS)


def is_menu_bar_token(text: str) -> bool:
    """Return whether OCR text is likely a menu bar item."""
    return norm_text(text) in MENU_BAR_TOKENS


def resembles_menu_bar_garble(text: str) -> bool:
    """Return whether OCR text looks like a garbled menu-bar token."""
    norm = norm_text(text)
    if not norm:
        return True
    return any(
        len(token) >= 4 and (token in norm or norm in token)
        for token in MENU_BAR_TOKENS
    )


def is_low_signal_title(text: str, app: str = "") -> bool:
    """Return whether a title candidate carries little restart value."""
    norm = norm_text(text)
    app_norm = norm_text(app)
    if not norm:
        return True
    if app_norm and norm == app_norm and app_norm not in APP_WHERE_NAME_IS_VALID_TITLE:
        return True
    if is_menu_bar_token(norm):
        return True
    if is_ambient_ocr_fragment(norm):
        return True
    if resembles_menu_bar_garble(text):
        return True
    if app_norm in {norm_text(name) for name in NON_BROWSER_FRONTMOST_APPS}:
        if len(norm) < 12 and not any(keyword in norm for keyword in TITLE_KEYWORD_BONUSES):
            return True
    if len(norm) < 4:
        return True
    return False


def detect_browser_content(ocr_text: str, clues: dict[str, Any] | None = None) -> bool:
    """Return whether OCR/clues suggest browser-visible content."""
    clues = clues or {}
    haystack = ocr_text.lower()
    if any(signal in haystack for signal in BROWSER_CONTENT_SIGNALS):
        return True
    return any("http" in str(url).lower() for url in clues.get("urls", []))


def detect_meeting_context(ocr_text: str) -> bool:
    """Return whether OCR suggests an active meeting or call."""
    haystack = ocr_text.lower()
    return any(signal in haystack for signal in MEETING_SIGNALS)


def detect_work_tracking_context(ocr_text: str) -> bool:
    """Return whether OCR suggests issue/work-tracking UI."""
    haystack = ocr_text.lower()
    return any(signal in haystack for signal in WORK_TRACKING_SIGNALS)


def suggests_multitasking_during_call(ocr_text: str) -> bool:
    """Return whether OCR suggests work UI open alongside a likely call."""
    haystack = ocr_text.lower()
    has_work = detect_work_tracking_context(haystack)
    has_meeting = detect_meeting_context(haystack)
    if has_work and has_meeting:
        return True
    # Admin/campaign UI plus work-tracking often appears during screen-share calls.
    return has_work and "campaigns" in haystack and "accounts" in haystack


def infer_work_tracking_label(ocr_text: str) -> str | None:
    """Infer a work-tracking tool label from OCR when evidence exists."""
    haystack = ocr_text.lower()
    for label, patterns in WORK_TRACKING_TOOL_HINTS:
        if any(pattern in haystack for pattern in patterns):
            return label
    if detect_work_tracking_context(haystack):
        return "work tracking"
    return None


def default_browser_label() -> str:
    """Return a platform-default browser label when OCR lacks explicit browser text."""
    if sys.platform == "darwin":
        return "Safari"
    return "browser"


def ocr_is_mostly_low_signal(ocr_lines: list[str], app: str) -> bool:
    """Return whether OCR lines are mostly menu, ambient, or other low-signal noise."""
    if not ocr_lines:
        return False
    meaningful = [
        line
        for line in ocr_lines
        if line.strip() and not is_low_signal_title(line, app)
    ]
    return len(meaningful) == 0


def infer_browser_label(ocr_text: str, clues: dict[str, Any] | None = None) -> str | None:
    """Infer a browser label from OCR/clues when browser content is visible."""
    clues = clues or {}
    haystack = ocr_text.lower()
    if "safari" in haystack or "icloud" in haystack:
        return "Safari"
    if "chrome" in haystack or "google chrome" in haystack:
        return "Chrome"
    domains = [str(domain).lower() for domain in clues.get("domains", [])]
    if any(domain.endswith(("youtube.com", "github.com", "linear.app")) for domain in domains):
        return "Safari"
    if detect_browser_content(haystack, clues):
        return "browser"
    return None


def has_dual_context(
    frontmost_app: str,
    ocr_text: str,
    clues: dict[str, Any] | None = None,
    ocr_lines: list[str] | None = None,
) -> bool:
    """Return whether menu-bar/frontmost app likely differs from visible browser content."""
    if frontmost_app in BROWSER_APPS:
        return False
    if frontmost_app in NON_BROWSER_FRONTMOST_APPS:
        if detect_browser_content(ocr_text, clues):
            return True
        if ocr_lines and ocr_is_mostly_low_signal(ocr_lines, frontmost_app):
            return True
        return False
    if frontmost_app in CODING_APPS:
        return detect_browser_content(ocr_text, clues)
    return False


def generic_title_skip_tokens(app: str) -> set[str]:
    """Return OCR tokens that are too generic to use as a window title for this app."""
    app_norm = norm_text(app)
    generic = set(MENU_BAR_TOKENS)
    generic.update({"", "unknown", app_norm, "meeting", "workplace", "cursor", "slack", "zoom"})
    if app_norm == "zoom workplace":
        generic.discard("meeting")
        generic.discard("workplace")
    if app_norm == "cursor":
        generic.discard("cursor")
        generic.update(DEV_UI_TOKENS)
    return generic


def score_window_title_candidate(line: str, app: str, ocr_lines: list[str]) -> float:
    """Score one OCR line as a window-title candidate."""
    app_norm = norm_text(app)
    norm = norm_text(line)
    if norm in generic_title_skip_tokens(app):
        return float("-inf")
    if len(norm) < 4:
        return float("-inf")

    score = float(len(norm))
    if " " in norm:
        score += 4.0
    if any(keyword in norm for keyword in TITLE_KEYWORD_BONUSES):
        score += 6.0
    if is_ambient_ocr_fragment(norm):
        score -= 16.0
    if any(ch.isdigit() for ch in norm):
        score -= 8.0

    if app_norm == "slack" and "check in" in norm:
        score += 12.0
    if app_norm == "zoom workplace" and "meeting" in norm:
        score += 18.0
    if app_norm == "cursor":
        if norm in DEV_UI_TOKENS:
            score += 18.0
        if "check in" in norm:
            score -= 30.0
        if norm == "cursor":
            score += 25.0
    if app_norm == "safari" and any(token in norm for token in ("workflow", "campaign", "issue", "accounts")):
        score += 8.0
    return score


def choose_window_title_from_ocr(app: str, ocr_lines: list[str]) -> str:
    """Pick the strongest non-generic window-title candidate from OCR."""
    app_norm = norm_text(app)
    candidates: list[tuple[float, str]] = []
    for line in ocr_lines:
        score = score_window_title_candidate(line, app, ocr_lines)
        if score > float("-inf"):
            candidates.append((score, line))

    if not candidates:
        return app if app and app != "Unknown" else "Unknown"

    candidates.sort(reverse=True)
    best = candidates[0][1][:80]
    best_norm = norm_text(best)

    if app_norm == "cursor" and is_ambient_ocr_fragment(best):
        return app if app and app != "Unknown" else best
    if app_norm == "zoom workplace" and best_norm == "workplace":
        return "Meeting"
    if app in NON_BROWSER_FRONTMOST_APPS and is_low_signal_title(best, app):
        return infer_browser_label(" ".join(ocr_lines).lower()) or default_browser_label()
    return best


def is_weak_window_title(value: str, app: str = "") -> bool:
    """Return whether a window title is too generic to store as concrete context."""
    norm = norm_text(value)
    app_norm = norm_text(app)
    if norm in {"", "unknown", "main window", "main window title", "window", "window title"}:
        return True
    if app_norm and norm == app_norm and app_norm not in APP_WHERE_NAME_IS_VALID_TITLE:
        return True
    return norm in WEAK_BROWSER_TITLES


def refine_task_from_content(app: str, ocr_text: str) -> str | None:
    """Return a task override when OCR content strongly suggests a different task."""
    haystack = ocr_text.lower()
    if app in BROWSER_APPS and suggests_multitasking_during_call(haystack):
        return "Meeting"
    if app in CODING_APPS and any(token in haystack for token in ("pytest", ".py", "terminal", "git ")):
        return "Coding"
    if app in COMMS_APPS and "check in" in haystack:
        return "Comms"
    if app in MEETING_APPS:
        return "Meeting"
    return None


@dataclass(frozen=True)
class SummaryRefinement:
    summary: str
    coarse_task: str


def fallback_summary_for_app(
    app: str,
    window_title: str,
    coarse_task: str,
    ocr_text: str = "",
) -> str:
    """Build a neutral summary when OCR only captured ambient chrome."""
    haystack = ocr_text.lower()
    if app in COMMS_APPS and "check in" in haystack:
        return f"{app} check-in conversation"
    if app in COMMS_APPS:
        return f"{app} conversation"
    if app in MEETING_APPS:
        return f"Meeting in {app}"
    if app in CODING_APPS:
        return f"Coding in {app}"
    if app in BROWSER_APPS:
        if window_title and window_title != "Unknown":
            return f"{window_title} in {app}"
        return f"Browsing in {app}"
    if coarse_task != "Unknown":
        return f"{coarse_task} in {app}"
    return f"Using {app}"


def refine_summary_and_task(
    app: str,
    window_title: str,
    ocr_lines: list[str],
    coarse_task: str,
    clues: dict[str, Any] | None = None,
) -> SummaryRefinement:
    """Apply cross-app enrichment patterns to summary and task."""
    clues = clues or {}
    ocr_text = " ".join(ocr_lines).lower()
    summary = (window_title or "").strip()
    if not summary or summary == "Unknown":
        summary = ocr_lines[0].strip() if ocr_lines else ""

    if app and summary and norm_text(summary) == norm_text(app):
        for line in ocr_lines:
            if line and norm_text(line) != norm_text(app):
                summary = line.strip()
                break

    task = coarse_task
    task_override = refine_task_from_content(app, ocr_text)
    if task_override:
        task = task_override

    if is_ambient_ocr_fragment(summary) or is_low_signal_title(summary, app):
        summary = fallback_summary_for_app(app, window_title, task, ocr_text)

    if app in MEETING_APPS and norm_text(summary) in {"workplace", "meeting"}:
        summary = f"Meeting in {app}"

    if app in CODING_APPS and norm_text(summary) in DEV_UI_TOKENS:
        summary = f"Coding in {app}"

    if has_dual_context(app, ocr_text, clues, ocr_lines):
        browser = infer_browser_label(ocr_text, clues) or default_browser_label()
        summary = f"Browsing in {browser} with {app} frontmost"
        if task in {"Unknown", "Design"}:
            task = "Research"

    if detect_work_tracking_context(ocr_text):
        label = infer_work_tracking_label(ocr_text)
        if suggests_multitasking_during_call(ocr_text):
            task = "Meeting"
        base = window_title if window_title not in {"", "Unknown"} else summary
        if label and norm_text(label) not in norm_text(base):
            summary = f"{label} {base}".strip()
        if app in BROWSER_APPS and " in " not in norm_text(summary):
            summary = f"{summary} in {app}".strip()

    summary = summary.strip() or fallback_summary_for_app(app, window_title, task, ocr_text)
    return SummaryRefinement(summary=summary[:160], coarse_task=task)
