# Alert Regime Gate 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** daily final alert에서 QQQ가 20일 MA 아래이고 20일 수익률이 -5% 미만일 때 digest watchlist 후보를 상위 3개로 제한한다.

**Architecture:** `fetch_benchmark_context`에 MA 플래그를 추가하고, `policy.py`에 `evaluate_regime_gate`를 신설한 뒤, `builder.py`가 결과를 소비해 digest를 cap한다. `core.py`가 daily final artifact 생성 시 `benchmark_context`를 builder에 전달하는 연결고리 역할을 한다. intraday provisional 경로는 이번 작업에서 cap을 적용하지 않고, benchmark context가 없을 때 `regime_gate="unknown"`으로 관측 가능하게 남긴다.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, uv

---

## 파일 변경 맵

| 파일 | 역할 |
|------|------|
| `src/screener/_pipeline/context.py` | `fetch_benchmark_context`에 `qqq_below_20d_ma` 추가 |
| `src/screener/alerts/policy.py` | `RegimeDecision` 데이터클래스 + `evaluate_regime_gate` 신설 |
| `src/screener/alerts/schema.py` | `AlertSummary`에 `regime_gate`, `regime_watchlist_cap`, `regime_gate_reason` 필드 추가 |
| `src/screener/alerts/builder.py` | `benchmark_context` 파라미터 수용, stable-order regime cap 적용, capped-out watchlist를 state/suppressed count에 반영 |
| `src/screener/_pipeline/core.py` | daily final `_write_artifacts`로 `benchmark_context` 전달 후 builder 호출에 전달 |
| `tests/test_pipeline.py` | `qqq_below_20d_ma` 단위 테스트 + integration 검증 |
| `tests/test_alert_policy.py` | `evaluate_regime_gate` 단위 테스트 3개 |
| `tests/test_alert_builder.py` | regime cap 적용 builder 테스트 2개 |

---

## Task 1: `qqq_below_20d_ma` 플래그 추가

**Files:**
- Modify: `src/screener/_pipeline/context.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_pipeline.py` 파일 끝에 아래 두 테스트를 추가한다.

```python
def test_fetch_benchmark_context_sets_above_ma_true_when_close_above_sma() -> None:
    from screener._pipeline.context import fetch_benchmark_context, BENCHMARK_TICKER
    from screener.models import PipelineContext
    from datetime import date, datetime
    import pandas as pd

    closes = [100.0] * 15 + [110.0] * 10  # 25 bars; last close=110, SMA-20=(100*10+110*10)/20=105
    rows = [
        {"date": date(2026, 1, 1 + i), "open": c, "high": c, "low": c, "close": c, "adj_close": c, "volume": 1e6}
        for i, c in enumerate(closes)
    ]
    df = pd.DataFrame(rows)

    class _StubProvider:
        def fetch_history(self, ticker, context):
            return df

    ctx = PipelineContext(run_date=date(2026, 1, 26), generated_at=datetime(2026, 1, 26, 20, 0))
    result = fetch_benchmark_context(_StubProvider(), ctx)

    assert result["qqq_above_20d_ma"] is True
    assert result["qqq_below_20d_ma"] is False


def test_fetch_benchmark_context_sets_above_ma_false_when_close_below_sma() -> None:
    from screener._pipeline.context import fetch_benchmark_context
    from screener.models import PipelineContext
    from datetime import date, datetime
    import pandas as pd

    closes = [110.0] * 15 + [100.0] * 10  # last close=100, SMA-20=(110*10+100*10)/20=105
    rows = [
        {"date": date(2026, 1, 1 + i), "open": c, "high": c, "low": c, "close": c, "adj_close": c, "volume": 1e6}
        for i, c in enumerate(closes)
    ]
    df = pd.DataFrame(rows)

    class _StubProvider:
        def fetch_history(self, ticker, context):
            return df

    ctx = PipelineContext(run_date=date(2026, 1, 26), generated_at=datetime(2026, 1, 26, 20, 0))
    result = fetch_benchmark_context(_StubProvider(), ctx)

    assert result["qqq_above_20d_ma"] is False
    assert result["qqq_below_20d_ma"] is True
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/test_pipeline.py::test_fetch_benchmark_context_sets_above_ma_true_when_close_above_sma tests/test_pipeline.py::test_fetch_benchmark_context_sets_above_ma_false_when_close_below_sma -v
```

