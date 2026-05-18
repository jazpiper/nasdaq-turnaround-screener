from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import typer

from screener.alerts import AlertSidecarError
from screener.backtest import HistoricalBacktestRunner
from screener.collector import CollectionResult, TwelveDataWindowCollector
from screener.config import Settings, get_settings
from screener.models import ScreenRunResult
from screener.pipeline import ScreenPipeline, build_context
from screener.reporting.assistant_briefing import (
    build_assistant_briefing_markdown,
    build_assistant_briefing_payload,
    load_daily_report,
    parse_user_tickers,
    write_assistant_briefing,
)
from screener.reporting.overlay_universe_report import (
    DEFAULT_ARTIFACT_BASENAME as DEFAULT_OVERLAY_REPORT_BASENAME,
    DEFAULT_BACKTEST_SUMMARY_PATH as DEFAULT_OVERLAY_BACKTEST_SUMMARY_PATH,
    DEFAULT_BASELINE_DAILY_REPORT_PATH,
    DEFAULT_OVERLAY_DAILY_REPORT_PATH,
    DEFAULT_OVERLAY_METADATA_PATH,
    DEFAULT_REPORT_OUTPUT_DIR,
    load_and_build_overlay_universe_report,
    write_overlay_universe_report,
)
from screener.reporting.performance_dashboard import (
    DEFAULT_BACKTEST_SUMMARY_PATH,
    DEFAULT_DASHBOARD_OUTPUT_DIR,
    DEFAULT_TUNING_PROPOSAL_PATH,
    DEFAULT_TUNING_WALKFORWARD_PATH,
    build_performance_dashboard_markdown,
    build_performance_dashboard_payload,
    load_json_artifact,
    write_performance_dashboard,
)
from screener.storage import OracleSqlStorage, OracleSqlStorageError
from screener.storage.files import ensure_directory
from screener.tuning import TierThresholdsGrid, tune_single_window, walk_forward
from screener.universe import USER_WATCHLIST_UNIVERSE_NAME, load_ticker_source_file, parse_ticker_list
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
    universe_name: str | None = typer.Option(None, "--universe-name", help="Name to record for a custom ticker universe. Defaults to user-watchlist when --tickers is provided."),
    universe_tickers: str | None = typer.Option(None, "--tickers", "--universe-tickers", help="Comma-separated tickers for a custom screener universe."),
    overlay_tickers: str | None = typer.Option(None, "--overlay-tickers", help="Comma-separated hot-sector overlay tickers to append to the core universe."),
    overlay_file: Path | None = typer.Option(None, "--overlay-file", help="File containing overlay tickers as JSON, CSV, or newline-separated text."),
    overlay_name: str | None = typer.Option(None, "--overlay-name", help="Label used when naming outputs for an overlay-backed universe."),
) -> None:
    settings = get_settings(output_dir=output_dir)
    overlay_ticker_values: tuple[str, ...] | None = None
    if universe_tickers is not None:
        try:
            settings.universe_tickers = parse_ticker_list(universe_tickers)
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--tickers") from exc
        settings.universe_name = (universe_name or USER_WATCHLIST_UNIVERSE_NAME).strip() or USER_WATCHLIST_UNIVERSE_NAME
    elif universe_name is not None:
        raise typer.BadParameter(
            "--universe-name requires --tickers/--universe-tickers.",
            param_hint="--universe-name",
        )

    if overlay_tickers is not None:
        try:
            overlay_ticker_values = parse_ticker_list(overlay_tickers)
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--overlay-tickers") from exc
    if overlay_file is not None:
        try:
            overlay_ticker_values = load_ticker_source_file(overlay_file)
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc), param_hint="--overlay-file") from exc
    if overlay_ticker_values is not None:
        settings.universe_overlay_tickers = overlay_ticker_values
        settings.universe_overlay_source = overlay_file
        settings.universe_overlay_name = (overlay_name or (overlay_file.stem if overlay_file is not None else "hot-sector-overlay")).strip() or "hot-sector-overlay"
        base_name = (universe_name or settings.universe_name).strip() or settings.universe_name
        settings.universe_name = f"{base_name}+{settings.universe_overlay_name}"
    if use_staged_intraday:
        settings.daily_intraday_source_mode = "prefer-staged"
    if intraday_output_root is not None:
        settings.intraday_output_root = intraday_output_root
    if persist_oracle_sql:
        settings.oracle_sql_enabled = True
    oracle_storage = _prepare_oracle_storage_if_enabled(settings) if settings.oracle_sql_enabled and not dry_run else None
    context = build_context(run_date=parse_run_date(run_date), dry_run=dry_run, output_dir=settings.output_dir, run_mode=settings.default_run_mode, universe_name=settings.universe_name)
    try:
        result, artifacts = ScreenPipeline(settings=settings).run(context)
    except AlertSidecarError as exc:
        typer.echo(f"Alert sidecar generation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Run date: {result.metadata.run_date.isoformat()}")
    typer.echo(f"Run universe: {result.metadata.universe}")
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

    run_id = _persist_daily_run_if_enabled(settings, result, storage=oracle_storage)
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
    oracle_storage = _prepare_oracle_storage_if_enabled(settings) if settings.oracle_sql_enabled and not dry_run else None
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

    collection_run_id = _persist_intraday_run_if_enabled(settings, result, storage=oracle_storage)
    typer.echo(f"Run directory: {result.artifacts.run_directory}")
    typer.echo(f"Metadata report: {result.artifacts.metadata_path}")
    typer.echo(f"Quotes report: {result.artifacts.quotes_path}")
    if result.artifacts.alert_events_path is not None:
        typer.echo(f"Provisional alert events: {result.artifacts.alert_events_path}")
    if result.artifacts.stable_alert_events_path is not None:
        typer.echo(f"Stable provisional alert entrypoint: {result.artifacts.stable_alert_events_path}")
    if collection_run_id is not None:
        typer.echo(f"Oracle SQL collection id: {collection_run_id}")


