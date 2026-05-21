"""Read-only local state probes for richer restart notes."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable, Protocol


class StateProbe(Protocol):
    """Read-only probe that enriches restart notes from local filesystem state."""

    name: str

    def probe(
        self,
        artifacts: list[str],
        clues: dict[str, Any] | None,
        *,
        allowed_roots: list[Path],
        max_items: int,
        timeout_seconds: float,
    ) -> list[dict[str, Any]]:
        """Return zero or more probe result records."""


ProbeFn = Callable[
    [list[str], dict[str, Any] | None, list[Path], int, float],
    list[dict[str, Any]],
]

_PROBE_REGISTRY: dict[str, ProbeFn] = {}


def register_probe(name: str, probe_fn: ProbeFn) -> None:
    """Register a named state probe implementation."""
    _PROBE_REGISTRY[name] = probe_fn


def registered_probe_names() -> list[str]:
    """Return registered probe names in registration order."""
    return list(_PROBE_REGISTRY.keys())


def default_allowed_roots() -> list[Path]:
    """Return default filesystem roots that probes may inspect."""
    return [Path.cwd().resolve(), Path.home().resolve()]


def resolve_allowed_roots(extra_roots: list[str] | None = None) -> list[Path]:
    """Build the allowed-root list from defaults plus optional config paths."""
    roots = default_allowed_roots()
    for raw in extra_roots or []:
        value = (raw or "").strip()
        if not value:
            continue
        path = Path(value).expanduser().resolve()
        if path not in roots:
            roots.append(path)
    return roots


def is_path_allowed(path: Path, allowed_roots: list[Path]) -> bool:
    """Return whether a resolved path stays within allowed roots."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in allowed_roots:
        try:
            if resolved.is_relative_to(root):
                return True
        except AttributeError:
            # Python <3.9 fallback (project requires 3.10+, kept for clarity)
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
    return False


def find_git_root(start: Path, *, max_depth: int = 8) -> Path | None:
    """Walk upward from start and return the nearest directory containing .git."""
    current = start
    if current.is_file():
        current = current.parent
    for _ in range(max_depth):
        if (current / ".git").exists():
            return current.resolve()
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def collect_probe_candidates(
    artifacts: list[str],
    clues: dict[str, Any] | None,
) -> list[Path]:
    """Collect filesystem paths worth probing from stored artifacts and clues."""
    candidates: list[Path] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        value = (raw or "").strip()
        if not value or value in seen:
            return
        seen.add(value)
        path = Path(value).expanduser()
        if path.suffix:
            candidates.append(path)
        else:
            candidates.append(path)

    for artifact in artifacts or []:
        _add(str(artifact))

    clues = clues or {}
    for token in clues.get("tokens", []) + clues.get("repo_tokens", []):
        token = str(token).strip()
        if "/" in token or token.endswith((".py", ".md", ".yaml", ".yml", ".json", ".ts", ".tsx")):
            _add(token)

    return candidates


def _run_git(args: list[str], *, cwd: Path, timeout: float) -> tuple[str, str | None]:
    """Run a fixed git subcommand and return stdout or an error string."""
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "", str(exc)

    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "").strip()
        return "", err or f"git {' '.join(args)} failed with code {completed.returncode}"
    return completed.stdout.strip(), None


def _read_branch_head(repo_root: Path) -> tuple[str | None, str | None]:
    head_path = repo_root / ".git" / "HEAD"
    try:
        head = head_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return None, str(exc)

    if head.startswith("ref: "):
        ref = head.removeprefix("ref: ").strip()
        branch = ref.rsplit("/", 1)[-1]
        return branch or ref, None
    if head:
        return f"detached@{head[:7]}", None
    return None, "empty HEAD"


def probe_git_repository(
    repo_root: Path,
    *,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Inspect a git repository read-only and return observed local state."""
    branch, branch_error = _read_branch_head(repo_root)
    status_out, status_error = _run_git(
        ["status", "--short", "--branch"],
        cwd=repo_root,
        timeout=timeout,
    )

    status_lines = [line for line in status_out.splitlines() if line and not line.startswith("##")]
    dirty = bool(status_lines)
    diff_stat = ""
    diff_error = None
    if dirty:
        diff_stat, diff_error = _run_git(["diff", "--stat"], cwd=repo_root, timeout=timeout)

    notes: list[str] = []
    confidence = "observed"
    if branch_error:
        notes.append(f"branch unavailable: {branch_error}")
        confidence = "partial"
    if status_error:
        notes.append(f"status unavailable: {status_error}")
        confidence = "partial"
    if diff_error:
        notes.append(f"diff unavailable: {diff_error}")
        confidence = "partial"

    status_summary = "; ".join(status_lines[:3])
    if len(status_lines) > 3:
        status_summary = f"{status_summary}; +{len(status_lines) - 3} more"

    return {
        "repo": str(repo_root),
        "branch": branch,
        "clean": not dirty,
        "status_summary": status_summary or "clean working tree",
        "diff_stat": diff_stat,
        "confidence": confidence,
        "notes": notes,
    }


def gather_state_probes(
    artifacts: list[str],
    clues: dict[str, Any] | None,
    *,
    enabled: bool,
    allowed_roots: list[Path] | None = None,
    max_repos: int = 2,
    timeout_seconds: float = 5.0,
    probe_names: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Gather read-only local state for restart-note enrichment."""
    if not enabled:
        return []

    roots = allowed_roots or default_allowed_roots()
    names = probe_names or registered_probe_names()
    probes: list[dict[str, Any]] = []
    for name in names:
        probe_fn = _PROBE_REGISTRY.get(name)
        if probe_fn is None:
            continue
        probes.extend(
            probe_fn(
                artifacts,
                clues,
                roots,
                max_repos,
                timeout_seconds,
            )
        )
    return probes


def _gather_git_probes(
    artifacts: list[str],
    clues: dict[str, Any] | None,
    allowed_roots: list[Path],
    max_repos: int,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    """Git probe adapter for the probe registry."""
    repo_roots: list[Path] = []
    seen_repos: set[str] = set()

    for candidate in collect_probe_candidates(artifacts, clues):
        if not is_path_allowed(candidate, allowed_roots):
            continue
        git_root = find_git_root(candidate)
        if git_root is None:
            continue
        key = str(git_root)
        if key in seen_repos:
            continue
        seen_repos.add(key)
        repo_roots.append(git_root)
        if len(repo_roots) >= max_repos:
            break

    probes: list[dict[str, Any]] = []
    for repo_root in repo_roots:
        result = probe_git_repository(repo_root, timeout=timeout_seconds)
        result["probe"] = "git"
        probes.append(result)
    return probes


register_probe("git", _gather_git_probes)


def format_probe_summary(probe: dict[str, Any]) -> str:
    """Render one probe result as a single concise line."""
    branch = probe.get("branch") or "unknown branch"
    status = probe.get("status_summary") or "status unavailable"
    repo = probe.get("repo") or "unknown repo"
    confidence = probe.get("confidence") or "partial"
    line = f"{repo} on {branch}: {status} ({confidence})"
    diff_stat = (probe.get("diff_stat") or "").strip()
    if diff_stat:
        first_line = diff_stat.splitlines()[0]
        line = f"{line}; diff {first_line}"
    return line
