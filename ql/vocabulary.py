"""Shared vocabulary for apps, tasks, OCR signals, and enrichment constants."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


class Task:
    CODING: Final = "Coding"
    RESEARCH: Final = "Research"
    COMMS: Final = "Comms"
    BUILD: Final = "Build"
    TEST: Final = "Test"
    DESIGN: Final = "Design"
    MEETING: Final = "Meeting"
    ADMIN: Final = "Admin"
    IDLE: Final = "Idle"
    NOTES: Final = "Notes"
    UNKNOWN: Final = "Unknown"

    ALL: Final = frozenset(
        {
            CODING,
            RESEARCH,
            COMMS,
            BUILD,
            TEST,
            DESIGN,
            MEETING,
            ADMIN,
            IDLE,
            NOTES,
            UNKNOWN,
        }
    )


class App:
    SAFARI: Final = "Safari"
    CHROME: Final = "Google Chrome"
    CHROME_SHORT: Final = "Chrome"
    ARC: Final = "Arc"
    FIREFOX: Final = "Firefox"
    BROWSER: Final = "Browser"
    CURSOR: Final = "Cursor"
    CODE: Final = "Code"
    VSCODE: Final = "Visual Studio Code"
    XCODE: Final = "Xcode"
    TERMINAL: Final = "Terminal"
    ITERM: Final = "iTerm2"
    PYCHARM: Final = "PyCharm"
    WEBSTORM: Final = "WebStorm"
    GOLAND: Final = "GoLand"
    DATAGRIP: Final = "DataGrip"
    SLACK: Final = "Slack"
    DISCORD: Final = "Discord"
    MAIL: Final = "Mail"
    SPARK: Final = "Spark"
    OBSIDIAN: Final = "Obsidian"
    NOTES: Final = "Notes"
    FIGMA: Final = "Figma"
    DRAW_THINGS: Final = "Draw Things"
    PHOTOS: Final = "Photos"
    PREVIEW: Final = "Preview"
    ZOOM_WORKPLACE: Final = "Zoom Workplace"
    ZOOM: Final = "Zoom"
    CALENDAR: Final = "Calendar"
    GOOGLE_MEET: Final = "Google Meet"
    TEAMS: Final = "Teams"
    GITHUB: Final = "GitHub"
    UNKNOWN: Final = "Unknown"


class Placeholder:
    UNKNOWN: Final = "Unknown"
    EMPTY: Final = ""
    MAIN_WINDOW: Final = "main window"
    MAIN_WINDOW_TITLE: Final = "main window title"
    WINDOW: Final = "window"
    WINDOW_TITLE: Final = "window title"
    RECENT_ACTIVITY: Final = "Recent activity captured"
    USING_UNKNOWN: Final = "using unknown"


class BrowserLabel:
    SAFARI: Final = "Safari"
    CHROME: Final = "Chrome"
    GENERIC: Final = "browser"


class WorkTrackingLabel:
    GENERIC: Final = "work tracking"


class ClueKey:
    URLS: Final = "urls"
    DOMAINS: Final = "domains"
    REPO_TOKENS: Final = "repo_tokens"
    TOKENS: Final = "tokens"


class OcrSignal:
    CHECK_IN: Final = "check in"
    SINGLE_IMAGE: Final = "single image"
    MOVIES: Final = "movies"
    TODAY: Final = "today"
    NOW: Final = "now"
    ZOOM: Final = "zoom"
    MEETING: Final = "meeting"
    PARTICIPANTS: Final = "participants"
    WORKPLACE: Final = "workplace"
    WORKFLOW_RUNS: Final = "workflow runs"
    ISSUES: Final = "issues"
    CAMPAIGNS: Final = "campaigns"
    ACCOUNTS: Final = "accounts"
    EDIT_ADVERTISER: Final = "edit advertiser"
    LINEAR: Final = "linear"
    LINEAR_APP: Final = "linear.app"
    JIRA: Final = "jira"
    ASANA: Final = "asana"
    BACKLOG: Final = "backlog"
    YOUTUBE: Final = "youtube"
    GITHUB_COM: Final = "github.com"
    ICLOUD: Final = "icloud"
    SAFARI: Final = "safari"
    CHROME: Final = "chrome"
    GOOGLE_CHROME: Final = "google chrome"
    HTTP: Final = "http://"
    HTTPS: Final = "https://"
    WWW: Final = "www."
    TABS: Final = "tabs"
    PYTEST: Final = "pytest"
    PY_EXT: Final = ".py"
    TERMINAL: Final = "terminal"
    GIT_PREFIX: Final = "git "
    ISSUE: Final = "issue"
    WORKFLOW: Final = "workflow"
    CAMPAIGN: Final = "campaign"
    README: Final = "readme"
    REPOSITORY: Final = "repository"
    SPRINT_BOARD: Final = "sprint board"


class MenuToken:
    FILE: Final = "file"
    EDIT: Final = "edit"
    VIEW: Final = "view"
    WINDOW: Final = "window"
    HELP: Final = "help"
    RUN: Final = "run"
    TERMINAL: Final = "terminal"
    SELECTION: Final = "selection"
    ZOOM: Final = "zoom"
    DRAW: Final = "draw"
    IMAGE: Final = "image"
    HISTORY: Final = "history"
    BOOKMARKS: Final = "bookmarks"
    GO: Final = "go"
    FORMAT: Final = "format"
    TOOLS: Final = "tools"

    ALL: Final = frozenset(
        {
            FILE,
            EDIT,
            VIEW,
            WINDOW,
            HELP,
            RUN,
            TERMINAL,
            SELECTION,
            ZOOM,
            DRAW,
            IMAGE,
            HISTORY,
            BOOKMARKS,
            GO,
            FORMAT,
            TOOLS,
        }
    )


class DevUiToken:
    SELECTION: Final = "selection"
    RUN: Final = "run"
    TERMINAL: Final = "terminal"
    UNKNOWN: Final = "unknown"

    ALL: Final = frozenset({SELECTION, RUN, TERMINAL, UNKNOWN})


class MonthToken:
    MON: Final = "mon"
    APR: Final = "apr"
    MAY: Final = "may"
    JUN: Final = "jun"


class DomainSuffix:
    YOUTUBE: Final = "youtube.com"
    GITHUB: Final = "github.com"
    LINEAR: Final = "linear.app"


class TitleScoreWeight:
    MULTI_WORD_BONUS: Final = 4.0
    KEYWORD_BONUS: Final = 6.0
    AMBIENT_PENALTY: Final = 16.0
    DIGIT_PENALTY: Final = 8.0
    SLACK_CHECK_IN_BONUS: Final = 12.0
    ZOOM_MEETING_BONUS: Final = 18.0
    CURSOR_DEV_UI_BONUS: Final = 18.0
    CURSOR_CHECK_IN_PENALTY: Final = 30.0
    CURSOR_APP_NAME_BONUS: Final = 25.0
    SAFARI_WORK_UI_BONUS: Final = 8.0
    MIN_TITLE_LENGTH: Final = 4
    SHORT_NON_BROWSER_TITLE_MAX: Final = 12


def norm_text(value: str) -> str:
    """Normalize text for loose heuristic matching."""
    return " ".join((value or "").strip().lower().split())


class AppSlug:
    CURSOR: Final = norm_text(App.CURSOR)
    SLACK: Final = norm_text(App.SLACK)
    ZOOM_WORKPLACE: Final = norm_text(App.ZOOM_WORKPLACE)
    SAFARI: Final = norm_text(App.SAFARI)
    DRAW_THINGS: Final = norm_text(App.DRAW_THINGS)
    CODE: Final = norm_text(App.CODE)
    TERMINAL: Final = norm_text(App.TERMINAL)
    GITHUB: Final = norm_text(App.GITHUB)


APP_WHERE_NAME_IS_VALID_TITLE: Final = frozenset(
    {AppSlug.CURSOR, AppSlug.SLACK, AppSlug.ZOOM_WORKPLACE}
)

BROWSER_APPS: Final = frozenset(
    {
        App.SAFARI,
        App.CHROME,
        App.CHROME_SHORT,
        App.ARC,
        App.FIREFOX,
        App.BROWSER,
    }
)

CODING_APPS: Final = frozenset(
    {
        App.CURSOR,
        App.CODE,
        App.VSCODE,
        App.XCODE,
        App.TERMINAL,
        App.ITERM,
        App.PYCHARM,
        App.WEBSTORM,
        App.GOLAND,
        App.DATAGRIP,
    }
)

MEETING_APPS: Final = frozenset(
    {App.ZOOM_WORKPLACE, App.ZOOM, App.CALENDAR, App.GOOGLE_MEET, App.TEAMS}
)

COMMS_APPS: Final = frozenset({App.SLACK, App.DISCORD, App.MAIL, App.SPARK})

NON_BROWSER_FRONTMOST_APPS: Final = frozenset(
    {App.DRAW_THINGS, App.FIGMA, App.PHOTOS, App.PREVIEW}
)

AMBIENT_OCR_FRAGMENTS: Final = (
    OcrSignal.CHECK_IN,
    OcrSignal.SINGLE_IMAGE,
    OcrSignal.MOVIES,
    MonthToken.MON,
    MonthToken.APR,
    MonthToken.MAY,
    MonthToken.JUN,
    OcrSignal.TODAY,
    OcrSignal.NOW,
)

MEETING_SIGNALS: Final = (
    OcrSignal.ZOOM,
    OcrSignal.MEETING,
    OcrSignal.PARTICIPANTS,
    OcrSignal.WORKPLACE,
)

WORK_TRACKING_SIGNALS: Final = (
    OcrSignal.WORKFLOW_RUNS,
    OcrSignal.ISSUES,
    OcrSignal.CAMPAIGNS,
    OcrSignal.EDIT_ADVERTISER,
    OcrSignal.LINEAR,
    OcrSignal.LINEAR_APP,
    OcrSignal.JIRA,
    OcrSignal.ASANA,
    OcrSignal.BACKLOG,
)

BROWSER_CONTENT_SIGNALS: Final = (
    OcrSignal.YOUTUBE,
    OcrSignal.GITHUB_COM,
    OcrSignal.WORKFLOW_RUNS,
    OcrSignal.LINEAR_APP,
    OcrSignal.ICLOUD,
    OcrSignal.SAFARI,
    OcrSignal.CHROME,
    OcrSignal.HTTP,
    OcrSignal.HTTPS,
    OcrSignal.WWW,
    OcrSignal.TABS,
)

TITLE_KEYWORD_BONUSES: Final = (
    OcrSignal.ISSUE,
    OcrSignal.WORKFLOW,
    OcrSignal.YOUTUBE,
    OcrSignal.CAMPAIGN,
    OcrSignal.LINEAR,
    OcrSignal.WORKPLACE,
    OcrSignal.MEETING,
    OcrSignal.CHECK_IN,
)

SAFARI_TITLE_KEYWORD_BONUSES: Final = (
    OcrSignal.WORKFLOW,
    OcrSignal.CAMPAIGN,
    OcrSignal.ISSUE,
    OcrSignal.ACCOUNTS,
)

WEAK_BROWSER_TITLES: Final = frozenset(
    {
        norm_text(App.CHROME),
        norm_text("chrome - google chrome"),
        norm_text(App.VSCODE),
    }
)

PLACEHOLDER_TITLES: Final = frozenset(
    {
        Placeholder.EMPTY,
        Placeholder.UNKNOWN.lower(),
        Placeholder.MAIN_WINDOW,
        Placeholder.MAIN_WINDOW_TITLE,
        Placeholder.WINDOW,
        Placeholder.WINDOW_TITLE,
    }
)

GENERIC_MEETING_TITLE_TOKENS: Final = frozenset(
    {OcrSignal.WORKPLACE, OcrSignal.MEETING}
)

GENERIC_TITLE_SKIP_TOKENS: Final = frozenset(
    {
        Placeholder.EMPTY,
        Placeholder.UNKNOWN.lower(),
        OcrSignal.MEETING,
        OcrSignal.WORKPLACE,
        AppSlug.CURSOR,
        AppSlug.SLACK,
        OcrSignal.ZOOM,
    }
)

CODING_TASK_KEYWORDS: Final = (
    OcrSignal.PYTEST,
    OcrSignal.PY_EXT,
    OcrSignal.TERMINAL,
    OcrSignal.GIT_PREFIX,
)

TERMINAL_TASK_KEYWORDS: Final = {
    Task.TEST: (OcrSignal.PYTEST, "coverage", "unittest", "rspec"),
    Task.BUILD: ("docker", "compose", "kubectl", "terraform", "ansible"),
    Task.CODING: (OcrSignal.GIT_PREFIX, "vim ", "nvim ", "code ", "gcc", "make ", "pip ", "uv "),
}

DEFAULT_TASK_BY_APP: Final = dict(
    {
        App.CURSOR: Task.CODING,
        App.CODE: Task.CODING,
        App.VSCODE: Task.CODING,
        App.XCODE: Task.CODING,
        App.TERMINAL: Task.CODING,
        App.ITERM: Task.CODING,
        App.PYCHARM: Task.CODING,
        App.WEBSTORM: Task.CODING,
        App.GOLAND: Task.CODING,
        App.DATAGRIP: Task.CODING,
        App.SAFARI: Task.RESEARCH,
        App.CHROME: Task.RESEARCH,
        App.ARC: Task.RESEARCH,
        App.FIREFOX: Task.RESEARCH,
        App.BROWSER: Task.RESEARCH,
        App.SLACK: Task.COMMS,
        App.DISCORD: Task.COMMS,
        App.MAIL: Task.COMMS,
        App.SPARK: Task.COMMS,
        App.OBSIDIAN: Task.NOTES,
        App.NOTES: Task.NOTES,
        App.FIGMA: Task.DESIGN,
        App.DRAW_THINGS: Task.DESIGN,
        App.ZOOM_WORKPLACE: Task.MEETING,
        App.CALENDAR: Task.MEETING,
    }
)


@dataclass(frozen=True)
class WorkTrackingTool:
    label: str
    patterns: tuple[str, ...]


WORK_TRACKING_TOOLS: Final = (
    WorkTrackingTool("Linear", (OcrSignal.LINEAR, OcrSignal.LINEAR_APP, OcrSignal.WORKFLOW_RUNS)),
    WorkTrackingTool("Jira", (OcrSignal.JIRA, OcrSignal.SPRINT_BOARD)),
    WorkTrackingTool("Asana", (OcrSignal.ASANA,)),
)


@dataclass(frozen=True)
class AppInferenceRule:
    app: str
    keywords: tuple[str, ...]
    slug: str


APP_INFERENCE_RULES: Final = (
    AppInferenceRule(App.DRAW_THINGS, ("drawthings", AppSlug.DRAW_THINGS, "edit image view window help", "version history", "local network"), AppSlug.DRAW_THINGS),
    AppInferenceRule(App.SAFARI, (OcrSignal.SAFARI, "file edit view history bookmarks"), norm_text(App.SAFARI)),
    AppInferenceRule(App.CHROME_SHORT, (OcrSignal.CHROME, OcrSignal.GOOGLE_CHROME), norm_text(App.CHROME)),
    AppInferenceRule(App.FIREFOX, ("firefox", "mozilla"), norm_text(App.FIREFOX)),
    AppInferenceRule(App.CURSOR, (AppSlug.CURSOR, "cursor editor"), AppSlug.CURSOR),
    AppInferenceRule(App.CODE, (norm_text(App.VSCODE), App.CODE.lower(), "vscode"), norm_text(App.CODE)),
    AppInferenceRule(App.ZOOM_WORKPLACE, (AppSlug.ZOOM_WORKPLACE, OcrSignal.ZOOM, OcrSignal.MEETING), AppSlug.ZOOM_WORKPLACE),
    AppInferenceRule(App.TERMINAL, (OcrSignal.TERMINAL, "iterm", "zsh", "bash"), norm_text(App.TERMINAL)),
    AppInferenceRule(App.SLACK, (AppSlug.SLACK,), AppSlug.SLACK),
    AppInferenceRule(App.DISCORD, ("discord",), norm_text(App.DISCORD)),
    AppInferenceRule(App.MAIL, ("mail", "apple mail"), norm_text(App.MAIL)),
    AppInferenceRule(App.NOTES, (norm_text(App.NOTES),), norm_text(App.NOTES)),
    AppInferenceRule(App.FIGMA, ("figma",), norm_text(App.FIGMA)),
    AppInferenceRule(App.OBSIDIAN, ("obsidian",), norm_text(App.OBSIDIAN)),
    AppInferenceRule(App.GITHUB, (OcrSignal.GITHUB_COM, "github", OcrSignal.REPOSITORY, "pull request", OcrSignal.ISSUE), norm_text(App.GITHUB)),
)

BROWSER_WORK_UI_SIGNALS: Final = (
    OcrSignal.LINEAR_APP,
    OcrSignal.WORKFLOW_RUNS,
    OcrSignal.ACCOUNTS,
    OcrSignal.CAMPAIGNS,
    OcrSignal.EDIT_ADVERTISER,
    OcrSignal.ISSUES,
)

SOURCE_CODE_EXTENSIONS: Final = (".py", ".js", ".ts", ".md")


class SummaryPhrase:
    @staticmethod
    def check_in_conversation(app: str) -> str:
        return f"{app} check-in conversation"

    @staticmethod
    def conversation(app: str) -> str:
        return f"{app} conversation"

    @staticmethod
    def meeting_in_app(app: str) -> str:
        return f"Meeting in {app}"

    @staticmethod
    def coding_in_app(app: str) -> str:
        return f"Coding in {app}"

    @staticmethod
    def browsing_in_app(app: str) -> str:
        return f"Browsing in {app}"

    @staticmethod
    def title_in_app(title: str, app: str) -> str:
        return f"{title} in {app}"

    @staticmethod
    def task_in_app(task: str, app: str) -> str:
        return f"{task} in {app}"

    @staticmethod
    def using_app(app: str) -> str:
        return f"Using {app}"

    @staticmethod
    def browsing_with_frontmost(browser: str, frontmost_app: str) -> str:
        return f"Browsing in {browser} with {frontmost_app} frontmost"

    @staticmethod
    def labeled_work_item(label: str, base: str) -> str:
        return f"{label} {base}".strip()
