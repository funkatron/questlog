"""Capture-related commands."""

import datetime as dt
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Iterator, Optional

import typer
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from questlog.config import load_config
from questlog.services import DatabaseService, ImageService, setup_logging

logger = logging.getLogger("questlog")

# Create command group
app = typer.Typer(name="capture", help="Screenshot capture commands")

_BACKFILL_HEARTBEAT_SEC = 10.0


def _iter_backfill_images(
    base: Path,
    *,
    today_date: Optional[str],
    days: Optional[int],
    image_service: ImageService,
) -> Iterator[Path]:
    """Yield image paths for backfill.

    When ``--days`` or ``--today`` is used, only walks TimeSnapper-style
    ``YYYY-MM-DD`` folders under ``base`` so we do not scan the entire archive.
    Falls back to a full recursive walk if no matching day folders exist.
    """
    if today_date:
        day_dir = base / today_date
        if not day_dir.is_dir():
            typer.echo(f"  [!] No folder for today ({today_date}) under base_folder.")
            return
        for root, _dirs, files in os.walk(day_dir):
            for name in files:
                p = Path(root) / name
                if p.suffix.lower() in IMAGE_EXTS:
                    yield p
        return

    if days is not None:
        day_roots: list[Path] = []
        for i in range(days):
            label = (dt.date.today() - dt.timedelta(days=i)).isoformat()
            p = base / label
            if p.is_dir():
                day_roots.append(p)
        if day_roots:
            for day_dir in day_roots:
                for root, _dirs, files in os.walk(day_dir):
                    for name in files:
                        p = Path(root) / name
                        if p.suffix.lower() in IMAGE_EXTS:
                            yield p
            return
        typer.echo(
            "  [i] No YYYY-MM-DD day folders in range; scanning full tree under base_folder."
        )

    yield from image_service.iter_images(base)

IMAGE_EXTS = {".png", ".jpg", ".jpeg"}


class ShotHandler(FileSystemEventHandler):
    """File system event handler for watching screenshots."""

    def __init__(self, db_service: DatabaseService, image_service: ImageService):
        """Initialize handler with services.

        Args:
            db_service: Database service.
            image_service: Image service.
        """
        self.db_service = db_service
        self.image_service = image_service

    def _process_path(self, p: Path) -> None:
        """Process a file path if it's an image.

        Args:
            p: Path to file.
        """
        if p.suffix.lower() not in IMAGE_EXTS:
            return
        # Give writers a moment to finish
        time.sleep(0.3)
        try:
            with self.db_service.connect() as conn:
                if self.db_service.already_processed(conn, str(p)):
                    return
                logger.info("watch event processing: %s", p)
                self.image_service.process_image(conn, p)
        except Exception as e:
            logger.error("watch error on %s: %s", p, e)

    def on_created(self, event) -> None:
        """Handle file creation event."""
        if event.is_directory:
            return
        p = Path(event.src_path)
        self._process_path(p)

    def on_modified(self, event) -> None:
        """Handle file modification event."""
        if event.is_directory:
            return
        p = Path(event.src_path)
        self._process_path(p)

    def on_moved(self, event) -> None:
        """Handle file move event."""
        if event.is_directory:
            return
        p = Path(getattr(event, "dest_path", event.src_path))
        self._process_path(p)


@app.command()
def snap() -> None:
    """Capture a screenshot and index it."""
    cfg = load_config()
    setup_logging(cfg)
    db_service = DatabaseService()
    image_service = ImageService(cfg)
    db_service.ensure_schema()

    base = Path(cfg.base_folder)
    today_dir = image_service.ensure_today_dir(base)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = today_dir / f"questlog_snap_{ts}.png"

    try:
        subprocess.run(["screencapture", "-x", str(out_path)], check=True)
    except subprocess.CalledProcessError as e:
        typer.echo(f"screencapture failed: {e}", err=True)
        typer.echo(
            "If prompted, grant Screen Recording permission to your terminal.",
            err=True,
        )
        raise typer.Exit(2)
    except FileNotFoundError:
        typer.echo("screencapture tool not found. This command requires macOS.", err=True)
        raise typer.Exit(2)

    with db_service.connect() as conn:
        try:
            entry_id = image_service.process_image(conn, out_path)
        except Exception as e:
            logger.error("snap index failed: %s", e)
            entry_id = None

    typer.echo(f"Captured: {out_path}")
    if entry_id:
        typer.echo(f"Indexed entry_id: {entry_id}")


