# Questlog — Current Status

Last updated: 2025-11-24

## Summary
- Vision-first analysis using LLM vision models (llava:7b) for holistic scene understanding
- High-quality OCR with EasyOCR (deep learning) as primary method, with LLM OCR and Tesseract fallbacks
- Working CLI for capture/watch, analysis, and exports (Markdown/CSV with session grouping)
- LLM-assisted labeling (Ollama/OpenAI) with improved prompts and model selection

## What works
- Capture (manual, timed, and folder watch)
- Vision-first analysis using llava:7b for scene understanding (apps, windows, layout, activities)
- OCR with EasyOCR (primary, high quality), LLM OCR, or Tesseract fallback chain
- EasyOCR model caching (loads once, reuses across images)
- LLM summarization with intelligent model selection and fallbacks
- Window title detection from vision analysis or OCR fallback
- Project resolution with fuzzy matching and aliases
- Exports for selected dates (md/csv) with session grouping
- Benchmark tool for visualizing analysis results
- Diagnostic logging for quality issues
- Tests: core utilities, LLM mock, Ollama integration (7 tests passing)

## Recent improvements
- **Vision-first analysis**: Implemented holistic scene understanding using llava:7b vision model
- **EasyOCR integration**: Added EasyOCR as primary OCR method with model caching for better performance
- **Improved OCR quality**: EasyOCR provides much better text extraction (40+ readable lines vs garbled Tesseract output)
- **Enhanced processing flow**: Vision analysis → OCR extraction → Merge → Project resolution → Summarization
- **Benchmark tool**: Added tool to visualize vision analysis, OCR, and final results side-by-side
- **Better OCR fallback chain**: EasyOCR → LLM OCR → Tesseract (with improved PSM modes)
- **Enhanced LLM prompts**: Better prompts for vision analysis and summarization
- **Improved error handling**: Better fallbacks and diagnostic logging

## Known limitations
- Project resolution can be improved with better fuzzy matching
- EasyOCR is slower than Tesseract (~9-10s per image vs ~1s) but much higher quality
- Vision analysis adds ~20-25s per image (llava:7b processing time)
- LLM output quality varies by model (smaller models less consistent)
- EasyOCR requires significant disk space for model files (~500MB)

## Future enhancements
- Fine-tune project resolution matching
- Add activity field to entries and exports
- Improve export formatting with activity summaries
- Optimize vision analysis performance (faster models or GPU acceleration)
- Extract text directly from vision analysis responses when available
- Improve dual-pane/multi-app scenario detection
