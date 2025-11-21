"""Diagnostic commands."""

import datetime as dt
import os
from pathlib import Path

import typer

from questlog.config import load_config
from questlog.services import ImageService

# Create command group
app = typer.Typer(name="diagnostic", help="Diagnostic commands")

IMAGE_EXTS = {".png", ".jpg", ".jpeg"}
BIN_FRONTAPP = Path("bin/frontapp")
BIN_OCR = Path("bin/ocrshot")


@app.command()
def doctor() -> None:
    """Run environment and config checks."""
    try:
        cfg = load_config()
    except Exception as e:
        typer.echo(f"Config load failed: {e}", err=True)
        raise typer.Exit(1)

    ok = True
    image_service = ImageService(cfg)

    typer.echo("== QuestLog Doctor ==")
    typer.echo(f"Base folder: {cfg.base_folder}")
    base = Path(cfg.base_folder)
    if not base.exists():
        typer.echo("  [!] base_folder does not exist.")
        ok = False
    else:
        today_dir = base / dt.date.today().strftime("%Y-%m-%d")
        typer.echo(f"  Today subdir: {today_dir} (exists: {today_dir.exists()})")

    # Binaries
    typer.echo(f"Frontapp binary: {BIN_FRONTAPP} (exists: {BIN_FRONTAPP.exists()})")
    typer.echo(f"OCR binary: {BIN_OCR} (exists: {BIN_OCR.exists()})")
    if not BIN_FRONTAPP.exists() or not BIN_OCR.exists():
        typer.echo(
            "  [i] One or more Swift helpers missing. You can still run with degraded features."
        )

    # Try front app info
    try:
        meta = image_service.front_app_info()
        typer.echo(
            f"  front app info; app: {meta.get('app')}, title: {meta.get('window_title')}"
        )
        if meta.get("window_title", "Unknown") == "Unknown":
            typer.echo(
                "  [i] Window title is 'Unknown' - check Accessibility permission for your terminal."
            )
    except Exception as e:
        typer.echo(f"  [!] front app info failed: {e}")
        ok = False

    # Try OCR on any one file
    test_file = None
    if base.exists():
        for root, dirs, files in os.walk(base):
            for name in files:
                p = Path(root) / name
                if p.suffix.lower() in IMAGE_EXTS:
                    test_file = p
                    break
            if test_file:
                break
    if test_file and BIN_OCR.exists():
        try:
            lines = image_service.ocr_lines(test_file, cfg.max_ocr_lines)
            typer.echo(f"  OCR ok; {len(lines)} lines from {test_file.name}")
        except Exception as e:
            typer.echo(f"  [!] OCR test failed: {e}")
            ok = False
    else:
        typer.echo("  [i] OCR sanity check skipped (no sample image or ocr helper missing).")

    result = "OK" if ok else "Issues found. See README and questlog.log for guidance."
    typer.echo(f"Doctor result: {result}")