@app.command("build-assistant-briefing")
def build_assistant_briefing(
    report_path: Path = typer.Option(
        Path("output/daily/latest/daily-report.json"),
        "--report-path",
        help="Source daily-report.json path.",
    ),
    output_dir: Path = typer.Option(
        Path("output/assistant"),
        "--output-dir",
        help="Directory for compact assistant briefing artifacts.",
    ),
    user_tickers: str = typer.Option(
        "TSLA,INFQ,PLTR,RKLB,GOOGL,NVDA",
        "--user-tickers",
        help="Comma-separated user holdings/watchlist tickers to summarize.",
    ),
    top_candidates: int = typer.Option(
        10,
        "--top-candidates",
        min=0,
        help="Number of top screener candidates to include.",
    ),
    artifact_basename: str | None = typer.Option(
        None,
        "--artifact-basename",
        help="Optional basename for output artifacts; writes <basename>.json and <basename>.md.",
    ),
    dry_run: bool = typer.Option(False, help="Build the briefing without writing artifacts."),
) -> None:
    try:
        daily_report = load_daily_report(report_path)
    except FileNotFoundError as exc:
        typer.echo(f"Daily report not found: {report_path}", err=True)
        raise typer.Exit(code=1) from exc
    except json.JSONDecodeError as exc:
        typer.echo(f"Daily report is not valid JSON: {report_path}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except OSError as exc:
        typer.echo(f"Daily report could not be read: {report_path}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    payload = build_assistant_briefing_payload(
        daily_report,
        user_tickers=parse_user_tickers(user_tickers),
        top_candidate_count=top_candidates,
        generated_at=datetime.now(timezone.utc),
        source_report_path=report_path,
    )
    markdown = build_assistant_briefing_markdown(payload)

    typer.echo(f"Source daily report: {report_path}")
    typer.echo(f"User tickers: {', '.join(item['ticker'] for item in payload['user_tickers'])}")
    typer.echo(f"Top candidates included: {len(payload['top_candidates'])}")
    if dry_run:
        typer.echo("Artifacts skipped (--dry-run).")
        return

    try:
        json_path, markdown_path = write_assistant_briefing(
            payload,
            markdown,
            output_dir,
            artifact_basename=artifact_basename,
        )
    except ValueError as exc:
        typer.echo(f"Invalid artifact basename: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"Assistant briefing JSON: {json_path}")
    typer.echo(f"Assistant briefing markdown: {markdown_path}")


@app.command("performance-dashboard")
def performance_dashboard(
    backtest_summary_path: Path = typer.Option(
        DEFAULT_BACKTEST_SUMMARY_PATH,
        "--backtest-summary-path",
        help="Source backtest summary JSON artifact.",
    ),
    tuning_proposal_path: Path = typer.Option(
        DEFAULT_TUNING_PROPOSAL_PATH,
        "--tuning-proposal-path",
        help="Optional tuning proposal JSON artifact.",
    ),
    tuning_walkforward_path: Path = typer.Option(
        DEFAULT_TUNING_WALKFORWARD_PATH,
        "--tuning-walkforward-path",
        help="Optional walk-forward tuning JSON artifact.",
    ),
    output_dir: Path = typer.Option(
        DEFAULT_DASHBOARD_OUTPUT_DIR,
        "--output-dir",
        help="Directory for dashboard artifacts.",
    ),
    dry_run: bool = typer.Option(False, help="Build the dashboard without writing artifacts."),
) -> None:
    try:
        backtest_summary = load_json_artifact(backtest_summary_path, required=True)
    except FileNotFoundError as exc:
        typer.echo(f"Backtest summary not found: {backtest_summary_path}", err=True)
        raise typer.Exit(code=1) from exc
    except json.JSONDecodeError as exc:
        typer.echo(f"Backtest summary is not valid JSON: {backtest_summary_path}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except OSError as exc:
        typer.echo(f"Backtest summary could not be read: {backtest_summary_path}: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    try:
        tuning_proposal = load_json_artifact(tuning_proposal_path)
        tuning_walkforward = load_json_artifact(tuning_walkforward_path)
    except json.JSONDecodeError as exc:
        typer.echo(f"Tuning artifact is not valid JSON: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except OSError as exc:
        typer.echo(f"Tuning artifact could not be read: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if backtest_summary is None:
        typer.echo(f"Backtest summary not found: {backtest_summary_path}", err=True)
        raise typer.Exit(code=1)

    payload = build_performance_dashboard_payload(
        backtest_summary,
        generated_at=datetime.now(timezone.utc),
        backtest_summary_path=backtest_summary_path,
        tuning_proposal=tuning_proposal,
        tuning_walkforward=tuning_walkforward,
        tuning_proposal_path=tuning_proposal_path,
        tuning_walkforward_path=tuning_walkforward_path,
        output_dir=output_dir,
    )
    markdown = build_performance_dashboard_markdown(payload)

    typer.echo(f"Backtest summary: {backtest_summary_path}")
    typer.echo(f"Trading days: {payload['backtest'].get('trading_day_count', 'n/a')}")
    typer.echo(f"Candidate observations: {payload['backtest'].get('candidate_observation_count', 'n/a')}")
    typer.echo(f"Tuning status: {payload['tuning'].get('status', 'missing')}")
    if dry_run:
        typer.echo("Artifacts skipped (--dry-run).")
        return

    json_path, markdown_path = write_performance_dashboard(payload, markdown, output_dir)
    typer.echo(f"Dashboard JSON: {json_path}")
    typer.echo(f"Dashboard markdown: {markdown_path}")


@app.command("overlay-universe-report")
def overlay_universe_report(
    baseline_report_path: Path = typer.Option(
        DEFAULT_BASELINE_DAILY_REPORT_PATH,
        "--baseline-report-path",
        help="Source baseline daily-report.json artifact.",
    ),
    overlay_report_path: Path = typer.Option(
        DEFAULT_OVERLAY_DAILY_REPORT_PATH,
        "--overlay-report-path",
        help="Source overlay-backed daily-report.json artifact.",
    ),
    overlay_metadata_path: Path = typer.Option(
        DEFAULT_OVERLAY_METADATA_PATH,
        "--overlay-metadata-path",
        help="Source hot-sector overlay metadata artifact.",
    ),
    backtest_summary_path: Path = typer.Option(
        DEFAULT_OVERLAY_BACKTEST_SUMMARY_PATH,
        "--backtest-summary-path",
        help="Optional backtest summary JSON artifact.",
    ),
    output_dir: Path = typer.Option(
        DEFAULT_REPORT_OUTPUT_DIR,
        "--output-dir",
        help="Directory for overlay comparison artifacts.",
    ),
    dry_run: bool = typer.Option(False, help="Build the report without writing artifacts."),
) -> None:
    try:
        payload, markdown = load_and_build_overlay_universe_report(
            baseline_report_path=baseline_report_path,
            overlay_report_path=overlay_report_path,
            overlay_metadata_path=overlay_metadata_path,
            backtest_summary_path=backtest_summary_path,
            output_dir=output_dir,
            generated_at=datetime.now(timezone.utc),
        )
    except FileNotFoundError as exc:
        message = str(exc)
        missing_path = baseline_report_path
        if str(overlay_report_path) in message:
            missing_path = overlay_report_path
        elif str(overlay_metadata_path) in message:
            missing_path = overlay_metadata_path
        elif backtest_summary_path is not None and str(backtest_summary_path) in message:
            missing_path = backtest_summary_path
        typer.echo(f"Overlay report source not found: {missing_path}", err=True)
        raise typer.Exit(code=1) from exc
    except json.JSONDecodeError as exc:
        typer.echo(f"Overlay report source is not valid JSON: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except OSError as exc:
        typer.echo(f"Overlay report source could not be read: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    comparison = payload["comparison"]
    deltas = comparison["deltas"]
    typer.echo(f"Baseline report: {baseline_report_path}")
    typer.echo(f"Overlay report: {overlay_report_path}")
    typer.echo(
        "Comparison: "
        f"planned={comparison['baseline'].get('planned_ticker_count', 'n/a')}→{comparison['overlay'].get('planned_ticker_count', 'n/a')} "
        f"({deltas.get('planned_ticker_count', 'n/a')}), "
        f"candidates={comparison['baseline'].get('candidate_count', 'n/a')}→{comparison['overlay'].get('candidate_count', 'n/a')} "
        f"({deltas.get('candidate_count', 'n/a')})"
    )
    typer.echo(f"Overlay sectors: {', '.join(payload['overlay'].get('selected_sectors', [])) or 'n/a'}")
    typer.echo(f"Overlay tickers: {', '.join(payload['overlay'].get('tickers', [])) or 'n/a'}")
    if dry_run:
        typer.echo("Artifacts skipped (--dry-run).")
        return

    json_path, markdown_path = write_overlay_universe_report(
        payload,
        markdown,
        output_dir,
        artifact_basename=DEFAULT_OVERLAY_REPORT_BASENAME,
    )
    typer.echo(f"Overlay report JSON: {json_path}")
    typer.echo(f"Overlay report markdown: {markdown_path}")


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
    if forward_horizon not in parsed_horizons:
        collected = ", ".join(str(horizon) for horizon in parsed_horizons)
        typer.echo(
            f"Forward horizon T+{forward_horizon} is not included in --horizons ({collected}).",
            err=True,
        )
        raise typer.Exit(code=2)

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


def _prepare_oracle_storage_if_enabled(settings: Settings) -> OracleSqlStorage | None:
    try:
        storage = OracleSqlStorage.from_settings(settings)
        if storage is not None:
            preflight = getattr(storage, "preflight", None)
            if callable(preflight):
                preflight()
    except OracleSqlStorageError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    return storage


def _persist_daily_run_if_enabled(
    settings: Settings,
    result: ScreenRunResult,
    *,
    storage: Any | None = None,
) -> str | None:
    if storage is None:
        storage = _prepare_oracle_storage_if_enabled(settings)

    if storage is None:
        return None

    try:
        return storage.persist_daily_run(result)
    except OracleSqlStorageError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


def _persist_intraday_run_if_enabled(
    settings: Settings,
    result: CollectionResult,
    *,
    storage: Any | None = None,
) -> str | None:
    if storage is None:
        storage = _prepare_oracle_storage_if_enabled(settings)

    if storage is None:
        return None

    try:
        return storage.persist_intraday_collection(result)
    except OracleSqlStorageError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


if __name__ == "__main__":
    app()
