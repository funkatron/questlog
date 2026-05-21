"""Pattern-based OCR enrichment for app, title, task, and summary inference."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from typing import Any

from ql.vocabulary import (
    AMBIENT_DATE_TIME_FRAGMENTS,
    APP_INFERENCE_RULES,
    APP_WHERE_NAME_IS_VALID_TITLE,
    BROWSER_APPS,
    BROWSER_CONTENT_SIGNALS,
    BROWSER_CONTEXT_TITLE_SIGNALS,
    BROWSER_WORK_UI_SIGNALS,
    BrowserLabel,
    ClueKey,
    CODING_APPS,
    CODING_TASK_KEYWORDS,
    COMMS_APPS,
    DEFAULT_TASK_BY_APP,
    DevUiToken,
    DomainSuffix,
    GENERIC_MEETING_TITLE_TOKENS,
    GENERIC_TITLE_SKIP_TOKENS,
    MEETING_APPS,
    MEETING_SIGNALS,
    MenuToken,
    NON_BROWSER_FRONTMOST_APPS,
    OcrSignal,
    PLACEHOLDER_TITLES,
    Placeholder,
    SAFARI_TITLE_KEYWORD_BONUSES,
    SummaryPhrase,
    Task,
    App,
    AppSlug,
    TITLE_KEYWORD_BONUSES,
    TitleScoreWeight,
    WEAK_BROWSER_TITLES,
    WORK_TRACKING_SIGNALS,
    WORK_TRACKING_TOOLS,
    WorkTrackingLabel,
    norm_text,
)


@dataclass(frozen=True)
class SummaryRefinement:
    summary: str
    coarse_task: str


def is_ambient_ocr_fragment(text: str, app: str = "") -> bool:
    """Return whether OCR text looks like clock/date/noise rather than task content."""
    norm = norm_text(text)
    if not norm:
        return True
    if any(fragment in norm for fragment in AMBIENT_DATE_TIME_FRAGMENTS):
        return True
    # Check-in text outside comms apps is usually notification bleed, not the active task.
    if OcrSignal.CHECK_IN in norm and app not in COMMS_APPS:
        return True
    return False


def is_menu_bar_token(text: str) -> bool:
    """Return whether OCR text is likely a menu bar item."""
    return norm_text(text) in MenuToken.ALL


def resembles_menu_bar_garble(text: str) -> bool:
    """Return whether OCR text looks like a garbled menu-bar token."""
    norm = norm_text(text)
    if not norm:
        return True
    return any(
        len(token) >= TitleScoreWeight.MIN_TITLE_LENGTH and (token in norm or norm in token)
        for token in MenuToken.ALL
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
        if len(norm) < TitleScoreWeight.SHORT_NON_BROWSER_TITLE_MAX and not any(
            keyword in norm for keyword in TITLE_KEYWORD_BONUSES
        ):
            return True
    if len(norm) < TitleScoreWeight.MIN_TITLE_LENGTH:
        return True
    return False


def detect_browser_content(ocr_text: str, clues: dict[str, Any] | None = None) -> bool:
    """Return whether OCR/clues suggest browser-visible content."""
    clues = clues or {}
    haystack = ocr_text.lower()
    if any(signal in haystack for signal in BROWSER_CONTENT_SIGNALS):
        return True
    return any(
        OcrSignal.HTTP in str(url).lower() or OcrSignal.HTTPS in str(url).lower()
        for url in clues.get(ClueKey.URLS, [])
    )


def detect_meeting_context(ocr_text: str) -> bool:
    """Return whether OCR suggests an active meeting or call."""
    haystack = ocr_text.lower()
    return any(signal in haystack for signal in MEETING_SIGNALS)


def detect_work_tracking_context(ocr_text: str) -> bool:
    """Return whether OCR suggests issue/work-tracking UI."""
    haystack = ocr_text.lower()
    return any(signal in haystack for signal in WORK_TRACKING_SIGNALS)


def detect_video_call_sidebar(ocr_text: str) -> bool:
    """Return whether OCR suggests a video-call sidebar alongside other UI."""
    haystack = ocr_text.lower()
    return bool(re.search(r"\bcam\b", haystack)) and detect_work_tracking_context(haystack)


def suggests_multitasking_during_call(ocr_text: str) -> bool:
    """Return whether OCR suggests work UI open alongside a likely call."""
    haystack = ocr_text.lower()
    has_work = detect_work_tracking_context(haystack)
    has_meeting = detect_meeting_context(haystack)
    if has_work and has_meeting:
        return True
    if has_work and detect_video_call_sidebar(haystack):
        return True
    return (
        has_work
        and OcrSignal.CAMPAIGNS in haystack
        and OcrSignal.ACCOUNTS in haystack
    )


def infer_work_tracking_label(ocr_text: str) -> str | None:
    """Infer a work-tracking tool label from OCR when evidence exists."""
    haystack = ocr_text.lower()
    for tool in WORK_TRACKING_TOOLS:
        if any(pattern in haystack for pattern in tool.patterns):
            return tool.label
    if detect_work_tracking_context(haystack):
        return WorkTrackingLabel.GENERIC
    return None


def default_browser_label() -> str:
    """Return a platform-default browser label when OCR lacks explicit browser text."""
    if sys.platform == "darwin":
        return BrowserLabel.SAFARI
    return BrowserLabel.GENERIC


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
    if OcrSignal.SAFARI in haystack or OcrSignal.ICLOUD in haystack:
        return BrowserLabel.SAFARI
    if OcrSignal.CHROME in haystack or OcrSignal.GOOGLE_CHROME in haystack:
        return BrowserLabel.CHROME
    domains = [str(domain).lower() for domain in clues.get(ClueKey.DOMAINS, [])]
    if any(
        domain.endswith((DomainSuffix.YOUTUBE, DomainSuffix.GITHUB, DomainSuffix.LINEAR))
        for domain in domains
    ):
        return BrowserLabel.SAFARI
    if detect_browser_content(haystack, clues):
        return BrowserLabel.GENERIC
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
    generic = set(MenuToken.ALL)
    generic.update(GENERIC_TITLE_SKIP_TOKENS)
    generic.add(app_norm)
    if app_norm == AppSlug.ZOOM_WORKPLACE:
        generic.discard(OcrSignal.MEETING)
        generic.discard(OcrSignal.WORKPLACE)
    if app_norm == AppSlug.CURSOR:
        generic.discard(AppSlug.CURSOR)
        generic.update(DevUiToken.ALL)
    return generic


def pick_browser_context_title(ocr_lines: list[str]) -> str | None:
    """Pick a browser window title from visible page/tab content signals."""
    haystack = " ".join(ocr_lines).lower()
    for signal, label in BROWSER_CONTEXT_TITLE_SIGNALS:
        if signal not in haystack:
            continue
        for line in ocr_lines:
            line_norm = norm_text(line)
            if signal in line_norm:
                if signal in {OcrSignal.ICLOUD, OcrSignal.YOUTUBE, OcrSignal.TABS}:
                    return label
                return line.strip()[:80]
        return label
    return None


def is_garbled_work_tracking_title(text: str) -> bool:
    """Return whether a title looks like OCR noise rather than a readable page title."""
    norm = norm_text(text)
    if not norm:
        return True
    if "/" in text and OcrSignal.LINEAR in norm:
        return True
    if len(norm) > 24 and not any(
        keyword in norm
        for keyword in (
            OcrSignal.ISSUES,
            OcrSignal.WORKFLOW,
            OcrSignal.WORKFLOW_RUNS,
            OcrSignal.CAMPAIGNS,
        )
    ):
        return True
    return False


def score_window_title_candidate(line: str, app: str, ocr_lines: list[str]) -> float:
    """Score one OCR line as a window-title candidate."""
    app_norm = norm_text(app)
    norm = norm_text(line)
    if norm in generic_title_skip_tokens(app):
        return float("-inf")
    if len(norm) < TitleScoreWeight.MIN_TITLE_LENGTH:
        return float("-inf")

    score = float(len(norm))
    if " " in norm:
        score += TitleScoreWeight.MULTI_WORD_BONUS
    if any(keyword in norm for keyword in TITLE_KEYWORD_BONUSES):
        score += TitleScoreWeight.KEYWORD_BONUS
    if is_ambient_ocr_fragment(norm, app):
        score -= TitleScoreWeight.AMBIENT_PENALTY
    if any(ch.isdigit() for ch in norm):
        score -= TitleScoreWeight.DIGIT_PENALTY

    if app_norm == AppSlug.SLACK and OcrSignal.CHECK_IN in norm:
        score += TitleScoreWeight.SLACK_CHECK_IN_BONUS
    if app_norm == AppSlug.ZOOM_WORKPLACE and OcrSignal.MEETING in norm:
        score += TitleScoreWeight.ZOOM_MEETING_BONUS
    if app_norm == AppSlug.CURSOR:
        if norm in DevUiToken.ALL:
            score += TitleScoreWeight.CURSOR_DEV_UI_BONUS
        if OcrSignal.CHECK_IN in norm:
            score -= TitleScoreWeight.CURSOR_CHECK_IN_PENALTY
        if norm == AppSlug.CURSOR:
            score += TitleScoreWeight.CURSOR_APP_NAME_BONUS
    if app_norm == AppSlug.SAFARI:
        if OcrSignal.CHECK_IN in norm:
            score -= TitleScoreWeight.NOTIFICATION_BLEED_PENALTY
        if any(token in norm for token in SAFARI_TITLE_KEYWORD_BONUSES):
            score += TitleScoreWeight.SAFARI_WORK_UI_BONUS
        elif len(norm) >= TitleScoreWeight.MIN_TITLE_LENGTH:
            score -= TitleScoreWeight.SAFARI_NON_CONTEXT_PENALTY
    return score


def _is_weak_browser_window_title(text: str) -> bool:
    """Return whether a browser window title looks like OCR junk rather than page content."""
    norm = norm_text(text)
    if not norm:
        return True
    if norm in {AppSlug.SAFARI, norm_text(BrowserLabel.SAFARI), norm_text(BrowserLabel.CHROME)}:
        return False
    if any(keyword in norm for keyword in SAFARI_TITLE_KEYWORD_BONUSES):
        return False
    if detect_browser_content(norm):
        return False
    return is_low_signal_title(text, App.SAFARI) or len(norm) < 18


def choose_window_title_from_ocr(app: str, ocr_lines: list[str]) -> str:
    """Pick the strongest non-generic window-title candidate from OCR."""
    app_norm = norm_text(app)
    candidates: list[tuple[float, str]] = []
    for line in ocr_lines:
        score = score_window_title_candidate(line, app, ocr_lines)
        if score > float("-inf"):
            candidates.append((score, line))

    if not candidates:
        return app if app and app != Placeholder.UNKNOWN else Placeholder.UNKNOWN

    candidates.sort(reverse=True)
    best = candidates[0][1][:80]
    best_norm = norm_text(best)

    if app in BROWSER_APPS:
        context_title = pick_browser_context_title(ocr_lines)
        if context_title and (
            _is_weak_browser_window_title(best)
            or not any(token in best_norm for token in SAFARI_TITLE_KEYWORD_BONUSES)
        ):
            return context_title

    if app_norm == AppSlug.CURSOR and is_ambient_ocr_fragment(best):
        return app if app and app != Placeholder.UNKNOWN else best
    if app_norm == AppSlug.ZOOM_WORKPLACE and best_norm == OcrSignal.WORKPLACE:
        return Task.MEETING
    if app in BROWSER_APPS and _is_weak_browser_window_title(best):
        context_title = pick_browser_context_title(ocr_lines)
        if context_title:
            return context_title
        return infer_browser_label(" ".join(ocr_lines).lower()) or App.SAFARI
    if app in NON_BROWSER_FRONTMOST_APPS and is_low_signal_title(best, app):
        return infer_browser_label(" ".join(ocr_lines).lower()) or default_browser_label()
    return best


def is_weak_window_title(value: str, app: str = "") -> bool:
    """Return whether a window title is too generic to store as concrete context."""
    norm = norm_text(value)
    app_norm = norm_text(app)
    if norm in PLACEHOLDER_TITLES:
        return True
    if app_norm and norm == app_norm and app_norm not in APP_WHERE_NAME_IS_VALID_TITLE:
        return True
    return norm in WEAK_BROWSER_TITLES


def refine_task_from_content(app: str, ocr_text: str) -> str | None:
    """Return a task override when OCR content strongly suggests a different task."""
    haystack = ocr_text.lower()
    if app in BROWSER_APPS and suggests_multitasking_during_call(haystack):
        return Task.MEETING
    if app in CODING_APPS and any(token in haystack for token in CODING_TASK_KEYWORDS):
        return Task.CODING
    if app in COMMS_APPS and OcrSignal.CHECK_IN in haystack:
        return Task.COMMS
    if app in MEETING_APPS:
        return Task.MEETING
    return None


def fallback_summary_for_app(
    app: str,
    window_title: str,
    coarse_task: str,
    ocr_text: str = "",
) -> str:
    """Build a neutral summary when OCR only captured ambient chrome."""
    haystack = ocr_text.lower()
    if app in COMMS_APPS and OcrSignal.CHECK_IN in haystack:
        return SummaryPhrase.check_in_conversation(app)
    if app in COMMS_APPS:
        return SummaryPhrase.conversation(app)
    if app in MEETING_APPS:
        return SummaryPhrase.meeting_in_app(app)
    if app in CODING_APPS:
        return SummaryPhrase.coding_in_app(app)
    if app in BROWSER_APPS:
        if window_title and window_title != Placeholder.UNKNOWN:
            return SummaryPhrase.title_in_app(window_title, app)
        return SummaryPhrase.browsing_in_app(app)
    if coarse_task != Task.UNKNOWN:
        return SummaryPhrase.task_in_app(coarse_task, app)
    return SummaryPhrase.using_app(app)


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
    if not summary or summary == Placeholder.UNKNOWN:
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

    if app in MEETING_APPS and norm_text(summary) in GENERIC_MEETING_TITLE_TOKENS:
        summary = SummaryPhrase.meeting_in_app(app)

    if app in CODING_APPS and norm_text(summary) in DevUiToken.ALL:
        summary = SummaryPhrase.coding_in_app(app)

    if app in BROWSER_APPS and (
        _is_weak_browser_window_title(summary)
        or _is_weak_browser_window_title(window_title)
        or norm_text(summary) == norm_text(app)
        or norm_text(window_title) == norm_text(app)
    ):
        summary = SummaryPhrase.browsing_in_app(app)

    if has_dual_context(app, ocr_text, clues, ocr_lines):
        browser = infer_browser_label(ocr_text, clues) or default_browser_label()
        summary = SummaryPhrase.browsing_with_frontmost(browser, app)
        if task in {Task.UNKNOWN, Task.DESIGN}:
            task = Task.RESEARCH

    if detect_work_tracking_context(ocr_text):
        label = infer_work_tracking_label(ocr_text)
        multitasking = suggests_multitasking_during_call(ocr_text)
        if multitasking:
            task = Task.MEETING
        base = window_title if window_title not in {Placeholder.EMPTY, Placeholder.UNKNOWN} else summary
        if (
            label
            and label != WorkTrackingLabel.GENERIC
            and multitasking
            and "zoom" not in norm_text(base)
        ):
            summary = SummaryPhrase.work_items_during_call(label, app)
        elif label and label != WorkTrackingLabel.GENERIC and (
            is_garbled_work_tracking_title(base)
            or _is_weak_browser_window_title(base)
        ):
            if multitasking:
                summary = SummaryPhrase.work_items_during_call(label, app)
            else:
                summary = SummaryPhrase.work_issues_in_app(label, app)
        elif label and norm_text(label) not in norm_text(base):
            summary = SummaryPhrase.labeled_work_item(label, base)
            if app in BROWSER_APPS and " in " not in norm_text(summary):
                summary = SummaryPhrase.title_in_app(summary, app)

    summary = summary.strip() or fallback_summary_for_app(app, window_title, task, ocr_text)
    return SummaryRefinement(summary=summary[:160], coarse_task=task)


def infer_app_from_content(window_title: str, ocr_lines: list[str]) -> str:
    """Infer application name from window title and OCR content."""
    combined_text = " ".join([window_title] + ocr_lines).lower()

    if detect_browser_content(combined_text):
        return App.SAFARI

    if OcrSignal.ZOOM in combined_text and (
        OcrSignal.WORKPLACE in combined_text or OcrSignal.MEETING in combined_text
    ):
        return next(rule.app for rule in APP_INFERENCE_RULES if rule.slug == AppSlug.ZOOM_WORKPLACE)

    for rule in APP_INFERENCE_RULES:
        if any(keyword in combined_text for keyword in rule.keywords):
            return rule.app

    title_lower = window_title.lower()
    if any(ext in title_lower for ext in (".py", ".js", ".ts", ".md")):
        if AppSlug.CURSOR in title_lower or OcrSignal.GITHUB_COM in combined_text:
            return next(rule.app for rule in APP_INFERENCE_RULES if rule.slug == AppSlug.CURSOR)
        return next(rule.app for rule in APP_INFERENCE_RULES if rule.slug == AppSlug.CODE)

    if OcrSignal.TERMINAL in title_lower or "iterm" in title_lower:
        return next(rule.app for rule in APP_INFERENCE_RULES if rule.slug == AppSlug.TERMINAL)

    if OcrSignal.GITHUB_COM in combined_text or OcrSignal.REPOSITORY in combined_text:
        return next(rule.app for rule in APP_INFERENCE_RULES if rule.slug == AppSlug.GITHUB)

    if OcrSignal.README in combined_text and (
        "github" in combined_text or ".md" in combined_text
    ):
        return next(rule.app for rule in APP_INFERENCE_RULES if rule.slug == AppSlug.CURSOR)

    if any(token in combined_text for token in BROWSER_WORK_UI_SIGNALS):
        return next(rule.app for rule in APP_INFERENCE_RULES if rule.slug == AppSlug.SAFARI)

    return Placeholder.UNKNOWN
