from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from screener.collector import TwelveDataWindowCollector
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


@app.command("collect-window")
def collect_window(
    run_date: str = typer.Option(..., "--date", help="Run date in YYYY-MM-DD format."),
    window_index: int = typer.Option(..., min=0, help="Zero-based window index to collect."),
    total_windows: int = typer.Option(6, min=1, help="Total collection windows planned for the day."),
    max_credits_per_minute: int = typer.Option(8, min=1, help="Per-minute request budget."),
    dry_run: bool = typer.Option(False, help="Plan and execute the window without writing artifacts."),
    output_dir: Path = typer.Option(Path("output/intraday"), help="Root directory for intraday collection artifacts."),
) -> None:
    settings = get_settings(output_dir=output_dir, market_data_provider="twelve-data")
    collector = TwelveDataWindowCollector(settings=settings)
    result = collector.run_window(
        run_date=parse_run_date(run_date),
        output_root=settings.output_dir,
        window_index=window_index,
        total_windows=total_windows,
        max_credits_per_minute=max_credits_per_minute,
        dry_run=dry_run,
    )

    typer.echo(f"Window: {result.plan.window_index + 1}/{result.plan.total_windows}")
    typer.echo(f"Planned tickers: {len(result.plan.window_tickers)}")
    typer.echo(f"Collected: {len(result.collected)}")
    typer.echo(f"Failures: {len(result.failures)}")
    typer.echo(f"Remaining after window: {len(result.plan.remaining_tickers)}")

    if dry_run:
        typer.echo("Artifacts skipped (--dry-run).")
        return

    typer.echo(f"Run directory: {result.artifacts.run_directory}")
    typer.echo(f"Metadata report: {result.artifacts.metadata_path}")
    typer.echo(f"Quotes report: {result.artifacts.quotes_path}")


if __name__ == "__main__":
    app()
