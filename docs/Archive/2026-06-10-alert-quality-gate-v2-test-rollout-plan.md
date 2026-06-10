# Alert Quality Gate v2 테스트·롤아웃 계획 (2026-06-10)

## 목적

`docs/Archive/2026-06-10-alert-quality-gate-v2-options.md`의 Conservative gate와 Aggressive gate 중 하나를 향후 구현할 때 필요한 테스트 전략, 계약 검증, rollout/rollback 기준을 정리한다.

중요 원칙: production threshold 또는 gate 우선순위 변경은 사용자가 "alert noise 감소"와 "좋은 후보 누락 방지" 중 어느 쪽을 우선할지 결정하기 전에는 적용하지 않는다.

## 적용 범위

- 대상: daily final alert sidecar와 intraday provisional alert sidecar의 alert quality gate.
- 포함: market regime, sector concentration, candidate correlation, missing-signal handling, alert volume guardrail.
- 제외: sector/correlation producer 자체 구현, 신규 외부 데이터 계약, 실거래/주문 연동.

## 테스트 전략

### 1. Unit coverage

`tests/test_alert_policy.py`와 `tests/test_alert_builder.py`에 다음 케이스를 추가한다.

- market regime
  - confirmed bearish: `qqq_below_20d_ma is True` and `qqq_return_20d < -5.0`.
  - normal/pass: QQQ가 20일선 이상이거나 20일 수익률 하락폭이 threshold 이상이 아닌 경우.
  - missing benchmark context: Conservative는 fail-open, Aggressive는 defensive 또는 shadow-only로 검증.
- sector concentration
  - 동일 sector가 cap을 초과하는 fixture.
  - sector coverage가 acceptance threshold 미만인 fixture.
  - `sector`와 `gics_sector` alias가 모두 동작하는 fixture.
- candidate correlation
  - 동일 correlation group이 cap을 초과하는 fixture.
  - correlation coverage가 acceptance threshold 미만인 fixture.
  - `correlation_group`, `correlation_cluster`, `candidate_correlation_group` alias가 모두 동작하는 fixture.
- enforcement surface
  - Conservative: digest member만 cap 대상이고 single alert는 유지되는지 검증.
  - Aggressive: single alert와 digest member를 합산해 cap을 적용하는지 검증.
- state/dedupe interaction
  - cap으로 suppress된 후보가 alert state에 잘못 기록되지 않는지 검증.
  - unchanged final single이 digest-only로 내려가는 기존 동작을 깨지 않는지 검증.

### 2. Fixture/backtest coverage

실제 production threshold 변경 전, 최소 10개 이상의 최근 daily final snapshot 또는 고정 fixture를 사용해 shadow comparison을 만든다.

- baseline/current, Conservative, Aggressive 세 경로의 결과를 같은 입력으로 비교한다.
- 각 run마다 다음 값을 저장한다.
  - `eligible_candidate_count`
  - `individual_event_count`
  - `digest_event_count`
  - `suppressed_candidate_count`
  - `sector_coverage_ratio`
  - `correlation_coverage_ratio`
  - `regime_context_available`
  - top-N candidate retention ratio: baseline top 5와 top 10 중 유지된 후보 비율
- intraday provisional fixture는 benchmark context 누락 케이스를 반드시 포함한다.

### 3. Contract checks

OpenClaw-style consumer가 읽는 stable alert entrypoint 계약을 깨지 않는지 확인한다.

- `output/daily/latest/alert-events.json`
- `output/intraday/<NY_DATE>/latest-alert-events.json`

검증 항목:

- 기존 required fields는 삭제하지 않는다.
- 신규 summary field는 optional/additive로 추가한다.
- 신규 gate status 값은 문서화하고 schema/Pydantic validation을 통과한다.
- `quality_gate`, `regime_gate`, `regime_gate_reason`, `regime_watchlist_cap` 기존 의미가 바뀌면 migration note를 남긴다.
- stable entrypoint와 dated artifact가 같은 alert sidecar schema를 유지한다.

### 4. Operational dry-run

production threshold 변경 전 아래를 한 번 이상 실행한다.

- targeted tests: `uv run pytest tests/test_alert_policy.py tests/test_alert_builder.py -q`
- affected runner/contract tests: `uv run pytest tests/test_cli.py tests/test_run_daily.py -q`
- daily dry-run or fixture replay: 실제 credential이 필요 없는 범위에서 dated output과 latest pointer 생성을 확인한다.

## Acceptance criteria: Conservative gate

Conservative option은 false negative 최소화를 우선한다. production 적용 전 아래 조건을 모두 만족해야 한다.

- Regime behavior
  - confirmed bearish daily final에서만 강화 gate가 suppress를 수행한다.
  - `benchmark_context`가 missing이면 `regime_gate="unknown"` 또는 동등 상태를 기록하고 fail-open한다.
  - intraday provisional은 benchmark context 연결 전까지 production suppress를 늘리지 않는다.
- Sector/correlation coverage
  - eligible candidate 중 sector coverage가 80% 미만이면 sector cap은 suppress하지 않고 `insufficient_signal` 또는 동등 telemetry만 남긴다.
  - eligible candidate 중 correlation coverage가 80% 미만이면 correlation cap은 suppress하지 않고 `insufficient_signal` 또는 동등 telemetry만 남긴다.
