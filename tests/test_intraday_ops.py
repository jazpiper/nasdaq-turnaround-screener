from __future__ import annotations

from pathlib import Path

import pytest

from screener.intraday_ops import (
    DEFAULT_INTRADAY_WINDOW_IDS,
    IntradayPlan,
    build_collector_command,
    intraday_output_dir,
    parse_window_ids,
)


def test_parse_window_ids_uses_default_when_value_missing() -> None:
    assert parse_window_ids(None) == DEFAULT_INTRADAY_WINDOW_IDS


def test_parse_window_ids_normalizes_values() -> None:
    assert parse_window_ids(" Open-1, MIDDAY-2 ,power-hour-1 ") == (
        "open-1",
        "midday-2",
        "power-hour-1",
    )


@pytest.mark.parametrize("value", ["", " , "])
def test_parse_window_ids_rejects_empty_lists(value: str) -> None:
    with pytest.raises(ValueError):
        parse_window_ids(value)


def test_intraday_plan_validates_known_window() -> None:
    plan = IntradayPlan(window_ids=("open-1", "midday-1"))

    assert plan.validate_window_id(" MIDDAY-1 ") == "midday-1"



def test_intraday_plan_rejects_unknown_window() -> None:
    plan = IntradayPlan(window_ids=("open-1", "midday-1"))

    with pytest.raises(ValueError, match="Unknown window id"):
        plan.validate_window_id("close-1")



def test_intraday_output_dir_nests_date_and_window() -> None:
    assert intraday_output_dir(Path("output/intraday"), "2026-04-21", "Open-1") == Path(
        "output/intraday/2026-04-21/open-1"
    )



def test_build_collector_command_expands_placeholders() -> None:
    command = build_collector_command(
        command_template="{python} -m demo.collect --date {date} --window-id {window_id} --window-index {window_index} --output-dir {output_dir} --output-root {output_root} --root {project_root}",
        python_path=Path("/tmp/project/.venv/bin/python"),
        run_date="2026-04-21",
        window_id="Open-1",
        window_index=0,
        output_dir=Path("/tmp/project/output/intraday/2026-04-21/open-1"),
        output_root=Path("/tmp/project/output/intraday"),
        project_root=Path("/tmp/project"),
    )

    assert command == [
        "/tmp/project/.venv/bin/python",
        "-m",
        "demo.collect",
        "--date",
        "2026-04-21",
        "--window-id",
        "open-1",
        "--window-index",
        "0",
        "--output-dir",
        "/tmp/project/output/intraday/2026-04-21/open-1",
        "--output-root",
        "/tmp/project/output/intraday",
        "--root",
        "/tmp/project",
    ]
