from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from screener.alerts import AlertSidecarError
from screener.backtest import HistoricalBacktestRunner
from screener.collector import CollectionResult, TwelveDataWindowCollector
from screener.config import Settings, get_settings
from screener.models import ScreenRunResult
from screener.pipeline import ScreenPipeline, build_context
from screener.storage import OracleSqlStorage, OracleSqlStorageError
from screener.storage.files import ensure_directory
from screener.tuning import TierThresholdsGrid, tune_single_window, walk_forward
from screener.tuning.report import (
    write_diff_markdown,
    write_diff_markdown_from_walkforward,
    write_grid_csv,
    write_proposal_json,
    write_proposal_json_from_walkforward,
    write_walkforward_json,
)

app = typer.Typer(help="NASDAQ turnaround screener CLI.")


@app.callback()
def main() -> None:
    """Run NASDAQ turnaround screener commands."""


def parse_run_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:  # pragma: no cover, handled by typer
        raise typer.BadParameter("Date must be in YYYY-MM-DD format.") from exc


def parse_horizons(value: str) -> tuple[int, ...]:
    horizons: list[int] = []
    for part in value.split(","):
        normalized = part.strip()
        if not normalized:
            continue
        try:
            horizon = int(normalized)
        except ValueError as exc:
            raise typer.BadParameter("Horizons must be a comma-separated list of integers.") from exc
        if horizon <= 0:
            raise typer.BadParameter("Horizons must be positive integers.")
        horizons.append(horizon)
    if not horizons:
        raise typer.BadParameter("At least one horizon is required.")
    return tuple(dict.fromkeys(horizons))


@app.command()
def run(
    run_date: str = typer.Option(..., "--date", help="Run date in YYYY-MM-DD format."),
    dry_run: bool = typer.Option(False, help="Execute the scaffold without writing artifacts."),
    output_dir: Path = typer.Option(Path("output"), help="Directory for generated artifacts."),
    use_staged_intraday: bool = typer.Option(False, "--use-staged-intraday", help="Prefer latest staged intraday quotes from output/intraday for same-day enrichment when available."),
    intraday_output_root: Path | None = typer.Option(None, "--intraday-output-root", help="Override staged intraday artifact root used with --use-staged-intraday."),
    persist_oracle_sql: bool = typer.Option(False, "--persist-oracle-sql", help="Write successful run results to Oracle SQL."),
) -> None:
    settings = get_settings(output_dir=output_dir)
    if use_staged_intraday:
        settings.daily_intraday_source_mode = "prefer-staged"
    if intraday_output_root is not None:
        settings.intraday_output_root = intraday_output_root
    if persist_oracle_sql:
        settings.oracle_sql_enabled = True
    context = build_context(run_date=parse_run_date(run_date), dry_run=dry_run, output_dir=settings.output_dir, run_mode=settings.default_run_mode, universe_name=settings.universe_name)
    try:
        result, artifacts = ScreenPipeline(settings=settings).run(context)
    except AlertSidecarError as exc:
        typer.echo(f"Alert sidecar generation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Run date: {result.metadata.run_date.isoformat()}")
    typer.echo(f"Dry run: {result.metadata.dry_run}")
    typer.echo(f"Candidate count: {result.candidate_count}")
    typer.echo(
        "Data quality: "
        f"nonempty={result.metadata.bars_nonempty_count}, "
        f"latest_date_mismatch={result.metadata.latest_bar_date_mismatch_count}, "
        f"insufficient_history={result.metadata.insufficient_history_count}"
    )
    if settings.daily_intraday_source_mode == "prefer-staged":
        typer.echo(f"Intraday source mode: {settings.daily_intraday_source_mode} ({settings.intraday_output_root})")

    if dry_run:
        typer.echo("Artifacts skipped (--dry-run).")
        return

    run_id = _persist_daily_run_if_enabled(settings, result)
    typer.echo(f"Markdown report: {artifacts.markdown_path}")
    typer.echo(f"JSON report: {artifacts.json_report_path}")
    typer.echo(f"Metadata report: {artifacts.metadata_path}")
    if artifacts.alert_events_path is not None:
        typer.echo(f"Alert events: {artifacts.alert_events_path}")
    if artifacts.stable_alert_events_path is not None:
        typer.echo(f"Stable alert entrypoint: {artifacts.stable_alert_events_path}")
    if run_id is not None:
        typer.echo(f"Oracle SQL run id: {run_id}")


