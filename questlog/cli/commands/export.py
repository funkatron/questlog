"""Export-related commands."""

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

