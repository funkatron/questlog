# Cursor Rules for questlog

## Principles
- Make one change at a time; test before committing; commit each change separately.
- Clarity over brevity. Prefer explicit code and types when practical.
- No hyperbole in documentation. Reflect the current state accurately.
- Preserve privacy: avoid uploading screenshots or raw content to third‑party services unless explicitly enabled.

## Coding style
- Python 3.10+. Type annotate public functions and exported APIs.
- Early returns; shallow nesting; meaningful names.
- Add concise comments when intent might be unclear.
- Keep OCR/LLM/providers isolated under `ql/` modules; CLI (`questlog.py`) should be orchestration only.

## LLM policy
- Provider switch via config: default to local Ollama; OpenAI optional.
- Prefer OCR text to image where possible; send images only when a vision model is explicitly selected.
- Prompt sources live in `ql/text.py`. Keep one canonical prompt per task.

## Prompts
### Context Recovery Analyst (canonical)
You are a context recovery analyst. Analyze the attached screenshot and write a detailed account that helps the user restart later without judging their focus or output.

Return Markdown only (no preface, no extra commentary), using exactly these section headings:

## What was happening
- A clear description of the user’s primary task (what they were doing) in 2–4 sentences.

## Why (likely intent)
- Briefly explain the plausible goal(s) driving this task.

## Sub‑tasks and steps
- Bullet list of concrete actions or sub‑steps visible or strongly implied.

## Evidence (from the screenshot)
- 4–8 bullets citing specific on‑screen cues (UI labels, titles, text snippets, filenames, domains). Quote exact text where useful.

## Tools and context
- App(s) in focus and any notable services/sites.
- Any visible files, repos, docs, or environments.

## Related project(s)
- Short project/repo/doc names if strongly indicated; otherwise “Unknown”.

## Uncertainties
- List any ambiguities and what additional signals would resolve them.

## Likely next actions
- 3–5 concrete, low-friction actions the user could take to resume.

Rules:
- Be concrete and rely only on what’s visible.
- If unclear, state that explicitly under “Uncertainties.”
- Keep the narrative precise and useful for future restart notes.
- Avoid productivity scoring, moral language, or labels like distracted/unproductive.

## Testing
- Fixtures for screenshots live under `tests/fixtures/` (kept out of git LFS unless needed).
- Add tests that assert non‑empty summaries and reasonable activities for fixtures.

## Git workflow
- Keep `.gitignore` up to date; never commit local DB, exports, logs, or large binaries.
- PR/commit messages: imperative mood, concise scope, avoid marketing language.
