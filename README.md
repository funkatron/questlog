# Questlog (in progress)

Questlog records on-device activity from periodic screenshots and produces a daily timeline. It can use OCR and a local LLM to infer what you were doing at each point in time.

This is a work in progress. APIs, prompts, and outputs may change.

## Features
- Screenshot capture (built-in) or folder watch
- OCR: Swift Vision binary if available, otherwise Python Tesseract fallback
- Optional LLM labeling via Ollama (local) or, optionally, a cloud provider
- Exports: Markdown timeline and CSV
- Doctor command to verify setup

## Requirements
- macOS
  - Screen Recording and Accessibility permissions for your terminal/app
  - Xcode Command Line Tools for building Swift helpers (optional)
- Python 3.10+
- Optional: Ollama for local LLMs

## Setup
```bash
make build                      # build Swift helpers (optional)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python questlog.py init-db
python questlog.py doctor
```

## Configuration
Edit `config.yaml`:
- `base_folder`: screenshot folder (used by backfill/watch; built-in capture writes here)
- `projects`, `project_aliases`: help resolve project names
- `ollama`: model settings; set `enabled: true` to use a local LLM
- `max_ocr_lines`: how much OCR text to include in prompts

## Usage
```bash
# capture a single snapshot and index it
questlog snap

# continuous capture every N seconds
questlog capture --interval 60

# analyze a single image (no DB write) — helpful for testing
questlog analyze-file /path/to/screenshot.png

# watch an existing folder for new screenshots
questlog watch

# export a given day
questlog export-md --date $(date +%F)
questlog export-csv --date $(date +%F)
```

## LLM notes
- The tool builds a concise prompt from app/window title, OCR text, and simple clues.
- By default it uses the configured Ollama endpoint with `/api/generate`.
- If you enable `send_image` and use a vision model, the screenshot path is sent.

## Status and roadmap (short)
- Current focus: better activity inference and prompt consistency
- Near-term: optional cloud LLM provider switch; improved exports (activity-first)

## License
MIT
