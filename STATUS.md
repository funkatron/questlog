# Questlog — Current Status

Last updated: 2025-11-19

## Summary
- Working CLI for capture/watch, OCR (Swift/Python/LLM), LLM-assisted labeling (Ollama/OpenAI)
- Exports: Markdown and CSV with session grouping
- Improved prompts and model selection for better output quality

## What works
- Capture (manual, timed, and folder watch)
- OCR via Swift helper, Python Tesseract, or LLM vision model with fallback chain
- LLM summarization with intelligent model selection and fallbacks
- Window title fallback from OCR when unavailable
- Project resolution with fuzzy matching and aliases
- Exports for selected dates (md/csv) with session grouping
- Diagnostic logging for quality issues
- Tests: core utilities, LLM mock, Ollama integration (7 tests passing)

## Recent improvements
- Consolidated duplicate code into `ql/processing.py`
- Enhanced LLM prompts with better examples and structure
- Improved window title detection with OCR fallback
- Better error handling and diagnostic logging
- Standardized LLM integration with model selection

## Known limitations
- Project resolution can be improved with better fuzzy matching
- OCR quality depends on Swift binary or Tesseract installation
- LLM output quality varies by model (smaller models less consistent)

## Future enhancements
- Fine-tune project resolution matching
- Add activity field to entries and exports
- Improve export formatting with activity summaries
