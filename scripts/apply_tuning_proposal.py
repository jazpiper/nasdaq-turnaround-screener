#!/usr/bin/env python3
"""Apply a tuning-proposal.json to src/screener/scoring/tiering.py.

Usage (dry-run, default):
    uv run python scripts/apply_tuning_proposal.py output/tuning/2026-04-21/tuning-proposal.json

Usage (write + test):
    uv run python scripts/apply_tuning_proposal.py output/tuning/2026-04-21/tuning-proposal.json --write
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

TIERING_PATH_RELATIVE = "src/screener/scoring/tiering.py"

# Each entry: (constant_name, regex_pattern, format_func)
# The pattern matches the full assignment line (anchored at line start).
_CONSTANT_PATTERNS: list[tuple[str, str, str]] = [
    ("min_score",        r"^BUY_REVIEW_MIN_SCORE = \S+",        "BUY_REVIEW_MIN_SCORE = {value}"),
    ("min_reversal",     r"^BUY_REVIEW_MIN_REVERSAL = \S+",     "BUY_REVIEW_MIN_REVERSAL = {value}"),
    ("min_volume_ratio", r"^BUY_REVIEW_MIN_VOLUME_RATIO = \S+", "BUY_REVIEW_MIN_VOLUME_RATIO = {value}"),
    ("max_risk_count",   r"^BUY_REVIEW_MAX_RISK_COUNT = \S+",   "BUY_REVIEW_MAX_RISK_COUNT = {value}"),
]


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_proposal(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"ERROR: cannot load proposal: {exc}")

    if payload.get("status") != "proposal":
        sys.exit(
            f"ERROR: proposal status is '{payload.get('status')}', not 'proposal'. "
            "Nothing to apply."
        )
    if "proposed" not in payload:
        sys.exit("ERROR: proposal JSON has no 'proposed' key.")
    return payload


def parse_proposed(payload: dict) -> dict[str, int | float]:
    proposed = payload["proposed"]
    return {
        "min_score":        int(proposed["min_score"]),
        "min_reversal":     int(proposed["min_reversal"]),
        "min_volume_ratio": float(proposed["min_volume_ratio"]),
        "max_risk_count":   int(proposed["max_risk_count"]),
    }


def parse_current_from_file(tiering_path: Path) -> dict[str, int | float]:
    content = tiering_path.read_text(encoding="utf-8")
    result: dict[str, int | float] = {}
    for field_name, pattern, _ in _CONSTANT_PATTERNS:
        match = re.search(pattern, content, re.MULTILINE)
        if match is None:
            sys.exit(f"ERROR: pattern not found in tiering.py: {pattern!r}")
        # Extract the value part after "= "
        raw_value = match.group(0).split("=", 1)[1].strip()
        result[field_name] = float(raw_value) if "." in raw_value else int(raw_value)
    return result


def apply_to_content(content: str, proposed: dict[str, int | float]) -> str:
    """Replace the four constant lines and nothing else."""
    for field_name, pattern, template in _CONSTANT_PATTERNS:
        value = proposed[field_name]
        replacement = template.format(value=value)
        new_content, n = re.subn(pattern, replacement, content, flags=re.MULTILINE)
        if n != 1:
            sys.exit(
                f"ERROR: expected exactly 1 match for {pattern!r}, got {n}. "
                "Aborting to avoid corrupting tiering.py."
            )
        content = new_content
    return content


def print_diff(current: dict, proposed: dict) -> None:
    print("\nParameter diff:")
    print(f"  {'Parameter':<22}  {'Current':>10}  {'Proposed':>10}  {'Changed':>8}")
    print(f"  {'-'*22}  {'-'*10}  {'-'*10}  {'-'*8}")
    for key in ("min_score", "min_reversal", "min_volume_ratio", "max_risk_count"):
        cur = current[key]
        prop = proposed[key]
        changed = "YES" if cur != prop else "-"
        print(f"  {key:<22}  {str(cur):>10}  {str(prop):>10}  {changed:>8}")


def run_tests(root: Path) -> bool:
    result = subprocess.run(
        ["uv", "run", "--extra", "dev", "pytest", "-q"],
        cwd=root,
    )
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply a tuning proposal to tiering.py.")
    parser.add_argument("proposal", type=Path, help="Path to tuning-proposal.json.")
    parser.add_argument(
        "--write",
        action="store_true",
        default=False,
        help="Actually rewrite tiering.py and run pytest. Default is dry-run.",
    )
    args = parser.parse_args()

    root = project_root()
    tiering_path = root / TIERING_PATH_RELATIVE
    proposal_path = args.proposal if args.proposal.is_absolute() else Path.cwd() / args.proposal

    if not proposal_path.exists():
        sys.exit(f"ERROR: proposal file not found: {proposal_path}")
    if not tiering_path.exists():
        sys.exit(f"ERROR: tiering.py not found at expected path: {tiering_path}")

    payload = load_proposal(proposal_path)
    proposed = parse_proposed(payload)
    current = parse_current_from_file(tiering_path)

    print(f"Proposal: {proposal_path}")
    print(f"Target:   {tiering_path}")
    print(f"Source:   {payload.get('source', 'single_window')}")
    print(f"Horizon:  T+{payload.get('horizon', '?')}")
    print_diff(current, proposed)

    if not args.write:
        print("\nDry-run complete. Pass --write to apply changes and run pytest.")
        return 0

    if all(current[k] == proposed[k] for k in proposed):
        print("\nNo changes — proposed values match current. Nothing to write.")
        return 0

    original_content = tiering_path.read_text(encoding="utf-8")
    new_content = apply_to_content(original_content, proposed)

    print("\nWriting updated tiering.py…")
    tiering_path.write_text(new_content, encoding="utf-8")

    print("Running pytest…")
    tests_passed = run_tests(root)

    if tests_passed:
        print("\nAll tests passed. Changes applied successfully.")
        print(f"Next step: review the diff, then commit with:")
        print(f"  git add {TIERING_PATH_RELATIVE}")
        horizon = payload.get("horizon", "?")
        print(f"  git commit -m 'feat: apply tuning proposal (T+{horizon})'")
        return 0
    else:
        print("\nTests FAILED — restoring original tiering.py.")
        tiering_path.write_text(original_content, encoding="utf-8")
        print("tiering.py has been restored. No changes were kept.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