@app.command()
def capture(
    interval: int = typer.Option(60, "--interval", "-i", help="Seconds between captures"),
) -> None:
    """Continuously capture screenshots at an interval and index them."""
    cfg = load_config()
    setup_logging(cfg)
    db_service = DatabaseService()
    image_service = ImageService(cfg)
    db_service.ensure_schema()

    base = Path(cfg.base_folder)
    interval = max(5, interval)
    typer.echo(f"Capturing every {interval}s. Press Ctrl+C to stop.")

    try:
        while True:
            ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            today_dir = image_service.ensure_today_dir(base)
            shot = today_dir / f"questlog_snap_{ts}.png"
            try:
                subprocess.run(["screencapture", "-x", str(shot)], check=True)
                with db_service.connect() as conn:
                    image_service.process_image(conn, shot)
            except Exception as e:
                logger.error("capture cycle failed: %s", e)
            time.sleep(interval)
    except KeyboardInterrupt:
        typer.echo("Stopped continuous capture.")


@app.command()
def watch() -> None:
    """Watch the folder for new screenshots."""
    cfg = load_config()
    setup_logging(cfg)
    db_service = DatabaseService()
    image_service = ImageService(cfg)

    base = Path(cfg.base_folder)
    if not base.exists():
        typer.echo(f"Base folder does not exist: {base}", err=True)
        raise typer.Exit(2)

    db_service.ensure_schema()
    event_handler = ShotHandler(db_service, image_service)
    obs = Observer()
    obs.schedule(event_handler, str(base), recursive=True)
    obs.start()
    typer.echo(f"Watching: {base}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        obs.stop()
        obs.join()


@app.command()
def backfill(
    days: Optional[int] = typer.Option(None, "--days", "-d", help="Only process last N days"),
    today: bool = typer.Option(False, "--today", help="Only process today's images"),
    debug: bool = typer.Option(False, "--debug", help="Enable debug logging and show OCR output"),
) -> None:
    """Scan historical screenshots and index them."""
    cfg = load_config()
    setup_logging(cfg, debug=debug)
    db_service = DatabaseService()
    image_service = ImageService(cfg)

    base = Path(cfg.base_folder)
    cutoff = None
    today_date = None

    if today:
        today_date = dt.date.today().strftime("%Y-%m-%d")
        typer.echo(f"Processing only images from today: {today_date}")
    elif days is not None:
        cutoff = time.time() - (days * 86400)
        typer.echo(f"Processing images from last {days} days")

    db_service.ensure_schema()

    started = time.monotonic()
    last_heartbeat = started

    with db_service.connect() as conn:
        count = 0
        skipped = 0
        scanned = 0

        for p in _iter_backfill_images(
            base,
            today_date=today_date if today else None,
            days=days if not today else None,
            image_service=image_service,
        ):
            scanned += 1
            try:
                # Filter by today's date if requested (only when scanning full tree)
                if today_date:
                    file_date = p.parent.name
                    if file_date != today_date:
                        skipped += 1
                        if debug:
                            logger.debug("Skipping %s (not today's date: %s)", p.name, file_date)
                        continue

                # Filter by days cutoff if specified (full-tree fallback or edge cases)
                if cutoff and p.stat().st_mtime < cutoff:
                    skipped += 1
                    continue

                if db_service.already_processed(conn, str(p)):
                    skipped += 1
                    if debug:
                        logger.debug("Skipping %s (already processed)", p.name)
                    continue

                if debug:
                    logger.debug("Processing: %s", p)

                # Historical screenshots: skip app detection, infer from content
                image_service.process_image(conn, p, use_app_detection=False)
                count += 1
                if debug:
                    typer.echo(f"✓ Processed {p.name} ({count} total)")
                elif count % 50 == 0:
                    typer.echo(f"Processed {count} new files...")
            except Exception as e:
                logger.error("backfill error on %s: %s", p, e)
                if debug:
                    typer.echo(f"✗ Error processing {p.name}: {e}", err=True)

            now = time.monotonic()
            if now - last_heartbeat >= _BACKFILL_HEARTBEAT_SEC:
                elapsed = now - started
                scan_rate = scanned / elapsed if elapsed > 0 else 0.0
                rate_fmt = f"{scan_rate:.2f}" if scan_rate < 1 else f"{scan_rate:.1f}"
                parts = [
                    f"  ... {elapsed:.0f}s",
                    f"scanned={scanned}",
                    f"new={count}",
                    f"skipped={skipped}",
                    f"{rate_fmt} scanned/s",
                ]
                if count > 0:
                    parts.append(f"~{elapsed / count:.0f}s avg per new")
                typer.echo("  ".join(parts))
                last_heartbeat = now

        total_s = time.monotonic() - started
        typer.echo(
            f"Backfill complete in {total_s:.1f}s. Processed {count} new screenshots, skipped {skipped} "
            f"(scanned {scanned}). See {cfg.logfile} for details."
        )

