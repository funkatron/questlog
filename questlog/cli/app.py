"""Main CLI application."""

import typer

from questlog.cli.commands import analyze, benchmark, capture, database, diagnostic, export

# Create main Typer app
app = typer.Typer(
    name="questlog",
    help="Activity logging from screenshots",
    add_completion=False,
)

# Register individual commands (for backward compatibility with old command names)
app.command(name="init-db")(database.init_db)
app.command()(capture.snap)
app.command()(capture.capture)
app.command()(capture.watch)
app.command()(capture.backfill)
app.command(name="export-md")(export.export_md)
app.command(name="export-csv")(export.export_csv)
app.command(name="hour-summary")(export.hour_summary)
app.command(name="analyze-now")(analyze.analyze_now)
app.command(name="analyze-file")(analyze.analyze_file)
app.command(name="what-image")(analyze.what_image)
app.command()(diagnostic.doctor)
app.command(name="benchmark")(benchmark.show)


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()

