"""Analysis-related commands."""

import datetime as dt
import json
import os
import subprocess
from pathlib import Path

import requests
import typer

from ql.processing import resolve_project, summarize
from ql.text import build_historian_prompt, extract_clues, find_artifacts, redact
from questlog.config import load_config
from questlog.services import ImageService, setup_logging

# Create command group
app = typer.Typer(name="analyze", help="Analysis commands")


def _analyze_image(image_path: Path, cfg, image_service: ImageService) -> dict:
    """Analyze an image and return results.

    Args:
        image_path: Path to image file.
        cfg: Configuration.
        image_service: Image service instance.

    Returns:
        Analysis result dictionary.
    """
    meta = image_service.front_app_info()
    app_name = meta.get("app", "Unknown")
    window_title = meta.get("window_title", "Unknown")
    ocr_top_raw = image_service.ocr_lines(image_path, cfg.max_ocr_lines)
    redacted = [redact(l) for l in ocr_top_raw]
    clues = extract_clues(app_name, window_title, redacted)
    proj_guess = resolve_project(
        cfg.projects, cfg.project_aliases, window_title, redacted, clues
    )
    summary, coarse_task, confidence = summarize(
        cfg.to_dict(), app_name, window_title, redacted, proj_guess, clues
    )
    artifacts = find_artifacts(window_title, redacted)

    return {
        "app": app_name,
        "window_title": window_title,
        "ocr_top": redacted,
        "clues": clues,
        "project": proj_guess[0],
        "coarse_task": coarse_task,
        "summary": summary,
        "confidence": confidence,
        "artifacts": artifacts,
        "image": str(image_path),
    }


@app.command(name="analyze-now")
def analyze_now() -> None:
    """Capture and print a one-off JSON analysis (no DB write)."""
    cfg = load_config()
    setup_logging(cfg)
    image_service = ImageService(cfg)

    base = Path(cfg.base_folder)
    today_dir = image_service.ensure_today_dir(base)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    shot = today_dir / f"questlog_snap_{ts}.png"

    try:
        subprocess.run(["screencapture", "-x", str(shot)], check=True)
    except Exception as e:
        typer.echo(f"screencapture failed: {e}", err=True)
        raise typer.Exit(2)

    result = _analyze_image(shot, cfg, image_service)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command(name="analyze-file")
def analyze_file(
    image: str = typer.Argument(..., help="Path to screenshot image"),
) -> None:
    """Analyze an existing screenshot image (no DB write)."""
    cfg = load_config()
    setup_logging(cfg)
    image_service = ImageService(cfg)

    img = Path(image).expanduser()
    if not img.exists():
        typer.echo(f"Image not found: {img}", err=True)
        raise typer.Exit(2)

    result = _analyze_image(img, cfg, image_service)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command(name="what-image")
def what_image(
    image: str = typer.Argument(..., help="Path to screenshot image"),
    vision: bool = typer.Option(False, "--vision", help="Send the image to Ollama vision model"),
) -> None:
    """Generate historian Markdown for an image (OCR-only by default)."""
    cfg = load_config()
    setup_logging(cfg)
    image_service = ImageService(cfg)

    img = Path(image).expanduser()
    if not img.exists():
        typer.echo(f"Image not found: {img}", err=True)
        raise typer.Exit(2)

    ocr_top = image_service.ocr_lines(img, cfg.max_ocr_lines)
    prompt = build_historian_prompt(ocr_top)

    # Provider: OpenAI (if enabled) else Ollama generate
    text = ""
    try:
        if cfg.openai.enabled:
            if vision:
                raise RuntimeError(
                    "--vision is not implemented for OpenAI in this command. "
                    "Enable Ollama or omit --vision."
                )
            api_key_env = cfg.openai.api_key_env
            api_key = os.environ.get(api_key_env)
            if not api_key:
                raise RuntimeError(f"Missing OpenAI API key in env var {api_key_env}")
            api_base = cfg.openai.api_base.rstrip("/")
            model = cfg.openai.model
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            body = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
            }
            r = requests.post(
                f"{api_base}/chat/completions", headers=headers, json=body, timeout=60
            )
            r.raise_for_status()
            data = r.json() or {}
            choices = data.get("choices", [])
            if choices:
                text = (choices[0].get("message") or {}).get("content", "").strip()
        else:
            endpoint_cfg = cfg.ollama.endpoint
            gen_url = (
                endpoint_cfg
                if endpoint_cfg.endswith("/api/generate")
                else endpoint_cfg.rstrip("/") + "/api/generate"
            )
            model = cfg.ollama.summarization.model
            payload = {"model": model, "prompt": prompt, "stream": False}
            if vision:
                payload["images"] = [str(img)]
            r = requests.post(gen_url, json=payload, timeout=60)
            r.raise_for_status()
            text = (r.json() or {}).get("response", "").strip()
    except Exception as e:
        typer.echo(f"Historian failed: {e}", err=True)
        raise typer.Exit(1)

    out_dir = Path("exports")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"historian_{img.stem}.md"
    out_path.write_text(text or "(no response)")
    typer.echo(f"Wrote {out_path}")

