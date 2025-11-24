"""Export-related commands."""

import datetime as dt
import typer

from questlog.config import load_config
from questlog.services import DatabaseService, ExportService

# Create command group
app = typer.Typer(name="export", help="Export commands")


@app.command(name="export-md")
def export_md(
    date: str = typer.Option(..., "--date", help="Date in YYYY-MM-DD format"),
) -> None:
    """Export a daily Markdown timeline."""
    cfg = load_config()
    db_service = DatabaseService()
    export_service = ExportService(cfg)

    with db_service.connect() as conn:
        out_path = export_service.export_markdown(conn, date)

    typer.echo(f"Wrote {out_path}")


@app.command(name="export-csv")
def export_csv(
    date: str = typer.Option(..., "--date", help="Date in YYYY-MM-DD format"),
) -> None:
    """Export a daily CSV."""
    cfg = load_config()
    db_service = DatabaseService()
    export_service = ExportService(cfg)

    with db_service.connect() as conn:
        out_path = export_service.export_csv(conn, date)

    typer.echo(f"Wrote {out_path}")


@app.command(name="hour-summary")
def hour_summary(
    datetime_str: str = typer.Option(
        ...,
        "--datetime",
        help="Start datetime in YYYY-MM-DDTHH:00 format (e.g., 2025-11-20T11:00)",
    ),
) -> None:
    """Generate a one-hour summary using LLM."""
    cfg = load_config()
    db_service = DatabaseService()
    export_service = ExportService(cfg)

    try:
        start_time = dt.datetime.fromisoformat(datetime_str)
    except ValueError:
        typer.echo(f"Error: Invalid datetime format. Use YYYY-MM-DDTHH:00 (e.g., 2025-11-20T11:00)")
        raise typer.Exit(1)

    with db_service.connect() as conn:
        summary = export_service.generate_hour_summary(conn, start_time)

    typer.echo("\n" + "=" * 80)
    typer.echo(summary)
    typer.echo("=" * 80 + "\n")