예상: `KeyError: 'qqq_above_20d_ma'`

- [ ] **Step 3: `context.py` 구현**

`src/screener/_pipeline/context.py`의 `fetch_benchmark_context` 함수를 아래와 같이 수정한다.

```python
def fetch_benchmark_context(market_data_provider: MarketDataProvider, context: PipelineContext) -> dict[str, Any]:
    benchmark = TickerInput(ticker=BENCHMARK_TICKER)
    prepare = getattr(market_data_provider, "prepare", None)
    if callable(prepare):
        prepare([benchmark], context)
    history = market_data_provider.fetch_history(benchmark, context)
    closes = [float(value) for value in history.sort_values("date")["close"].tolist()]
    sma_20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
    qqq_above_20d_ma = (closes[-1] > sma_20) if (sma_20 is not None and closes) else None
    qqq_below_20d_ma = (closes[-1] < sma_20) if (sma_20 is not None and closes) else None
    return {
        "qqq_return_20d": _percent_return(closes, 20),
        "qqq_return_60d": _percent_return(closes, 60),
        "qqq_above_20d_ma": qqq_above_20d_ma,
        "qqq_below_20d_ma": qqq_below_20d_ma,
    }
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_pipeline.py::test_fetch_benchmark_context_sets_above_ma_true_when_close_above_sma tests/test_pipeline.py::test_fetch_benchmark_context_sets_above_ma_false_when_close_below_sma -v
```

예상: 2 passed

- [ ] **Step 5: 커밋**

```bash
git add src/screener/_pipeline/context.py tests/test_pipeline.py
git commit -m "feat: add qqq below 20d ma flag to fetch_benchmark_context"
```

---

## Task 2: `RegimeDecision` + `evaluate_regime_gate` 추가

**Files:**
- Modify: `src/screener/alerts/policy.py`
- Test: `tests/test_alert_policy.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_alert_policy.py` 상단 import에 아래를 추가한다.

```python
from screener.alerts.policy import evaluate_regime_gate
```

파일 끝에 아래 세 테스트를 추가한다.

```python
def test_evaluate_regime_gate_returns_pass_when_above_ma() -> None:
    decision = evaluate_regime_gate(qqq_below_20d_ma=False, qqq_return_20d=-8.0)

    assert decision.status == "pass"
    assert decision.is_bearish is False
    assert decision.watchlist_cap is None
    assert decision.reason == "conditions_not_met"


def test_evaluate_regime_gate_returns_capped_when_below_ma_and_return_below_threshold() -> None:
    decision = evaluate_regime_gate(qqq_below_20d_ma=True, qqq_return_20d=-6.0)

    assert decision.status == "capped"
    assert decision.is_bearish is True
    assert decision.watchlist_cap == 3
    assert decision.reason == "bearish_qqq_regime"


def test_evaluate_regime_gate_returns_unknown_on_missing_data() -> None:
    decision = evaluate_regime_gate(qqq_below_20d_ma=None, qqq_return_20d=None)

    assert decision.status == "unknown"
    assert decision.is_bearish is False
    assert decision.watchlist_cap is None
    assert decision.reason == "missing_benchmark_context"
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/test_alert_policy.py::test_evaluate_regime_gate_returns_pass_when_above_ma tests/test_alert_policy.py::test_evaluate_regime_gate_returns_capped_when_below_ma_and_return_below_threshold tests/test_alert_policy.py::test_evaluate_regime_gate_returns_unknown_on_missing_data -v
```

예상: `ImportError: cannot import name 'evaluate_regime_gate'`

- [ ] **Step 3: `policy.py` 구현**

`src/screener/alerts/policy.py` 파일 상단의 import 블록 다음에 아래를 추가한다. `from __future__ import annotations` 바로 아래, 기존 import들 아래에 `from dataclasses import dataclass`를 추가한다.

파일 최상단:
```python
from __future__ import annotations

from dataclasses import dataclass

from screener.models import CandidateResult, RunMetadata
from screener.scoring import AVOID_HIGH_RISK_TIER, BUY_REVIEW_TIER, WATCHLIST_TIER
```

`_EXTENDED_STATE_KEYS` 정의 아래(line 28 이후)에 아래 블록을 삽입한다.

