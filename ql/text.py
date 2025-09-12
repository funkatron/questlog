import os
import re
from typing import List, Dict, Any


RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
RE_LONGNUM = re.compile(r"(?<!\d)(\d{4}[\s-]?){3}\d{4}(?!\d)")
RE_URL = re.compile(r"https?://[^\s)>\]]+", re.IGNORECASE)


def redact(text: str) -> str:
    text = RE_EMAIL.sub("[redacted-email]", text)
    text = RE_LONGNUM.sub("[redacted-num]", text)
    return text


def find_artifacts(window_title: str, ocr_lines: List[str]) -> List[str]:
    text = " ".join([window_title] + ocr_lines)
    cands = re.findall(r"[\w\-\_/]+\.[A-Za-z0-9]{1,6}", text)
    uniq = []
    for c in cands:
        if c not in uniq:
            uniq.append(c)
    return uniq[:5]


def extract_clues(app: str, window_title: str, lines: List[str]) -> Dict[str, Any]:
    joined = "\n".join(lines)
    urls = RE_URL.findall(joined)
    domain_tokens = []
    for u in urls:
        try:
            d = re.sub(r"^https?://", "", u).split("/")[0]
            if d:
                domain_tokens.append(d.lower())
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


def build_ollama_prompt(cfg, app, window_title, ocr_top, projects, clues):
    ocr_block = os.linesep.join(ocr_top[: cfg.get("max_ocr_lines", 12)])
    taxonomy = (
        "Coding, Research, Comms, Build, Test, Design, Meeting, Admin, Idle, Unknown"
    )
    prompt = f"""
You are labeling a short work snapshot.

Goal:
- Infer what the user is doing now as a short action phrase (activity), plus a concise summary.

Guidelines:
- Be concise; write an action-style summary (≤ 16 words).
- If unsure, use the window title as the summary.
- Choose coarse_task from exactly: {taxonomy}.
- Use only the information below; do not invent details.

Context:
- App: {app}
- Window: {window_title}
- OCR (top lines):
{ocr_block}
- Clues: {clues}
- Known Projects: {projects}

Few-shot examples:
Example A → JSON
  Input: App=Terminal, Window="pytest -q", OCR contains "pytest passed"
  Output: {{"activity":"Running tests","summary":"Running unit tests in terminal","coarse_task":"Test","confidence":0.86}}

Example B → JSON
  Input: App=Chrome, Window="RFC draft - Google Docs", OCR shows doc body text
  Output: {{"activity":"Writing spec","summary":"Editing RFC draft in Google Docs","coarse_task":"Research","confidence":0.78}}

Output (choose one):
1) JSON object with keys:
   - activity: string (verb+noun, ≤ 4 words)
   - summary: string (≤ 16 words)
   - coarse_task: one of {taxonomy}
   - confidence: number 0..1

OR

2) Two lines:
   Activity: <short phrase>
   Summary: <≤ 16 words>
""".strip()
    return prompt