@app.command("collect-window")
def collect_window(
    run_date: str = typer.Option(..., "--date", help="Run date in YYYY-MM-DD format."),
    window_index: int = typer.Option(..., min=0, help="Zero-based window index to collect."),
    total_windows: int = typer.Option(6, min=1, help="Total collection windows planned for the day."),
    max_credits_per_minute: int = typer.Option(8, min=1, help="Per-minute request budget."),
    dry_run: bool = typer.Option(False, help="Plan and execute the window without writing artifacts."),
    output_dir: Path = typer.Option(Path("output/intraday"), help="Root directory for intraday collection artifacts."),
    persist_oracle_sql: bool = typer.Option(False, "--persist-oracle-sql", help="Write successful collection results to Oracle SQL."),
) -> None:
    settings = get_settings(output_dir=output_dir, market_data_provider="twelve-data")
    if persist_oracle_sql:
        settings.oracle_sql_enabled = True
    collector = TwelveDataWindowCollector(settings=settings)
    try:
        result = collector.run_window(
            run_date=parse_run_date(run_date),
            output_root=settings.output_dir,
            window_index=window_index,
            total_windows=total_windows,
            max_credits_per_minute=max_credits_per_minute,
            dry_run=dry_run,
        )
    except AlertSidecarError as exc:
        typer.echo(f"Alert sidecar generation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Window: {result.plan.window_index + 1}/{result.plan.total_windows}")
    typer.echo(f"Planned tickers: {len(result.plan.window_tickers)}")
    typer.echo(f"Collected: {len(result.collected)}")
    typer.echo(f"Failures: {len(result.failures)}")
    typer.echo(f"Remaining after window: {len(result.plan.remaining_tickers)}")

    if dry_run:
        typer.echo("Artifacts skipped (--dry-run).")
        return

    collection_run_id = _persist_intraday_run_if_enabled(settings, result)
    typer.echo(f"Run directory: {result.artifacts.run_directory}")
    typer.echo(f"Metadata report: {result.artifacts.metadata_path}")
    typer.echo(f"Quotes report: {result.artifacts.quotes_path}")
    if result.artifacts.alert_events_path is not None:
        typer.echo(f"Provisional alert events: {result.artifacts.alert_events_path}")
    if result.artifacts.stable_alert_events_path is not None:
        typer.echo(f"Stable provisional alert entrypoint: {result.artifacts.stable_alert_events_path}")
    if collection_run_id is not None:
        typer.echo(f"Oracle SQL collection id: {collection_run_id}")


@app.command("init-oracle-schema")
def init_oracle_schema() -> None:
    settings = get_settings()
    settings.oracle_sql_enabled = True
    try:
        storage = OracleSqlStorage.from_settings(settings)
    except OracleSqlStorageError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if storage is None:
        typer.echo("Oracle SQL persistence is disabled.", err=True)
        raise typer.Exit(code=1)

    try:
        storage.initialize_schema()
    except OracleSqlStorageError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo("Oracle SQL schema initialized.")


@app.command()
def backtest(
    start_date: str = typer.Option(..., "--start-date", help="Inclusive start date in YYYY-MM-DD format."),
    end_date: str = typer.Option(..., "--end-date", help="Inclusive end date in YYYY-MM-DD format."),
    output_dir: Path = typer.Option(Path("output/backtests"), help="Directory for backtest artifacts."),
    horizons: str = typer.Option("5,10,20", help="Comma-separated forward return horizons in trading days."),
    dry_run: bool = typer.Option(False, help="Run the backtest without writing artifacts."),
) -> None:
    settings = get_settings(output_dir=output_dir)
    parsed_horizons = parse_horizons(horizons)
    summary, artifacts = HistoricalBacktestRunner(settings=settings).run(
        start_date=parse_run_date(start_date),
        end_date=parse_run_date(end_date),
        output_dir=settings.output_dir,
        forward_horizons=parsed_horizons,
        dry_run=dry_run,
    )

    typer.echo(f"Trading days: {summary['trading_day_count']}")
    typer.echo(f"Candidate observations: {summary['candidate_observation_count']}")
    typer.echo(f"Horizons: {', '.join(str(horizon) for horizon in parsed_horizons)}")
    if dry_run:
        typer.echo("Artifacts skipped (--dry-run).")
        return

    typer.echo(f"Summary report: {artifacts.summary_path}")
    typer.echo(f"Observation CSV: {artifacts.observations_path}")


