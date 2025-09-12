# Questlog (work in progress)

Questlog explores on-device activity logging from periodic screenshots, with OCR and LLM-assisted labeling to summarize “what I was doing.” This repository is under active development and not ready for general use.

## Current status
- Prototype CLI with capture/watch, OCR (Swift or Python fallback), and optional local LLM calls
- Basic exports (Markdown, CSV)
- Prompting and model selection are in flux; results are inconsistent

## Near-term goals
- Improve “what was I doing?” quality (prompting and provider compatibility)
- Stabilize the CLI surface and outputs
- Publish minimal, accurate setup docs once quality is acceptable

## Contributing / issues
Feedback is welcome. Please file issues with clear repro details and environment notes. Expect breaking changes while this is in progress.

## License
MIT