```python
REGIME_QQQ_RETURN_THRESHOLD = -5.0
REGIME_WATCHLIST_CAP = 3


@dataclass(frozen=True)
class RegimeDecision:
    status: str
    is_bearish: bool
    watchlist_cap: int | None
    reason: str | None = None


def evaluate_regime_gate(
    *,
    qqq_below_20d_ma: bool | None,
    qqq_return_20d: float | None,
) -> RegimeDecision:
    if qqq_below_20d_ma is None or qqq_return_20d is None:
        return RegimeDecision(
            status="unknown",
            is_bearish=False,
            watchlist_cap=None,
            reason="missing_benchmark_context",
        )
    bearish = qqq_below_20d_ma and (qqq_return_20d < REGIME_QQQ_RETURN_THRESHOLD)
    return RegimeDecision(
        status="capped" if bearish else "pass",
        is_bearish=bearish,
        watchlist_cap=REGIME_WATCHLIST_CAP if bearish else None,
        reason="bearish_qqq_regime" if bearish else "conditions_not_met",
    )
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_alert_policy.py -v
```

예상: 전체 pass (신규 3개 포함)

- [ ] **Step 5: 커밋**

```bash
git add src/screener/alerts/policy.py tests/test_alert_policy.py
git commit -m "feat: add RegimeDecision and evaluate_regime_gate to policy"
```

---

## Task 3: `AlertSummary` 스키마 필드 추가

**Files:**
- Modify: `src/screener/alerts/schema.py`

- [ ] **Step 1: `schema.py` 수정**

`src/screener/alerts/schema.py`의 `AlertSummary` 클래스에 regime 필드 세 개를 추가한다.

```python
class AlertSummary(BaseModel):
    eligible_candidate_count: int
    individual_event_count: int
    digest_event_count: int
    suppressed_candidate_count: int
    quality_gate: str
    regime_gate: str = "unknown"
    regime_watchlist_cap: int | None = None
    regime_gate_reason: str | None = None
```

- [ ] **Step 2: 기존 테스트 전체 통과 확인**

```bash
uv run pytest tests/test_alert_builder.py tests/test_alert_policy.py tests/test_intraday_alerts.py -v
```

예상: 전체 pass (스키마 기본값이 있으므로 기존 테스트 영향 없음)

- [ ] **Step 3: 커밋**

```bash
git add src/screener/alerts/schema.py
git commit -m "feat: add regime gate fields to AlertSummary schema"
```

---

## Task 4: `builder.py`에 regime cap 적용

**Files:**
- Modify: `src/screener/alerts/builder.py`
- Test: `tests/test_alert_builder.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_alert_builder.py`에 watchlist 전용 후보 생성 헬퍼와 테스트 2개를 추가한다. bearish 테스트는 digest member 수뿐 아니라 capped-out watchlist가 alert state에서 빠지고 `suppressed_candidate_count`에 반영되는지 확인한다.