- Enforcement surface
  - concentration cap은 digest member에만 적용한다.
  - single ticker alert는 sector/correlation cap 때문에 suppress되지 않는다.
- Alert volume guardrail
  - 최근 fixture/shadow run 기준 전체 emitted alert count 감소가 baseline 대비 20%를 초과하지 않는다.
  - baseline top 5 candidate retention이 90% 이상이어야 한다.
- Contract
  - alert sidecar schema 변경은 additive이며 기존 consumer required field를 제거하지 않는다.

## Acceptance criteria: Aggressive gate

Aggressive option은 crowded exposure 감소를 우선한다. production 적용 전 아래 조건을 모두 만족해야 한다.

- Explicit user decision
  - 사용자가 좋은 후보 누락 리스크를 감수하고 concentration/noise 감소를 우선한다고 명시적으로 결정해야 한다.
- Signal readiness
  - sector coverage가 최근 fixture/shadow run 기준 90% 이상이어야 한다.
  - correlation coverage가 최근 fixture/shadow run 기준 90% 이상이어야 한다.
  - intraday provisional에 benchmark context가 전달되거나, intraday에서는 Aggressive suppress를 shadow-only로 둔다.
- Enforcement surface
  - single alert와 digest member를 합산해 sector/correlation cap을 적용한다.
  - missing sector/correlation은 unknown bucket으로 묶되, unknown bucket suppress 수를 별도 telemetry로 기록한다.
- Alert volume guardrail
  - 최근 fixture/shadow run 기준 전체 emitted alert count 감소가 baseline 대비 45%를 초과하지 않는다.
  - baseline top 5 candidate retention이 80% 이상이어야 한다.
  - single alert 감소율이 baseline 대비 35%를 초과하면 production 적용을 보류한다.
- Contract
  - 신규 defensive/unknown bucket status가 schema와 downstream contract에 명시되어야 한다.

## Rollout plan

1. Shadow mode first
   - current policy output은 그대로 유지한다.
   - Conservative와 Aggressive 결과를 sidecar summary 또는 별도 diagnostic artifact에 shadow metrics로 기록한다.
   - 최소 5 trading days 또는 10 fixture runs 이상 비교한다.
2. Conservative guarded rollout
   - 사용자 결정이 "후보 누락 방지 우선"이면 Conservative를 production candidate로 둔다.
   - 처음에는 daily final에만 적용하고 intraday provisional은 shadow-only로 유지한다.
   - alert count delta와 top-N retention을 매일 확인한다.
3. Aggressive staged rollout
   - 사용자 결정이 "alert noise/concentration 감소 우선"이고 signal readiness 기준을 만족할 때만 진행한다.
   - 먼저 daily final shadow -> daily final guarded production -> intraday shadow 순서로 진행한다.
   - intraday production 적용은 benchmark context coverage가 안정화된 뒤 별도 승인으로 분리한다.

## Rollback criteria

다음 조건 중 하나라도 발생하면 production threshold/gate 변경을 즉시 이전 정책으로 되돌린다.

- Conservative
  - emitted alert count가 baseline 또는 최근 10-run median 대비 20% 초과 감소.
  - baseline top 5 candidate retention이 90% 미만.
  - sector/correlation coverage 부족인데 suppress가 발생.
  - single alert가 concentration cap 때문에 suppress됨.
- Aggressive
  - emitted alert count가 baseline 또는 최근 10-run median 대비 45% 초과 감소.
  - single alert count가 baseline 대비 35% 초과 감소.
  - baseline top 5 candidate retention이 80% 미만.
  - unknown bucket 때문에 suppressed candidate의 50% 이상이 묶임.
  - intraday provisional에서 benchmark context missing 상태로 production suppress가 늘어남.
- 공통
  - alert sidecar schema validation 실패.
  - stable alert entrypoint 생성 실패.
  - downstream consumer가 신규 status를 처리하지 못함.
  - 사용자에게 전달되는 daily/intraday 후보 수가 운영 기대치보다 현저히 낮아짐.

Rollback 방법은 feature flag 또는 config threshold를 이전 값으로 되돌리고, 같은 입력 fixture로 baseline contract tests를 다시 통과시키는 것이다.

## Rollout risk section for follow-up ticket

- Main decision risk: noise 감소와 후보 누락 방지 중 무엇을 우선할지 사용자 결정이 필요하다. 결정 전 production threshold 변경 금지.
- Data readiness risk: sector/correlation metadata가 main snapshot path에서 안정적으로 채워지지 않으면 Aggressive gate는 unknown bucket suppress를 과도하게 만들 수 있다.
- Intraday risk: provisional path가 benchmark context를 받지 못하는 동안 unknown/defensive regime 처리는 intraday alert under-delivery를 만들 수 있다.
- Contract risk: 신규 gate status와 summary field는 additive로만 추가해야 하며 stable alert entrypoint 소비자가 깨지면 즉시 rollback한다.
- Monitoring risk: alert volume, single alert count, top-N retention, unknown bucket suppress share를 매 run 저장하지 않으면 under-delivery를 늦게 발견한다.
- Recommended default: Conservative를 먼저 shadow/guarded rollout하고, Aggressive는 signal coverage 90%+와 사용자 우선순위 결정 이후 별도 staged rollout로 다룬다.
