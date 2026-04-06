"""Database-related commands."""

import typer

from questlog.config import load_config
from questlog.services import DatabaseService

# Create command group
app = typer.Typer(name="db", help="Database management commands")


@app.command()
def init_db() -> None:
    """Initialize the SQLite database and create config.yaml if missing."""
    # Auto-create config during initialization
    try:
        load_config(auto_create=True)
        typer.echo("Configuration file ready.")
    except FileNotFoundError:
        typer.echo("Warning: config.yaml not found and config.example.yaml not available.")

    db_service = DatabaseService()
    db_service.ensure_schema()
    typer.echo(f"Initialized DB at {db_service.db_path}")

