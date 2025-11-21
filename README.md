# Questlog

Questlog logs your computer activity by analyzing periodic screenshots. It uses OCR to extract text from screenshots and optional LLM assistance to generate summaries of what you were doing.

## What it does

1. **Captures screenshots** at intervals or watches a folder for new screenshots
2. **Extracts text** from screenshots using OCR (Swift helper or Python Tesseract fallback)
3. **Identifies context** like the active app, window title, and visible text
4. **Generates summaries** using local LLM (Ollama) or cloud API (OpenAI) if enabled
5. **Stores entries** in a SQLite database with timestamps, app names, tasks, and summaries
6. **Exports logs** as Markdown or CSV for review

## Quickstart

### Prerequisites

- Python 3.10 or later
- macOS (for screenshot capture; other features work on Linux)
- [uv](https://github.com/astral-sh/uv) package manager (recommended) or pip
- Optional: [Ollama](https://ollama.ai/) for local LLM processing

### Installation

1. Clone or download this repository
2. Install dependencies:

```bash
# Using uv (recommended)
uv sync                    # Core dependencies
uv sync --extra ocr        # Include OCR fallback (Pillow, pytesseract)
uv sync --extra dev        # Include dev tools (pytest, etc.)
uv sync --all-extras       # Everything

# Or using pip
pip install -e .           # Core dependencies only
pip install -e ".[ocr]"    # With OCR fallback
pip install -e ".[dev]"    # With dev tools
pip install -e ".[all]"    # Everything
```

3. Build Swift helpers (macOS only):

```bash
make build
```

This creates `bin/frontapp` and `bin/ocrshot` for better app detection and OCR on macOS.

4. Initialize the database:

```bash
uv run questlog init-db
# or: python -m questlog init-db
```

5. Create a `config.yaml` file (see Configuration below)

### First capture

Test the setup:

```bash
# Check your configuration
uv run questlog doctor

# Capture and analyze one screenshot
uv run questlog snap

# View the analysis without saving
uv run questlog analyze-now
```

## Configuration

Create a `config.yaml` file in the project directory:

```yaml
# Folder where screenshots are stored (or watched)
base_folder: "~/Screenshots"

# Your projects (for automatic classification)
projects:
  - "Project A"
  - "Project B"

# Aliases help match projects from window titles/URLs
project_aliases:
  "Project A": ["project-a", "pa", "repo-name"]
  "Project B": ["project-b", "pb"]

# Apps to skip (privacy-sensitive)
blocklist_apps:
  - "1Password"
  - "Messages"

# Ollama configuration (optional)
ollama:
  enabled: true
  endpoint: "http://localhost:11434/api/generate"

  ocr:
    model: "moondream:latest"  # Vision model for text extraction

  summarization:
    model: "tinydolphin:latest"  # Text model for summaries

# OpenAI configuration (optional, alternative to Ollama)
openai:
  enabled: false
  model: "gpt-4o-mini"
  api_key_env: "OPENAI_API_KEY"
```

## Usage

### Capture modes

**Single capture:**
```bash
questlog snap
```

**Continuous capture (every 60 seconds):**
```bash
questlog capture --interval 60
```

**Watch a folder:**
```bash
questlog watch
```
Processes new screenshots as they appear in the configured folder.

**Backfill existing screenshots:**
```bash
questlog backfill
# Or only recent days:
questlog backfill --days 7
```

### Analysis commands

**Analyze current screen (no database write):**
```bash
questlog analyze-now
```

**Analyze a specific image:**
```bash
questlog analyze-file path/to/screenshot.png
```

**Generate detailed activity report:**
```bash
questlog what-image path/to/screenshot.png
```

### Export

**Markdown timeline:**
```bash
questlog export-md --date 2025-01-15
```

**CSV export:**
```bash
questlog export-csv --date 2025-01-15
```

Exports are written to the `exports/` directory.

## How it works

1. **Screenshot capture**: Uses macOS `screencapture` or watches a folder
2. **App detection**: Swift helper or AppleScript fallback to identify the frontmost app and window title
3. **OCR**: Extracts visible text using Swift Vision framework, Python Tesseract, or LLM vision model
4. **Context extraction**: Identifies URLs, domains, and project hints from window titles and OCR text
5. **Project matching**: Fuzzy matches window titles and OCR content against your project list
6. **Summarization**: If LLM is enabled, generates a concise summary and task classification
7. **Storage**: Saves entry with timestamp, app, task type, summary, and confidence score

## Output quality

- **Without LLM**: Uses window titles and app names. Task classification is basic.
- **With LLM**: Generates more descriptive summaries and better task classification. Quality depends on the model used.

Small local models (like `tinydolphin`) are fast but may produce inconsistent results. Larger models or cloud APIs provide better quality.

## Troubleshooting

Run the diagnostic command to check your setup:

```bash
questlog doctor
```

This verifies configuration, binary availability, permissions, and basic functionality. Check `questlog.log` for detailed error messages.

## Development

Run tests:
```bash
uv run pytest
```

Project structure:
- `questlog.py` - CLI entry point and commands
- `ql/processing.py` - Core image processing and summarization
- `ql/system.py` - System integration (app detection, OCR)
- `ql/text.py` - Text processing and prompt building
- `ql/db.py` - Database operations

## License

MIT
