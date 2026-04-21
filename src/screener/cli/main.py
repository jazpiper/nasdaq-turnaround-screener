from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from screener.config import get_settings
from screener.pipeline import ScreenPipeline, build_context

app = typer.Typer(help="NASDAQ turnaround screener CLI.")


@app.callback()
def main() -> None:
    """Run NASDAQ turnaround screener commands."""


def parse_run_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:  # pragma: no cover, handled by typer
        raise typer.BadParameter("Date must be in YYYY-MM-DD format.") from exc


@app.command()
def run(
    run_date: str = typer.Option(..., "--date", help="Run date in YYYY-MM-DD format."),
    dry_run: bool = typer.Option(False, help="Execute the scaffold without writing artifacts."),
    output_dir: Path = typer.Option(Path("output"), help="Directory for generated artifacts."),
) -> None:
    settings = get_settings(output_dir=output_dir)
    context = build_context(run_date=parse_run_date(run_date), dry_run=dry_run, output_dir=settings.output_dir, run_mode=settings.default_run_mode, universe_name=settings.universe_name)
    result, artifacts = ScreenPipeline(settings=settings).run(context)

    typer.echo(f"Run date: {result.metadata.run_date.isoformat()}")
    typer.echo(f"Dry run: {result.metadata.dry_run}")
    typer.echo(f"Candidate count: {result.candidate_count}")

    if dry_run:
        typer.echo("Artifacts skipped (--dry-run).")
        return

    typer.echo(f"Markdown report: {artifacts.markdown_path}")
    typer.echo(f"JSON report: {artifacts.json_report_path}")
    typer.echo(f"Metadata report: {artifacts.metadata_path}")


if __name__ == "__main__":
    app()
