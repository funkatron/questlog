# Quest Log — TimeSnapper Edition (v2)

On‑device activity logging from periodic screenshots. Privacy‑first, macOS‑native OCR + heuristics,
with optional local LLM summaries (Ollama). This revision adds a **doctor** command, **project aliases**,
URL extraction, a simple rotating **logfile**, and **CSV export**.

## What’s new in v2
- `questlog.py doctor` — verifies config, binaries, permissions, and a quick OCR sanity check
- `project_aliases` in `config.yaml` to strengthen project detection (repo names, Jira keys, domains)
- Extracts URLs from OCR text for better “Research” labeling and project mapping
- Rotating `questlog.log` for easier QA / debugging
- `export-csv` command in addition to Markdown export

## Requirements
- macOS with Xcode Command Line Tools (`xcode-select --install`)
- Terminal/iTerm must be allowed under **System Settings → Privacy & Security → Accessibility**
- Python 3.10+ (uv optional)
- TimeSnapper screenshots under day folders named `YYYY-MM-DD`

## Quick start
```bash
# 1) Build Swift helpers
make build

# 2) Python env (uv preferred)
uv venv .venv && source .venv/bin/activate
uv pip install -r requirements.txt
# or: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# 3) Initialize and sanity check
python questlog.py init-db
python questlog.py doctor

# 4) Backfill a couple days, then export
python questlog.py backfill --days 2
python questlog.py export-md --date $(date +%F)
python questlog.py export-csv --date $(date +%F)
```

## Optional: local LLM summaries via Ollama
```bash
ollama pull qwen2.5:7b-instruct
# config.yaml → set ollama.enabled: true
python questlog.py backfill --days 1
```

## Notes
- Default `base_folder` is set to your TimeSnapper path; change it if QA uses a sample directory.
- Add sensitive apps to `blocklist_apps` to skip entries entirely.
- Redaction runs before storage (emails and long digit sequences). Add your own patterns as needed.

---
MIT‑licensed starter.