```python
def make_watchlist_candidate(*, ticker: str, score: int = 52) -> CandidateResult:
    from screener.scoring import WATCHLIST_TIER
    c = make_candidate(ticker=ticker, score=score)
    c = c.model_copy(update={"tier": WATCHLIST_TIER, "tier_reasons": ["score below buy-review threshold"]})
    return c


def test_build_daily_alert_caps_watchlist_in_bearish_regime() -> None:
    buy_review_digest = make_candidate(ticker="BR0", score=55)
    candidates = [
        make_watchlist_candidate(ticker="W00"),
        make_watchlist_candidate(ticker="W01"),
        buy_review_digest,
        make_watchlist_candidate(ticker="W02"),
        make_watchlist_candidate(ticker="W03"),
        make_watchlist_candidate(ticker="W04"),
        make_watchlist_candidate(ticker="W05"),
    ]
    result = make_result(candidates, bars_nonempty_count=95)
    bearish_context = {"qqq_below_20d_ma": True, "qqq_return_20d": -7.0}

    document, next_state = build_daily_alert_document(
        result,
        state=AlertState(),
        artifact_directory="output/daily/2026-04-22",
        report_path="output/daily/2026-04-22/daily-report.json",
        metadata_path="output/daily/2026-04-22/run-metadata.json",
        benchmark_context=bearish_context,
    )

    assert document.summary.regime_gate == "capped"
    assert document.summary.regime_watchlist_cap == 3
    assert document.summary.regime_gate_reason == "bearish_qqq_regime"
    assert document.summary.eligible_candidate_count == 4
    assert document.summary.suppressed_candidate_count == 3
    digest_events = [e for e in document.events if e.event_type == "digest_alert"]
    assert len(digest_events) == 1
    assert digest_events[0].payload["member_count"] == 4
    assert [member["ticker"] for member in digest_events[0].payload["members"]] == ["W00", "W01", "BR0", "W02"]
    assert set(next_state.tickers) == {"W00", "W01", "BR0", "W02"}


def test_build_daily_alert_does_not_cap_watchlist_in_normal_regime() -> None:
    candidates = [make_watchlist_candidate(ticker=f"T{i:02d}") for i in range(6)]
    result = make_result(candidates, bars_nonempty_count=95)
    normal_context = {"qqq_below_20d_ma": False, "qqq_return_20d": 1.0}

    document, next_state = build_daily_alert_document(
        result,
        state=AlertState(),
        artifact_directory="output/daily/2026-04-22",
        report_path="output/daily/2026-04-22/daily-report.json",
        metadata_path="output/daily/2026-04-22/run-metadata.json",
        benchmark_context=normal_context,
    )

    assert document.summary.regime_gate == "pass"
    assert document.summary.regime_watchlist_cap is None
    assert document.summary.suppressed_candidate_count == 0
    digest_events = [e for e in document.events if e.event_type == "digest_alert"]
    assert len(digest_events) == 1
    assert digest_events[0].payload["member_count"] == 6
    assert set(next_state.tickers) == {f"T{i:02d}" for i in range(6)}
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/test_alert_builder.py::test_build_daily_alert_caps_watchlist_in_bearish_regime tests/test_alert_builder.py::test_build_daily_alert_does_not_cap_watchlist_in_normal_regime -v
```

예상: `TypeError: build_daily_alert_document() got an unexpected keyword argument 'benchmark_context'`

- [ ] **Step 3: `builder.py` 수정**

`src/screener/alerts/builder.py` 파일 상단 import에 추가한다.

```python
from typing import Any

from screener.alerts.policy import (
    classify_candidate,
    determine_change_status,
    evaluate_daily_quality_gate,
    evaluate_intraday_quality_gate,
    evaluate_regime_gate,
    headline_reason,
    headline_risk,
    material_signature,
)
from screener.scoring import WATCHLIST_TIER
```

`build_daily_alert_document` 함수 시그니처를 변경한다.

```python
def build_daily_alert_document(
    result: ScreenRunResult,
    *,
    state: AlertState,
    artifact_directory: str,
    report_path: str,
    metadata_path: str,
    benchmark_context: dict[str, Any] | None = None,
) -> tuple[AlertDocument, AlertState]:
```

함수 본문 맨 앞(quality_gate 계산 바로 다음)에 regime 평가를 추가한다.

```python
    quality_gate = evaluate_daily_quality_gate(result.metadata)
    _bc = benchmark_context or {}
    regime = evaluate_regime_gate(
        qqq_below_20d_ma=_bc.get("qqq_below_20d_ma"),
        qqq_return_20d=_bc.get("qqq_return_20d"),
    )
    events: list[AlertEvent] = []
    next_tickers: dict[str, TickerAlertState] = {}
    digest_members: list[dict[str, object]] = []
```

`digest_members` 리스트를 완성한 뒤, `digest_state` 계산 전에 cap 로직을 삽입한다. 기존 digest 순서를 유지하고, capped-out watchlist ticker는 `next_tickers`에서 제거해 suppressed count와 state가 실제 발송 결과를 반영하게 한다.

기존:
```python
    digest_state: DigestAlertState | None = state.digest
    if digest_members:
```

변경 후:
```python
    capped_watchlist_tickers: set[str] = set()
    if regime.watchlist_cap is not None:
        kept_members: list[dict[str, object]] = []
        watchlist_seen = 0
        for member in digest_members:
            if member["tier"] != WATCHLIST_TIER:
                kept_members.append(member)
                continue
            watchlist_seen += 1
            if watchlist_seen <= regime.watchlist_cap:
                kept_members.append(member)
            else:
                capped_watchlist_tickers.add(str(member["ticker"]))
        digest_members = kept_members
        for ticker in capped_watchlist_tickers:
            next_tickers.pop(ticker, None)

    digest_state: DigestAlertState | None = state.digest
    if digest_members:
```

