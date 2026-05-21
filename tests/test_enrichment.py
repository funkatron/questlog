"""Unit tests for pattern-based OCR enrichment (not fixture-specific)."""

from ql.enrichment import (
    choose_window_title_from_ocr,
    detect_browser_content,
    detect_work_tracking_context,
    has_dual_context,
    is_ambient_ocr_fragment,
    is_low_signal_title,
    is_weak_window_title,
    refine_summary_and_task,
    refine_task_from_content,
    suggests_multitasking_during_call,
)


def test_ambient_fragments_are_not_used_as_titles():
    assert is_ambient_ocr_fragment("Mon Apr 27")
    assert is_ambient_ocr_fragment("WBD internal check in")
    assert not is_ambient_ocr_fragment("Workflow runs")


def test_low_signal_title_rejects_menu_bar_garble():
    assert is_low_signal_title("WWindow", "Draw Things")
    assert is_low_signal_title("Cruft", "Draw Things")
    assert is_low_signal_title("File", "Cursor")
    assert not is_weak_window_title("Cursor", "Cursor")
    assert is_weak_window_title("Google Chrome", "Google Chrome")


def test_choose_title_prefers_meeting_over_workplace_for_zoom():
    title = choose_window_title_from_ocr(
        "Zoom Workplace",
        ["Zoom", "Workplace", "Meeting", "Help"],
    )
    assert title == "Meeting"


def test_choose_title_rejects_ambient_bleed_for_editor_apps():
    title = choose_window_title_from_ocr(
        "Cursor",
        ["Cursor", "Selection", "Run", "WBD internal check in", "now"],
    )
    assert title == "Cursor"


def test_choose_title_uses_browser_hint_for_non_browser_frontmost_noise():
    title = choose_window_title_from_ocr(
        "Draw Things",
        ["Draw", "Image", "Window", "check in", "Mon"],
    )
    assert title in {"Safari", "browser"}


def test_dual_context_when_non_browser_frontmost_has_only_menu_bar_ocr():
    lines = ["Draw", "Image", "Window", "Help", "Mon"]
    assert has_dual_context("Draw Things", " ".join(lines).lower(), {}, lines)
    assert not has_dual_context("Safari", "workflow runs", {}, ["Workflow runs"])


def test_browser_content_detection_uses_urls_and_page_signals():
    assert detect_browser_content("workflow runs in github.com/funkatron/questlog")
    assert detect_browser_content("", {"urls": ["https://linear.app/team/issue/1"]})


def test_work_tracking_and_call_patterns():
    ocr = "campaigns accounts workflow runs edit advertiser"
    assert detect_work_tracking_context(ocr)
    assert suggests_multitasking_during_call(ocr)
    assert refine_task_from_content("Safari", ocr) == "Meeting"


def test_refine_summary_for_editor_dev_chrome():
    refined = refine_summary_and_task(
        "Cursor",
        "Unknown",
        ["Cursor", "Selection", "Run", "Terminal"],
        "Coding",
        {},
    )
    assert refined.summary == "Coding in Cursor"
    assert refined.coarse_task == "Coding"


def test_refine_summary_for_dual_context_non_browser_frontmost():
    refined = refine_summary_and_task(
        "Figma",
        "Safari",
        ["File", "Edit", "View", "Mon", "Apr"],
        "Design",
        {},
    )
    assert "Browsing in" in refined.summary
    assert "Figma frontmost" in refined.summary
    assert refined.coarse_task == "Research"


def test_refine_summary_for_work_tracking_in_browser():
    refined = refine_summary_and_task(
        "Safari",
        "Workflow runs",
        ["Campaigns", "Workflow runs", "Accounts"],
        "Research",
        {},
    )
    assert "Linear" in refined.summary or "work tracking" in refined.summary.lower()
    assert refined.coarse_task == "Meeting"


def test_refine_summary_for_comms_check_in_pattern():
    refined = refine_summary_and_task(
        "Slack",
        "WBD internal check in",
        ["Slack", "WBD internal check in", "Mon"],
        "Comms",
        {},
    )
    assert "check-in" in refined.summary.lower()
