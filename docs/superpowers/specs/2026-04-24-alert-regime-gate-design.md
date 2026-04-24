# Alert Regime Gate 설계 (2026-04-24)

## 배경 & 동기

2026-04-23 런에서 40건 후보 중 30건이 watchlist로 쏠리는 현상이 관측됨.
다운마켓 환경에서 alert 품질 게이트가 없어 watchlist가 과다 발송되는 문제를 해결한다.

관련 문서: `docs/improvements-2026-04-24.md` — #4 Alert 품질 게이트 강화

---

## 목표

QQQ 시장 regime을 기반으로 bearish 환경에서 watchlist 후보 수를 자동으로 제한한다.
buy-review 후보는 영향받지 않는다.

---

## 설계

### 발동 조건 (복합)

다음 두 조건을 **모두** 충족할 때 bearish regime으로 판단:

1. QQQ 종가가 20일 이동평균선 **아래**
2. QQQ 20일 수익률 < **-5%**

둘 중 하나만 해당하면 정상(pass) 동작. 데이터 누락 시에도 pass 기본값.

### 발동 효과

bearish regime 판정 시 digest에 포함되는 watchlist 후보를 상위 **3개**로 제한.
초과분은 suppressed 처리. buy-review 후보는 cap 대상 외.

---

## 컴포넌트 변경

| 파일 | 변경 내용 |
|------|----------|
| `src/screener/_pipeline/context.py` | `fetch_benchmark_context`에 `qqq_above_20d_ma: bool` 계산 추가 |
| `src/screener/alerts/policy.py` | `RegimeDecision` 데이터클래스 + `evaluate_regime_gate()` 함수 신설 |
| `src/screener/alerts/schema.py` | `AlertSummary`에 `regime_gate`, `regime_watchlist_cap` 필드 추가 |
| `src/screener/alerts/builder.py` | `benchmark_context` 파라미터 수용, regime cap 적용 |
| `src/screener/_pipeline/core.py` | `benchmark_context`를 builder 호출에 전달 |

---

## 데이터 흐름

```
fetch_benchmark_context()
  └─ 기존: qqq_return_20d, qqq_return_60d
  └─ 추가: qqq_above_20d_ma (bool)

evaluate_regime_gate(qqq_above_20d_ma, qqq_return_20d)
  → RegimeDecision(is_bearish, watchlist_cap)

build_daily_alert_document(... benchmark_context)
  └─ buy_review_members: cap 없음
  └─ watchlist_members: bearish 시 상위 3개로 제한
  └─ AlertSummary.regime_gate = "capped" | "pass"
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
    is_bearish: bool
    watchlist_cap: int | None

def evaluate_regime_gate(
    *,
    qqq_above_20d_ma: bool | None,
    qqq_return_20d: float | None,
) -> RegimeDecision:
    if qqq_above_20d_ma is None or qqq_return_20d is None:
        return RegimeDecision(is_bearish=False, watchlist_cap=None)
    bearish = (not qqq_above_20d_ma) and (qqq_return_20d < REGIME_QQQ_RETURN_THRESHOLD)
    return RegimeDecision(
        is_bearish=bearish,
        watchlist_cap=REGIME_WATCHLIST_CAP if bearish else None,
    )
```

### `builder.py` — cap 적용

```python
regime = evaluate_regime_gate(
    qqq_above_20d_ma=benchmark_context.get("qqq_above_20d_ma"),
    qqq_return_20d=benchmark_context.get("qqq_return_20d"),
)
watchlist_members = [m for m in digest_members if m["tier"] == WATCHLIST_TIER]
buy_review_members = [m for m in digest_members if m["tier"] == BUY_REVIEW_TIER]
if regime.watchlist_cap is not None:
    watchlist_members = watchlist_members[:regime.watchlist_cap]
digest_members = buy_review_members + watchlist_members
```

---

## 스키마 변경

```python
class AlertSummary(BaseModel):
    ...
    regime_gate: str = "pass"            # "pass" | "capped"
    regime_watchlist_cap: int | None = None
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
| `test_regime_gate_missing_data` | None 입력 → 안전 기본값 pass |
| `test_build_alert_caps_watchlist` | bearish 시 watchlist 3개 초과분 suppressed, buy-review 유지 |
| `test_build_alert_no_cap_in_normal_regime` | 정상 regime 시 watchlist 수 변화 없음 |
| `test_qqq_above_20d_ma_flag` | `fetch_benchmark_context`가 `qqq_above_20d_ma` 올바르게 반환 |

---

## 비고

- 이 설계는 **Regime 게이트만** 포함. 섹터 집중도 게이트, 상관 게이트는 별도 이슈.
- `benchmark_context`는 `build_daily_alert_document`의 선택 파라미터(`= None`)로 추가해 기존 호출 사이트 하위 호환 유지.