`AlertSummary` 생성 시 regime 필드를 채운다.

기존:
```python
        summary=AlertSummary(
            eligible_candidate_count=len(next_tickers),
            individual_event_count=len([event for event in emitted_events if event.event_type == "ticker_alert"]),
            digest_event_count=len([event for event in emitted_events if event.event_type == "digest_alert"]),
            suppressed_candidate_count=len(result.candidates) - len(next_tickers),
            quality_gate=quality_gate,
        ),
```

변경 후:
```python
        summary=AlertSummary(
            eligible_candidate_count=len(next_tickers),
            individual_event_count=len([event for event in emitted_events if event.event_type == "ticker_alert"]),
            digest_event_count=len([event for event in emitted_events if event.event_type == "digest_alert"]),
            suppressed_candidate_count=len(result.candidates) - len(next_tickers),
            quality_gate=quality_gate,
            regime_gate=regime.status,
            regime_watchlist_cap=regime.watchlist_cap,
            regime_gate_reason=regime.reason,
        ),
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_alert_builder.py -v
```

예상: 전체 pass

- [ ] **Step 5: 커밋**

```bash
git add src/screener/alerts/builder.py tests/test_alert_builder.py
git commit -m "feat: apply regime watchlist cap in build_daily_alert_document"
```

---

## Task 5: `core.py`에서 builder에 `benchmark_context` 전달

**Files:**
- Modify: `src/screener/_pipeline/core.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_pipeline.py` 끝에 아래 테스트를 추가한다. 이 테스트는 bearish QQQ 환경에서 파이프라인이 실행될 때 `alert-events.json`의 `summary.regime_gate`가 `"capped"`이고 digest watchlist cap이 실제 event/state/summary에 반영되는지 검증한다.

```python
def test_pipeline_passes_benchmark_context_to_alert_builder(tmp_path: Path) -> None:
    import json
    from datetime import date as dt_date

    from screener.models import CandidateResult, ScoreBreakdown
    from screener.scoring import WATCHLIST_TIER

    output_dir = tmp_path / "daily"
    run_date = dt_date(2026, 3, 31)
    tickers = [TickerInput(ticker=f"T{i:02d}") for i in range(100)]
    stock_history = make_history(start_close=180.0)

    class _LargeUniverseProvider:
        def load_universe(self, context):
            return tickers

    class _StubMarketDataProvider:
        def prepare(self, requested_tickers, context):
            return None

        def fetch_history(self, ticker, context):
            return stock_history

    class _StubBenchmarkProvider:
        def fetch_history(self, ticker, context):
            closes = [110.0] * 15 + [100.0] * 10
            rows = [
                {
                    "date": dt_date(2026, 3, 7) + timedelta(days=i),
                    "open": c,
                    "high": c,
                    "low": c,
                    "close": c,
                    "adj_close": c,
                    "volume": 2_000_000.0,
                }
                for i, c in enumerate(closes)
            ]
            return pd.DataFrame(rows)

    class _StubCandidateScorer:
        def evaluate(self, ticker, indicators, context):
            index = int(ticker.ticker.removeprefix("T"))
            if index >= 6:
                return None
            return CandidateResult(
                ticker=ticker.ticker,
                name=None,
                score=57 - index,
                subscores=ScoreBreakdown(oversold=18, bottom_context=14, reversal=12, volume=5, market_context=5),
                tier=WATCHLIST_TIER,
                tier_reasons=["score below buy-review threshold"],
                reasons=["BB 하단 근처 또는 재진입 구간", "5일선 회복 또는 회복 시도"],
                risks=["중기 추세는 아직 하락 압력일 수 있음"],
                indicator_snapshot={"earnings_penalty": 0, "volatility_penalty": 0},
                generated_at=context.generated_at,
            )

    class _EmptyEarningsProvider:
        def fetch(self, requested_tickers, run_date):
            return {}

    pipeline = ScreenPipeline(
        settings=Settings(output_dir=output_dir),
        universe_provider=_LargeUniverseProvider(),
        market_data_provider=_StubMarketDataProvider(),
        indicator_engine=TechnicalIndicatorEngine(),
        candidate_scorer=_StubCandidateScorer(),
        earnings_calendar_provider=_EmptyEarningsProvider(),
        benchmark_market_data_provider=_StubBenchmarkProvider(),
    )
    context = build_context(
        run_date=run_date,
        generated_at=datetime(2026, 3, 31, 20, 0, tzinfo=timezone.utc),
        output_dir=output_dir,
    )

    _, artifacts = pipeline.run(context)

    assert artifacts.stable_alert_events_path is not None
    payload = json.loads(artifacts.stable_alert_events_path.read_text(encoding="utf-8"))
    assert payload["summary"]["quality_gate"] == "pass"
    assert payload["summary"]["regime_gate"] == "capped"
    assert payload["summary"]["regime_watchlist_cap"] == 3
    assert payload["summary"]["suppressed_candidate_count"] == 3
    digest_events = [event for event in payload["events"] if event["event_type"] == "digest_alert"]
    assert len(digest_events) == 1
    assert digest_events[0]["payload"]["member_count"] == 3
    assert [member["ticker"] for member in digest_events[0]["payload"]["members"]] == ["T00", "T01", "T02"]
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/test_pipeline.py::test_pipeline_passes_benchmark_context_to_alert_builder -v
```

