"""Resume/re-entry command."""

import json

import typer

from questlog.config import load_config
from questlog.services import DatabaseService, ResumeService

app = typer.Typer(name="resume", help="Build a restart note from recent activity")


@app.command(name="resume")
def resume(
    hours: float = typer.Option(
        4.0,
        "--hours",
        min=0.25,
        help="How many recent hours to include in the restart note",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print structured resume data as JSON",
    ),
) -> None:
    """Print a local, heuristic restart note for recent activity."""
    cfg = load_config()
    db_service = DatabaseService()
    resume_service = ResumeService(cfg)

    with db_service.connect() as conn:
        data = resume_service.build_resume(conn, hours=hours)

    if json_output:
        typer.echo(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        typer.echo(resume_service.render_text(data))
