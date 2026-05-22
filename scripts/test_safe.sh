#!/usr/bin/env bash
set -uo pipefail

# venv/uv-aware pytest wrapper
# Usage:
#   scripts/test_safe.sh                  # run all tests
#   scripts/test_safe.sh tests/test_x.py  # target tests
#   scripts/test_safe.sh --dry-run ...    # print selected command only

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
  shift
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

PYTEST_ARGS=("$@")

detect_runner() {
  local py
  for py in \
    "$REPO_ROOT/.venv/bin/python" \
    "$REPO_ROOT/venv/bin/python" \
    "$REPO_ROOT/env/bin/python"
  do
    if [[ -x "$py" ]]; then
      if "$py" -c "import pytest" >/dev/null 2>&1; then
        RUNNER=("$py" -m pytest)
        RUNNER_REASON="local venv python + pytest"
        return 0
      fi
      FIRST_VENV_PY="$py"
    fi
  done

  if command -v uv >/dev/null 2>&1; then
    if [[ -f "$REPO_ROOT/uv.lock" || -f "$REPO_ROOT/pyproject.toml" ]]; then
      RUNNER=(uv run pytest)
      RUNNER_REASON="uv run pytest"
      return 0
    fi
  fi

  if command -v pytest >/dev/null 2>&1; then
    RUNNER=(pytest)
    RUNNER_REASON="pytest from PATH"
    return 0
  fi

  if command -v python3 >/dev/null 2>&1; then
    RUNNER=(python3 -m pytest)
    RUNNER_REASON="python3 -m pytest"
    return 0
  fi

  return 1
}

summarize_failure() {
  local log_file="$1"

  if grep -q "No module named pytest" "$log_file"; then
    echo "원인 요약: 선택된 Python 환경에 pytest가 설치되어 있지 않습니다."
    if [[ -n "${FIRST_VENV_PY:-}" ]]; then
      echo "권장 조치: $FIRST_VENV_PY -m pip install pytest 또는 uv sync --extra dev"
    else
      echo "권장 조치: venv 활성화 후 pytest 설치 또는 uv sync --extra dev"
    fi
    return
  fi

  if grep -q "command not found" "$log_file"; then
    echo "원인 요약: 테스트 실행 커맨드를 찾지 못했습니다(uv/pytest/python)."
    return
  fi

  if grep -q "ERROR: file or directory not found" "$log_file"; then
    echo "원인 요약: 지정한 테스트 경로가 잘못되었습니다."
    return
  fi

  if grep -q "ImportError\|ModuleNotFoundError" "$log_file"; then
    echo "원인 요약: 테스트 import 단계에서 모듈/의존성 로딩에 실패했습니다."
    return
  fi

  echo "원인 요약: pytest 실행 실패(아래 tail 참고)."
}

if ! detect_runner; then
  echo "[test_safe] FAIL: 실행 가능한 pytest 엔트리포인트를 찾지 못했습니다."
  echo "- 확인: .venv/venv/env, uv, pytest, python3"
  exit 127
fi

echo "[test_safe] repo       : $REPO_ROOT"
echo "[test_safe] runner     : ${RUNNER_REASON}"
echo "[test_safe] command    : ${RUNNER[*]} ${PYTEST_ARGS[*]}"

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[test_safe] dry-run only"
  exit 0
fi

LOG_FILE="$(mktemp)"
"${RUNNER[@]}" "${PYTEST_ARGS[@]}" 2>&1 | tee "$LOG_FILE"
RC=${PIPESTATUS[0]}

if [[ "$RC" -eq 0 ]]; then
  echo "[test_safe] result     : PASS"
  rm -f "$LOG_FILE"
  exit 0
fi

echo "[test_safe] result     : FAIL (exit=$RC)"
summarize_failure "$LOG_FILE"
echo "--- pytest tail (last 40 lines) ---"
tail -n 40 "$LOG_FILE"
rm -f "$LOG_FILE"
exit "$RC"
