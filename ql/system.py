"""System integration utilities for Questlog.

This module handles macOS-specific operations like app detection and OCR,
with fallbacks for when native helpers are unavailable.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import List, Dict, Any

try:
    from PIL import Image
    import pytesseract
except ImportError:
    Image = None
    pytesseract = None

# EasyOCR with caching - load model once and reuse
_easyocr_reader = None

def _get_easyocr_reader():
    """Get or create cached EasyOCR reader instance."""
    global _easyocr_reader
    if _easyocr_reader is None:
        try:
            import easyocr
            _easyocr_reader = easyocr.Reader(['en'], gpu=False)
        except ImportError:
            return None
    return _easyocr_reader


def run_cmd(cmd: List[str]) -> str:
    """Execute a shell command and return its output.

    Args:
        cmd: List of command and arguments to execute.

    Returns:
        Stripped stdout output from the command.

    Raises:
        subprocess.CalledProcessError: If the command returns non-zero exit code.
    """
    return subprocess.check_output(cmd, text=True).strip()


def front_app_info() -> Dict[str, str]:
    """Get information about the frontmost application and window.

    Uses AppleScript to detect the frontmost app and window title.
    Requires Accessibility permissions on macOS.

    Returns:
        Dictionary with keys:
        - bundle_id: Application bundle identifier.
        - app: Application name.
        - window_title: Title of the frontmost window, or "Unknown" if unavailable.
    """
    # Use AppleScript for app detection
    applescript = (
        'tell application "System Events"\n'
        '  set frontApp to first application process whose frontmost is true\n'
        '  set appName to name of frontApp\n'
        '  set winTitle to "Unknown"\n'
        '  try\n'
        '    set winTitle to name of front window of frontApp\n'
        '  end try\n'
        'end tell\n'
        'return appName & "\n" & winTitle\n'
    )
    try:
        output = subprocess.check_output(
            ["osascript", "-e", applescript],
            text=True
        ).splitlines()
        app_name = output[0].strip() if output else "Unknown"
        window_title = output[1].strip() if len(output) > 1 else "Unknown"
        return {
            "bundle_id": "unknown.bundle",
            "app": app_name or "Unknown",
            "window_title": window_title or "Unknown"
        }
    except Exception:
        return {
            "bundle_id": "unknown.bundle",
            "app": "Unknown",
            "window_title": "Unknown"
        }


def ocr_with_easyocr(path: Path, max_lines: int, min_confidence: float = 0.5) -> List[str]:
    """Extract text from an image using EasyOCR (deep learning OCR).

    Uses EasyOCR for high-quality text extraction. The model is cached
    and reused across calls for better performance.

    Args:
        path: Path to the image file.
        max_lines: Maximum number of lines to return.
        min_confidence: Minimum confidence threshold (0.0-1.0).

    Returns:
        List of text lines extracted by EasyOCR, up to max_lines.
        Returns empty list if EasyOCR is unavailable or fails.
    """
    reader = _get_easyocr_reader()
    if reader is None:
        return []

    try:
        results = reader.readtext(str(path))
        # Filter by confidence and extract text
        lines = [
            text.strip()
            for (bbox, text, conf) in results
            if conf >= min_confidence and text.strip() and len(text.strip()) > 2
        ]
        return lines[:max_lines]
    except Exception as e:
        import logging
        logger = logging.getLogger("questlog")
        logger.debug("EasyOCR failed: %s", e)
        return []


def ocr_lines(path: Path, max_lines: int) -> List[str]:
    """Extract text lines from an image using OCR.

    Uses Python Tesseract for OCR extraction with optimized settings for screenshots.

    Args:
        path: Path to the image file.
        max_lines: Maximum number of lines to return.

    Returns:
        List of non-empty text lines extracted from the image, up to max_lines.
        Returns empty list if OCR fails or dependencies are unavailable.
    """
    # Use Python Tesseract for OCR
    if Image is None or pytesseract is None:
        return []
    try:
        image = Image.open(path)

        # Try multiple PSM modes for better accuracy
        # PSM 6 = Uniform block of text (good for code/UI)
        # PSM 11 = Sparse text (good for scattered UI elements)
        # PSM 13 = Raw line (no layout analysis)
        psm_modes = [6, 11, 13]
        all_lines = set()

        for psm in psm_modes:
            try:
                # Use double braces to escape in f-string
                whitelist = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.,;:!?@#$%^&*()_+-=[]{{}}|\\/"\'<>~` '
                config = f'--psm {psm} -c tessedit_char_whitelist={whitelist}'
                text = pytesseract.image_to_string(image, config=config)
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                all_lines.update(lines)
            except Exception:
                continue

        # If no results with whitelist, try without it
        if not all_lines:
            try:
                text = pytesseract.image_to_string(image, config='--psm 6')
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                all_lines.update(lines)
            except Exception:
                pass

        result = list(all_lines)[:max_lines]
        return result
    except Exception:
        return []


def ocr_with_llm(cfg: Dict[str, Any], path: Path, max_lines: int) -> List[str]:
    """Extract text from an image using an LLM vision model.

    Uses a vision-capable model (like moondream) to extract text from screenshots.
    Falls back gracefully if the model is unavailable or the request fails.

    Args:
        cfg: Configuration dictionary with Ollama settings.
        path: Path to the image file.
        max_lines: Maximum number of lines to return.

    Returns:
        List of text lines extracted by the vision model, up to max_lines.
        Returns empty list if LLM OCR is disabled, model unavailable, or request fails.
    """
    if not cfg.get("ollama", {}).get("enabled", False):
        return []

    try:
        import requests

        ocr_cfg = cfg["ollama"].get("ocr", {})
        if not ocr_cfg.get("model"):
            return []

        endpoint_cfg = cfg["ollama"].get("endpoint", "http://localhost:11434")
        def _join(u: str, path: str) -> str:
            return u.rstrip("/") + path
        gen_url = endpoint_cfg if endpoint_cfg.endswith("/api/generate") else _join(endpoint_cfg, "/api/generate")

        model = ocr_cfg.get("model")

        # Check if model is available
        try:
            tags_url = gen_url.replace("/api/generate", "/api/tags")
            tags = requests.get(tags_url, timeout=2)
            names = set()
            if tags.ok:
                tj = tags.json()
                listing = tj.get("models") if isinstance(tj, dict) else (tj if isinstance(tj, list) else [])
                for m in listing or []:
                    if isinstance(m, dict) and m.get("name"):
                        names.add(m["name"])
            if model not in names:
                return []  # Model not available, fall back to traditional OCR
        except Exception:
            return []

        # Use vision model for OCR with improved prompt to reduce hallucinations
        prompt = """Extract ONLY the actual visible text from this screenshot image.

