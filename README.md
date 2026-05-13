# Questlog

Questlog is a local-first restart tool. It analyzes recent screenshots so you can recover what you were doing after an interruption and get a short, neutral next-step note.

It uses OCR to extract text from screenshots and optional LLM assistance to generate summaries. The first useful workflow is re-entry:

```bash
questlog resume
```

`resume` reads recent local database entries and prints a concise restart note with the last thread, possible open loops, context switches, and a suggested restart point. It does not require Ollama or OpenAI.

## Privacy model

- Questlog captures screenshots only when you run capture/watch/backfill commands.
- Questlog stores metadata, OCR-derived text, summaries, confidence, and screenshot file paths in local SQLite.
- User-facing restart notes apply extra redaction for emails, phone numbers, long card-like numbers, secret assignments, and URL query strings.
- Data stays local unless you explicitly enable an LLM provider that sends prompts or images outside the process.
- Use `blocklist_apps` in `config.yaml` for sensitive apps such as password managers or private messaging tools.

## What it does

1. **Captures screenshots** at intervals or watches a folder for new screenshots
2. **Analyzes images** using vision-first approach with LLM vision models for holistic scene understanding
3. **Extracts text** from screenshots using EasyOCR (primary), LLM OCR, or Tesseract fallback
4. **Identifies context** like visible apps, window titles, layout, activities, and projects
5. **Generates summaries** using local LLM (Ollama) or cloud API (OpenAI) if enabled
6. **Stores entries** in a SQLite database with timestamps, app names, tasks, and summaries
7. **Builds restart notes** for recent activity and exports logs as Markdown or CSV for review

## Quickstart

### Prerequisites

- Python 3.10 or later
- macOS (for screenshot capture; other features work on Linux)
- [uv](https://github.com/astral-sh/uv) package manager (recommended) or pip
- Optional: [Ollama](https://ollama.ai/) for local LLM processing

### Installation

1. Clone or download this repository
2. Run the install helper:

```bash
make install
```

This will automatically:
- Detect if `uv` is available and use it (recommended), otherwise fall back to `pip`
- Install all dependencies including OCR and dev tools
- Initialize the database
- Create `config.yaml` from `config.example.yaml` if it doesn't exist

**Alternative manual installation:**

If you prefer to install manually or don't have `make`:

```bash
# Using uv (recommended)
uv sync --all-extras
uv run questlog init-db

# Or using pip
pip install -e ".[all]"
python -m questlog init-db
```

**Note:** EasyOCR is recommended for best OCR quality. It uses deep learning models and provides much better text extraction than Tesseract. The model is cached after first load for performance.

3. Configure:

Edit `config.yaml` to set your screenshot folder, projects, and optional LLM settings (see Configuration below). The config file is automatically created from `config.example.yaml` during `init-db` if it doesn't exist.

### First capture

Test the setup:

```bash
# Check your configuration
questlog doctor

# Capture and analyze one screenshot
questlog snap

# View the analysis without saving
questlog analyze-now

# Recover recent context after an interruption
questlog resume
```

## Configuration

Copy `config.example.yaml` to `config.yaml` and edit as needed:

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

# Matching below this score is treated as Unknown instead of guessed
project_match_threshold: 0.70

# Ollama configuration (optional)
ollama:
  enabled: true
  endpoint: "http://localhost:11434/api/generate"

  ocr:
    model: "llava:7b"  # Vision model for text extraction (used if LLM OCR enabled)

  summarization:
    model: "tinydolphin:latest"  # Text model for summaries

  # Vision Analysis - for holistic scene understanding (primary analysis method)
  vision_analysis:
    model: "llava:7b"  # Vision model for scene understanding
    enabled: true  # Enable vision-first analysis

# OpenAI configuration (optional, alternative to Ollama)
openai:
  enabled: false
  model: "gpt-4o-mini"
  api_key_env: "OPENAI_API_KEY"
```

## Usage

### Resume recent work

**Restart note for the last 4 hours:**
```bash
questlog resume
```

**Use a different window or structured output:**
```bash
questlog resume --hours 8
questlog resume --json
```

The resume command is heuristic and local. It reads existing database entries and does not require an LLM.

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
# Disable vision completely for maximum throughput:
questlog backfill --today --vision-mode never
# Or force vision on every image:
questlog backfill --today --vision-mode always
```

Backfill defaults to `--vision-mode auto`: OCR first, then vision only for low-confidence
entries. Use `--vision-mode never` for maximum throughput, or `--vision-mode always`
when you want the richest model-generated summaries and can tolerate the extra latency.

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
2. **Vision analysis** (primary): Uses LLM vision model (llava:7b) to understand the entire screenshot scene - identifying apps, window titles, layout, activities, and projects
3. **OCR extraction** (supplemental): Extracts visible text using EasyOCR (primary), LLM OCR, or Tesseract fallback
4. **App detection**: AppleScript to identify frontmost app, or inferred from vision analysis for historical screenshots
5. **Context extraction**: Identifies URLs, domains, and project hints from vision analysis and OCR text
6. **Project matching**: Fuzzy matches window titles and OCR content against your project list
7. **Summarization**: If LLM is enabled, generates a concise summary and task classification (uses vision analysis if available)
8. **Storage**: Saves entry with timestamp, app, task type, summary, and confidence score

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
- `questlog/cli/app.py` - Main CLI application
- `questlog/cli/commands/` - Individual command modules (capture, analyze, export, benchmark, etc.)
- `questlog/services/` - Service layer (DatabaseService, ImageService, ExportService)
- `questlog/config.py` - Configuration management with Pydantic
- `ql/processing.py` - Core image processing and summarization
- `ql/system.py` - System integration (app detection, OCR, vision analysis)
- `ql/text.py` - Text processing and prompt building
- `ql/db.py` - Database operations

## Benchmark Tool

Use the benchmark tool to visualize what QuestLog extracts from screenshots:

```bash
# Analyze a single image
questlog benchmark path/to/image.jpg

# Process a directory of images
questlog benchmark --directory /path/to/images
```

This generates markdown reports showing the screenshot alongside vision analysis results, OCR extraction, app detection, and final summary.

## License

MIT
