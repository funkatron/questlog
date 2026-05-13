#!/usr/bin/env python3
"""Debug script to show step-by-step image processing."""

import json
import sys
from pathlib import Path

from ql import processing as qlp
from ql import system as qls
from ql.text import extract_clues, find_artifacts, redact
from questlog.config import load_config
from questlog.services import DatabaseService, ImageService

def main():
    if len(sys.argv) < 2:
        print("Usage: python debug_process.py <image_path>")
        sys.exit(1)

    image_path = Path(sys.argv[1])
    if not image_path.exists():
        print(f"Image not found: {image_path}")
        sys.exit(1)

    cfg = load_config()
    db_service = DatabaseService()
    image_service = ImageService(cfg)

    print("=" * 80)
    print("STEP-BY-STEP IMAGE PROCESSING")
    print("=" * 80)
    print()

    # Step 1: File info
    print("STEP 1: File Information")
    print("-" * 80)
    mtime = image_path.stat().st_mtime
    import datetime as dt
    timestamp = dt.datetime.fromtimestamp(mtime).astimezone().isoformat(timespec="seconds")
    print(f"Path: {image_path}")
    print(f"Size: {image_path.stat().st_size:,} bytes")
    print(f"Modified: {timestamp}")
    print(f"mtime: {mtime}")
    print()

    # Step 2: OCR extraction (needed before app inference)
    print("STEP 2: OCR Extraction")
    print("-" * 80)
    max_ocr_lines = cfg.max_ocr_lines
    print(f"Max OCR lines: {max_ocr_lines}")
    print("Trying LLM OCR first...")
    ocr_top_raw = qls.ocr_with_llm(cfg.to_dict(), image_path, max_ocr_lines)
    print(f"LLM OCR extracted {len(ocr_top_raw)} lines")
    if ocr_top_raw:
        print("LLM OCR lines:")
        for i, line in enumerate(ocr_top_raw[:5], 1):
            print(f"  {i}. {line}")
    else:
        print("LLM OCR failed, trying Tesseract...")
        ocr_top_raw = qls.ocr_lines(image_path, max_ocr_lines)
        print(f"Tesseract OCR extracted {len(ocr_top_raw)} lines")
        if ocr_top_raw:
            print("Tesseract OCR lines:")
            for i, line in enumerate(ocr_top_raw[:5], 1):
                print(f"  {i}. {line}")
    print()

    # Step 3: Text redaction
    print("STEP 3: Text Redaction")
    print("-" * 80)
    redacted = [redact(line) for line in ocr_top_raw]
    print(f"Redacted {len(redacted)} lines")
    if redacted:
        print("First 3 redacted lines:")
        for i, line in enumerate(redacted[:3], 1):
            print(f"  {i}. {line}")
    print()

    # Step 4: App inference (skipping detection for historical screenshots)
    print("STEP 4: App Inference")
    print("-" * 80)
    print("⚠️  SKIPPING app detection (front_app_info) for historical screenshots.")
    print("   Inferring app from OCR content and window title instead.")
    print()
    window_title = "Unknown"
    if redacted:
        for line in redacted:
            line_stripped = line.strip()
            if line_stripped and len(line_stripped) > 3:
                window_title = line_stripped[:80]
                break
    app = qlp.infer_app_from_content(window_title, redacted)
    print(f"Inferred App: {app}")
    print(f"Inferred Window Title: {window_title}")
    print()
    # Step 5: Clue extraction
    print("STEP 5: Clue Extraction")
    print("-" * 80)
    clues = extract_clues(app, window_title, redacted)
    print(f"Clues: {json.dumps(clues, indent=2)}")
    print()

    # Step 6: Project resolution
    print("STEP 6: Project Resolution")
    print("-" * 80)
    proj_guess = qlp.resolve_project(
        cfg.projects,
        cfg.project_aliases,
        window_title,
        redacted,
        clues,
        cfg.project_match_threshold,
    )
    print(f"Project: {proj_guess[0]}")
    print(f"Confidence: {proj_guess[1]:.2f}")
    print()

    # Step 7: Summarization
    print("STEP 7: Summarization")
    print("-" * 80)
    summary, coarse_task, confidence = qlp.summarize(
        cfg.to_dict(), app, window_title, redacted, proj_guess, clues
    )
    print(f"Summary: {summary}")
    print(f"Task: {coarse_task}")
    print(f"Confidence: {confidence:.2f}")
    print()

    # Step 8: Artifact extraction
    print("STEP 8: Artifact Extraction")
    print("-" * 80)
    artifacts = find_artifacts(window_title, redacted)
    print(f"Artifacts: {artifacts}")
    print()

    # Step 9: Final entry
    print("STEP 9: Final Entry")
    print("-" * 80)
    entry = {
        "ts": timestamp,
        "app": app,
        "window_title": window_title,
        "project": proj_guess[0],
        "coarse_task": coarse_task,
        "summary": summary,
        "artifacts": artifacts,
        "tags": [],
        "confidence": confidence,
        "clues": clues,
    }
    print(json.dumps(entry, indent=2, ensure_ascii=False))
    print()

    # Step 10: Evidence text
    print("STEP 10: Evidence Text (for FTS)")
    print("-" * 80)
    evidence_text = "\n".join([window_title] + redacted + clues.get("urls", []))
    print(f"Evidence text ({len(evidence_text)} chars):")
    print(evidence_text[:200] + "..." if len(evidence_text) > 200 else evidence_text)
    print()

if __name__ == "__main__":
    main()