CRITICAL RULES:
- Return ONLY text that you can clearly see in the image
- Do NOT invent, guess, or hallucinate text
- Do NOT add explanations or commentary
- Preserve line breaks as they appear
- Include window titles, file names, URLs, code snippets, button labels, and any other visible text
- If you cannot clearly read text, skip it rather than guessing

Return the text content line by line, exactly as it appears."""

        # Encode image to base64 for Ollama API
        import base64
        with open(path, "rb") as img_file:
            image_data = base64.b64encode(img_file.read()).decode("utf-8")

        gen_payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "images": [image_data]
        }

        resp = requests.post(gen_url, json=gen_payload, timeout=30)
        resp.raise_for_status()

        response_text = (resp.json() or {}).get("response", "")
        if response_text:
            # Filter out common hallucination patterns and extract actual text
            filtered_lines = []
            skip_patterns = [
                "The image",
                "I can",
                "Here's",
                "Sure,",
                "This image",
                "The screenshot",
                "There is no",
                "does not contain",
                "This is an",
                "indicating",
                "suggesting",
                "likely",
                "possibly",
                "shows:",
                "showing",
            ]

            # Look for bullet points or quoted text (actual extracted text)
            in_list = False
            for line in response_text.splitlines():
                line_stripped = line.strip()
                if not line_stripped:
                    continue

                # Skip explanation lines
                if any(line_stripped.startswith(pattern) for pattern in skip_patterns):
                    continue

                # Extract bullet point content (often contains actual text)
                if line_stripped.startswith('- ') or line_stripped.startswith('* '):
                    # Remove bullet and extract quoted text if present
                    content = line_stripped[2:].strip()
                    # Extract text from quotes
                    if '"' in content:
                        import re
                        quoted = re.findall(r'"([^"]+)"', content)
                        if quoted:
                            filtered_lines.extend(quoted)
                            continue
                    # Or use the content after the bullet
                    if content and len(content) > 3:
                        filtered_lines.append(content)
                    continue

                # Extract quoted text
                if '"' in line_stripped:
                    import re
                    quoted = re.findall(r'"([^"]+)"', line_stripped)
                    if quoted:
                        filtered_lines.extend(quoted)
                        continue

                # Skip lines that are explanations (contain words like "indicating", "suggesting")
                if any(word in line_stripped.lower() for word in ['indicating', 'suggesting', 'likely', 'possibly', 'probably']):
                    continue

                # Remove markdown code blocks if present
                line_stripped = line_stripped.strip('`').strip()
                # Only add if it looks like actual text (not an explanation)
                if line_stripped and len(line_stripped) > 2 and not line_stripped.endswith(':'):
                    filtered_lines.append(line_stripped)

            return filtered_lines[:max_lines]

    except Exception as e:
        import logging
        logger = logging.getLogger("questlog")
        logger.debug("LLM OCR failed: %s", e)
        pass

    return []


def analyze_image_with_vision(cfg: Dict[str, Any], path: Path) -> Dict[str, Any]:
    """Analyze an image using LLM vision for holistic scene understanding.

    Uses a vision-capable model to understand the entire screenshot scene,
    identifying apps, windows, layout, activities, and projects. This is
    the primary analysis method, with OCR used as supplemental context.

    Args:
        cfg: Configuration dictionary with Ollama settings.
        path: Path to the image file.

    Returns:
        Dictionary with structured analysis results:
        - apps_visible: List of all visible applications
        - primary_app: Main application in focus
        - window_titles: List of window titles visible
        - primary_window_title: Main window title
        - layout: Layout type (single-window, dual-pane, etc.)
        - layout_description: Description of screen layout
        - primary_activity: What user is primarily doing
        - secondary_activities: List of secondary activities
        - project_indicators: List of project/repo indicators found
        - summary: Activity summary
        - coarse_task: Task category
        - confidence: Confidence score (0.0-1.0)
        Returns empty dict if vision analysis fails or is disabled.
    """
    if not cfg.get("ollama", {}).get("enabled", False):
        return {}

    try:
        import requests
        import base64
        import logging

        logger = logging.getLogger("questlog")

        vision_cfg = cfg.get("ollama", {}).get("vision_analysis", {})
        # Fall back to OCR model if vision_analysis not configured
        if not vision_cfg.get("model"):
            vision_cfg = cfg.get("ollama", {}).get("ocr", {})

        if not vision_cfg.get("model"):
            return {}

        # Check if vision analysis is enabled (default True)
        if vision_cfg.get("enabled", True) is False:
            return {}

        endpoint_cfg = cfg["ollama"].get("endpoint", "http://localhost:11434")
        def _join(u: str, path: str) -> str:
            return u.rstrip("/") + path
        gen_url = endpoint_cfg if endpoint_cfg.endswith("/api/generate") else _join(endpoint_cfg, "/api/generate")

        model = vision_cfg.get("model")

        # Check if model is available
        try:
            tags_url = gen_url.replace("/api/generate", "/api/tags")
            tags = requests.get(tags_url, timeout=2)
            names = set()
            if tags.ok:
                tj = tags.json()
                listing = tj.get("models") if isinstance(tj, dict) else (tj if isinstance(tj, list) else [])
                for m in listing or []:
                    if isinstance(m, dict) and m.get("name"):
                        names.add(m["name"])
            if model not in names:
                logger.debug("Vision model %s not available", model)
                return {}  # Model not available
        except Exception as e:
            logger.debug("Failed to check vision model availability: %s", e)
            return {}

        # Build vision analysis prompt
        from ql.text import build_vision_analysis_prompt
        prompt = build_vision_analysis_prompt(cfg.get("projects", []))

        # Encode image to base64 for Ollama API
        with open(path, "rb") as img_file:
            image_data = base64.b64encode(img_file.read()).decode("utf-8")

        gen_payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "images": [image_data]
        }

        resp = requests.post(gen_url, json=gen_payload, timeout=60)
        resp.raise_for_status()

        response_text = (resp.json() or {}).get("response", "")
        if not response_text:
            return {}

        # Try to parse JSON response
        try:
            # Extract JSON from response (might have markdown code blocks)
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                json_text = response_text[json_start:json_end]
                result = json.loads(json_text)
                # Validate and normalize result
                return {
                    "apps_visible": result.get("apps_visible", []),
                    "primary_app": result.get("primary_app", "Unknown"),
                    "window_titles": result.get("window_titles", []),
                    "primary_window_title": result.get("primary_window_title", "Unknown"),
                    "layout": result.get("layout", "single-window"),
                    "layout_description": result.get("layout_description", ""),
                    "primary_activity": result.get("primary_activity", ""),
                    "secondary_activities": result.get("secondary_activities", []),
                    "project_indicators": result.get("project_indicators", []),
                    "summary": result.get("summary", ""),
                    "coarse_task": result.get("coarse_task", "Unknown"),
                    "confidence": float(result.get("confidence", 0.5)),
                }
            else:
                logger.warning("Vision analysis response contains no JSON")
                return {}
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse vision analysis JSON: %s. Response: %s", e, response_text[:200])
            return {}

    except Exception as e:
        import logging
        logger = logging.getLogger("questlog")
        logger.debug("Vision analysis failed: %s", e)
        return {}


