# Questlog — Current Status (WIP)

Last updated: 2025-09-12T19:21:10-04:00

## Summary
- Prototype CLI for capture/watch, OCR (Swift/Python), optional LLM labeling (Ollama)
- Exports: Markdown and CSV
- Activity historian prompt drafted and tested against local models

## What works
- Capture (manual and timed), folder watch
- OCR via Swift helper or Python Tesseract fallback
- Analyze single image (`analyze-file`) with OCR and LLM call
- Exports for a selected date (md/csv)
- Tests: core utilities, LLM mock, Ollama integration (skippable)

## What needs improvement
- LLM quality: local tiny models produce weak labels; larger local or cloud provider recommended
- Vision model support: download and wire (e.g., llava:7b) when bandwidth allows
- Provider switch: optional OpenAI with budget caps
- Export formatting: surface "Activity — Summary" when available

## Next steps
- At home: pull llava:7b or switch to OpenAI (gpt-4o-mini)
- Add `what` command to summarize a recent window into Markdown using the historian prompt
- Store `activity` per entry and prefer it in exports
- Tighten prompts with a few concise examples

## Risks / unknowns
- Ollama API shape differences across versions (chat vs generate)
- OCR noise affecting prompts; may need more filtering/deduping
- Performance impact at high capture cadence
