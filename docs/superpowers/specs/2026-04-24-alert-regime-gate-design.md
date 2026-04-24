# Alert Regime Gate 설계 (2026-04-24)

## 배경 & 동기

2026-04-23 런에서 40건 후보 중 30건이 watchlist로 쏠리는 현상이 관측됨.
다운마켓 환경에서 alert 품질 게이트가 없어 watchlist가 과다 발송되는 문제를 해결한다.

관련 문서: `docs/improvements-2026-04-24.md` — #4 Alert 품질 게이트 강화

---

## 목표

daily final alert sidecar에서 QQQ 시장 regime을 기반으로 bearish 환경의 watchlist 후보 수를 자동으로 제한한다.
buy-review 후보는 영향받지 않는다.

이번 변경은 daily final 경로를 우선 대상으로 한다. intraday provisional alert는 `benchmark_context` 전달 경로가 별도로 정리될 때까지 permissive 동작을 유지하고, regime 상태는 `unknown`으로 관측 가능하게 남긴다.

---

## 설계

### 발동 조건 (복합)

다음 두 조건을 **모두** 충족할 때 bearish regime으로 판단:

1. QQQ 종가가 20일 이동평균선 **아래**
2. QQQ 20일 수익률 < **-5%**

둘 중 하나만 해당하면 정상(`pass`) 동작.
데이터 누락 시에는 cap을 적용하지 않지만, 정상 regime으로 오인하지 않도록 `unknown`으로 기록한다.

### 발동 효과

bearish regime 판정 시 digest에 포함되는 watchlist 후보를 상위 **3개**로 제한.
초과분은 suppressed 처리한다. 즉 digest event에서 제외하고, 다음 alert state에도 저장하지 않으며, `suppressed_candidate_count`에 반영한다.
buy-review 후보는 cap 대상 외다.

---

## 컴포넌트 변경

| 파일 | 변경 내용 |
|------|----------|
| `src/screener/_pipeline/context.py` | `fetch_benchmark_context`에 `qqq_above_20d_ma: bool` 계산 추가 |
| `src/screener/alerts/policy.py` | `RegimeDecision` 데이터클래스 + `evaluate_regime_gate()` 함수 신설 |
| `src/screener/alerts/schema.py` | `AlertSummary`에 `regime_gate`, `regime_watchlist_cap`, `regime_gate_reason` 필드 추가 |
| `src/screener/alerts/builder.py` | `benchmark_context` 파라미터 수용, stable-order regime cap 적용, capped-out watchlist를 state/suppressed count에 반영 |
| `src/screener/_pipeline/core.py` | daily final artifact 생성 시 `benchmark_context`를 builder 호출에 전달 |

---

## 데이터 흐름

```
fetch_benchmark_context()
  └─ 기존: qqq_return_20d, qqq_return_60d
  └─ 추가: qqq_above_20d_ma (bool)

evaluate_regime_gate(qqq_above_20d_ma, qqq_return_20d)
  → RegimeDecision(status, is_bearish, watchlist_cap, reason)

build_daily_alert_document(... benchmark_context)
  └─ buy_review_members: cap 없음
  └─ watchlist_members: bearish 시 기존 rank 순서 기준 상위 3개로 제한
  └─ capped-out watchlist: digest 제외 + next state 제외 + suppressed count 반영
  └─ AlertSummary.regime_gate = "capped" | "pass" | "unknown"
```

---

## 핵심 로직

### `context.py` — MA 계산

```python
sma_20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
qqq_above_20d_ma = (closes[-1] > sma_20) if sma_20 is not None else None
```

`technicals.py`의 `rolling_mean` 유틸 재사용 가능.

### `policy.py` — RegimeDecision

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
    qqq_above_20d_ma: bool | None,
    qqq_return_20d: float | None,
) -> RegimeDecision:
    if qqq_above_20d_ma is None or qqq_return_20d is None:
        return RegimeDecision(
            status="unknown",
            is_bearish=False,
            watchlist_cap=None,
            reason="missing_benchmark_context",
        )
    bearish = (not qqq_above_20d_ma) and (qqq_return_20d < REGIME_QQQ_RETURN_THRESHOLD)
    return RegimeDecision(
        status="capped" if bearish else "pass",
        is_bearish=bearish,
        watchlist_cap=REGIME_WATCHLIST_CAP if bearish else None,
        reason="bearish_qqq_regime" if bearish else "conditions_not_met",
    )
```

### `builder.py` — cap 적용

```python
regime = evaluate_regime_gate(
    qqq_above_20d_ma=benchmark_context.get("qqq_above_20d_ma"),
    qqq_return_20d=benchmark_context.get("qqq_return_20d"),
)
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
```

이 필터는 기존 `digest_members` 순서를 유지한다. buy-review digest 후보와 cap 안에 남은 watchlist 후보의 상대 순서를 재배열하지 않는다.

---

## 스키마 변경

```python
class AlertSummary(BaseModel):
    ...
    regime_gate: str = "unknown"         # "pass" | "capped" | "unknown"
    regime_watchlist_cap: int | None = None
    regime_gate_reason: str | None = None
```

---

## 상수 (튜닝 가능)

| 상수 | 값 | 위치 |
|------|-----|------|
| `REGIME_QQQ_RETURN_THRESHOLD` | `-5.0` | `alerts/policy.py` |
| `REGIME_WATCHLIST_CAP` | `3` | `alerts/policy.py` |

추후 튜닝 루프(1번 개선 성과물)에서 grid search 대상으로 편입 가능.

---

## 테스트 계획

| 테스트 | 검증 내용 |
|--------|----------|
| `test_regime_gate_pass` | MA 위 or return > -5% → `is_bearish=False`, cap=None |
| `test_regime_gate_capped` | MA 아래 AND return < -5% → `is_bearish=True`, cap=3 |
| `test_regime_gate_missing_data` | None 입력 → cap 없음, `status="unknown"` |
| `test_build_alert_caps_watchlist` | bearish 시 watchlist 3개 초과분 digest/state 제외, suppressed count 반영, buy-review 유지, 기존 digest 순서 유지 |
| `test_build_alert_no_cap_in_normal_regime` | 정상 regime 시 watchlist 수 변화 없음 |
| `test_qqq_above_20d_ma_flag` | `fetch_benchmark_context`가 `qqq_above_20d_ma` 올바르게 반환 |
| `test_pipeline_passes_benchmark_context_to_alert_builder` | daily final pipeline에서 bearish context가 summary와 digest cap에 반영 |

---

## 비고

- 이 설계는 **Regime 게이트만** 포함. 섹터 집중도 게이트, 상관 게이트는 별도 이슈.
- `benchmark_context`는 `build_daily_alert_document`의 선택 파라미터(`= None`)로 추가해 기존 호출 사이트 하위 호환 유지.
- intraday provisional 경로에 regime cap을 적용하려면 `collector.py`/provisional screening 경로까지 benchmark context 전달을 확장하는 별도 작업이 필요하다.