예상: assertion failure. Task 4까지 끝난 상태에서는 `regime_gate` 필드는 존재하지만, `_write_artifacts`가 `benchmark_context`를 전달하지 않아 `"unknown"` 또는 uncapped digest 결과가 나온다.

- [ ] **Step 3: `core.py` 수정**

`benchmark_context`는 `ScreenPipeline.run()`의 지역 변수이므로 `_write_artifacts()`에 명시적으로 넘겨야 한다. 먼저 `run()`의 artifact 호출을 수정한다.

기존:
```python
        if not context.dry_run:
            artifacts = self._write_artifacts(result, context.output_dir)
```

변경 후:
```python
        if not context.dry_run:
            artifacts = self._write_artifacts(result, context.output_dir, benchmark_context=benchmark_context)
```

그 다음 `_write_artifacts()` 시그니처를 수정한다.

기존:
```python
    def _write_artifacts(self, result: ScreenRunResult, output_dir: Path) -> RunArtifacts:
```

변경 후:
```python
    def _write_artifacts(
        self,
        result: ScreenRunResult,
        output_dir: Path,
        *,
        benchmark_context: dict[str, Any] | None = None,
    ) -> RunArtifacts:
```

마지막으로 `build_daily_alert_document` 호출에 `benchmark_context` 파라미터를 추가한다.

기존:
```python
            document, next_state = build_daily_alert_document(
                result,
                state=state,
                artifact_directory=str(output_dir),
                report_path=str(json_report_path),
                metadata_path=str(metadata_path),
            )
```

변경 후:
```python
            document, next_state = build_daily_alert_document(
                result,
                state=state,
                artifact_directory=str(output_dir),
                report_path=str(json_report_path),
                metadata_path=str(metadata_path),
                benchmark_context=benchmark_context,
            )
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_pipeline.py::test_pipeline_passes_benchmark_context_to_alert_builder -v
```

예상: 1 passed

- [ ] **Step 5: 전체 테스트 스위트 실행**

```bash
uv run pytest
```

예상: 전체 pass. 실패 시 에러 메시지를 확인해 원인을 수정한다.

- [ ] **Step 6: 커밋**

```bash
git add src/screener/_pipeline/core.py tests/test_pipeline.py
git commit -m "feat: pass benchmark_context to alert builder in pipeline core"
```

---

## 완료 기준

- `uv run pytest` 전체 통과
- `output/daily/latest/alert-events.json`의 `summary` 필드에 `regime_gate`, `regime_watchlist_cap`, `regime_gate_reason` 포함
- bearish 조건(QQQ MA 아래 + 20d return < -5%)에서 digest watchlist 후보가 3개 이하
- cap으로 제외된 watchlist 후보는 digest event와 next alert state에서 빠지고 `suppressed_candidate_count`에 반영
- benchmark data 누락 시 cap은 적용하지 않되 `regime_gate == "unknown"`으로 관측 가능
- buy-review 후보는 cap 영향 없음