@app.command()
def tune(
    start_date: str = typer.Option(..., "--start-date", help="Inclusive start date in YYYY-MM-DD format."),
    end_date: str = typer.Option(..., "--end-date", help="Inclusive end date in YYYY-MM-DD format."),
    output_dir: Path = typer.Option(Path("output/tuning"), help="Root directory for tuning artifacts."),
    forward_horizon: int = typer.Option(10, min=1, help="Forward return horizon in trading days for the objective function."),
    min_samples: int = typer.Option(5, min=1, help="Minimum buy-review samples required for a valid objective score."),
    horizons: str = typer.Option("5,10,20", help="Comma-separated forward return horizons to collect during backtest."),
    train_days: int = typer.Option(90, min=10, help="Walk-forward training window in trading days."),
    eval_days: int = typer.Option(20, min=5, help="Walk-forward evaluation window in trading days."),
    stride: int = typer.Option(20, min=1, help="Walk-forward stride in trading days."),
    min_wins: int = typer.Option(2, min=1, help="Minimum walk-forward window wins for a valid proposal."),
) -> None:
    """Grid-search tier thresholds using walk-forward backtest observations.

    Collects observations, runs walk-forward grid search (train/eval sliding
    windows), and writes proposal JSON + diff markdown + walkforward summary
    to output_dir/<end-date>/. Falls back to single-window when data is
    insufficient for walk-forward.
    """
    settings = get_settings(output_dir=output_dir)
    parsed_start = parse_run_date(start_date)
    parsed_end = parse_run_date(end_date)
    parsed_horizons = parse_horizons(horizons)

    typer.echo(f"Collecting backtest observations ({start_date} → {end_date})…")
    runner = HistoricalBacktestRunner(settings=settings)
    observations, data_failures, trading_day_count = runner.generate_observations(
        start_date=parsed_start,
        end_date=parsed_end,
        forward_horizons=parsed_horizons,
    )

    typer.echo(f"Trading days: {trading_day_count}  |  Observations: {len(observations)}")
    if data_failures:
        typer.echo(f"Data failures: {len(data_failures)}", err=True)
    if not observations:
        typer.echo("No observations — cannot run tuning.", err=True)
        raise typer.Exit(code=1)

    grid = TierThresholdsGrid()
    artifact_dir = ensure_directory(output_dir / parsed_end.isoformat())

    unique_dates = len({obs.run_date for obs in observations})
    enough_for_walkforward = unique_dates >= train_days + eval_days

    if enough_for_walkforward:
        typer.echo(
            f"Running walk-forward ({len(grid)} combinations, "
            f"train={train_days}d / eval={eval_days}d / stride={stride}d, "
            f"horizon=T+{forward_horizon})…"
        )
        wf_result = walk_forward(
            observations,
            horizon=forward_horizon,
            grid=grid,
            train_days=train_days,
            eval_days=eval_days,
            stride=stride,
            min_samples=min_samples,
            min_wins=min_wins,
        )

        wf_path = write_walkforward_json(artifact_dir / "tuning-walkforward.json", wf_result)
        proposal_path = write_proposal_json_from_walkforward(artifact_dir / "tuning-proposal.json", wf_result)
        diff_path = write_diff_markdown_from_walkforward(artifact_dir / "tuning-diff.md", wf_result)

        typer.echo(f"Walk-forward windows: {len(wf_result.windows)}")
        typer.echo(f"Walkforward JSON: {wf_path}")
        typer.echo(f"Proposal JSON:    {proposal_path}")
        typer.echo(f"Diff markdown:    {diff_path}")

        if wf_result.proposal is None:
            typer.echo(f"Result: no proposal — no combination won >= {min_wins} windows.")
        else:
            p = wf_result.proposal
            best_stability = next(s for s in wf_result.stability if s.thresholds == p)
            typer.echo(
                f"Proposal: min_score={p.min_score}  min_reversal={p.min_reversal}"
                f"  min_volume_ratio={p.min_volume_ratio}  max_risk_count={p.max_risk_count}"
            )
            typer.echo(
                f"  wins={best_stability.win_count}/{len(wf_result.windows)}"
                f"  avg_oos_excess_return={best_stability.avg_eval_excess_return}"
            )
    else:
        typer.echo(
            f"Not enough data for walk-forward (need {train_days + eval_days}+ trading days, "
            f"got {unique_dates}). Running single-window grid search…"
        )
        single_result = tune_single_window(
            observations, horizon=forward_horizon, grid=grid, min_samples=min_samples
        )
        grid_path = write_grid_csv(artifact_dir / "tuning-grid.csv", single_result)
        proposal_path = write_proposal_json(artifact_dir / "tuning-proposal.json", single_result)
        diff_path = write_diff_markdown(artifact_dir / "tuning-diff.md", single_result)

        typer.echo(f"Grid CSV:      {grid_path}")
        typer.echo(f"Proposal JSON: {proposal_path}")
        typer.echo(f"Diff markdown: {diff_path}")

        best = single_result.best
        if best is None:
            typer.echo("Result: no valid proposal (no combination met the min_samples threshold).")
        else:
            typer.echo(
                f"Best: min_score={best.thresholds.min_score}  min_reversal={best.thresholds.min_reversal}"
                f"  min_volume_ratio={best.thresholds.min_volume_ratio}  max_risk_count={best.thresholds.max_risk_count}"
            )
            typer.echo(f"  excess_return={best.excess_return:+.4f}%  sample_count={best.sample_count}")


def _persist_daily_run_if_enabled(settings: Settings, result: ScreenRunResult) -> str | None:
    try:
        storage = OracleSqlStorage.from_settings(settings)
    except OracleSqlStorageError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if storage is None:
        return None

    try:
        return storage.persist_daily_run(result)
    except OracleSqlStorageError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


def _persist_intraday_run_if_enabled(settings: Settings, result: CollectionResult) -> str | None:
    try:
        storage = OracleSqlStorage.from_settings(settings)
    except OracleSqlStorageError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if storage is None:
        return None

    try:
        return storage.persist_intraday_collection(result)
    except OracleSqlStorageError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


if __name__ == "__main__":
    app()
