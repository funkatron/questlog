from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import List
try:
    from PIL import Image
    import pytesseract
except Exception:
    Image = None
    pytesseract = None


def run_cmd(cmd: List[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()


def front_app_info(frontapp_bin: Path) -> dict:
    if frontapp_bin.exists():
        out = run_cmd([str(frontapp_bin)])
        return json.loads(out)
    # AppleScript fallback
    script = (
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
        out = subprocess.check_output(["osascript", "-e", script], text=True).splitlines()
        app = out[0].strip() if out else "Unknown"
        title = out[1].strip() if len(out) > 1 else "Unknown"
        return {"bundle_id": "unknown.bundle", "app": app or "Unknown", "window_title": title or "Unknown"}
    except Exception:
        return {"bundle_id": "unknown.bundle", "app": "Unknown", "window_title": "Unknown"}


def ocr_lines(ocr_bin: Path, path: Path, max_lines: int) -> List[str]:
    # Prefer native Swift OCR helper
    if ocr_bin.exists():
        try:
            out = run_cmd([str(ocr_bin), str(path)])
            lines = [l for l in out.splitlines() if l.strip()]
            if lines:
                return lines[:max_lines]
        except Exception:
            pass
    # Python fallback via Tesseract
    if Image is None or pytesseract is None:
        return []
    try:
        img = Image.open(path)
        text = pytesseract.image_to_string(img)
        lines = [l for l in text.splitlines() if l.strip()]
        return lines[:max_lines]
    except Exception:
        return []


