"""Database-related commands."""

import typer

from questlog.services import DatabaseService

# Create command group
app = typer.Typer(name="db", help="Database management commands")


@app.command()
def init_db() -> None:
    """Initialize the SQLite database."""
    db_service = DatabaseService()
    db_service.ensure_schema()
    typer.echo(f"Initialized DB at {db_service.db_path}")

