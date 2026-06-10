# Alert Quality Gate v2 사용자 결정용 후속 스펙 (2026-06-10)

## 결론

구현은 사용자 우선순위 선택 전까지 보류한다.

권장 다음 단계는 Conservative gate를 먼저 shadow/guarded rollout 후보로 준비하는 것이다. 현재 inventory 기준으로 daily final의 market regime만 비교적 신뢰 가능하고, sector/correlation 및 intraday benchmark context는 coverage gap이 남아 있다. 따라서 곧바로 production threshold를 바꾸기보다, 두 옵션을 같은 입력에서 shadow comparison으로 비교하고 alert volume, single alert 감소율, top-N retention, missing-signal suppress를 먼저 계측한다.

## 사용자가 선택해야 할 정책 우선순위

질문: v2 alert quality gate의 기본 우선순위를 무엇으로 둘 것인가?

1. 좋은 후보 누락 방지 우선
   - 기본 선택: Conservative gate
   - 목표: false negative를 최소화하면서 confirmed bearish daily final에서만 alert noise를 완만하게 줄인다.
   - 적합한 경우: 사용자가 alert 수가 다소 많더라도 상위 후보를 놓치지 않는 것을 더 중요하게 볼 때.

2. alert noise / crowded exposure 감소 우선
   - 기본 선택: Aggressive gate
   - 목표: 같은 sector/theme/correlation group 반복 노출을 강하게 줄인다.
   - 적합한 경우: 사용자가 일부 좋은 후보 누락 가능성을 감수하고서라도 과밀·중복 alert를 크게 줄이고 싶을 때.

## 옵션 A: Conservative gate

### 동작 요약

- market regime
  - QQQ가 20일선 아래이고 20일 수익률이 -5% 미만인 confirmed bearish daily final에서만 강화 gate를 적용한다.
  - benchmark context가 없으면 regime을 unknown으로 기록하되 fail-open한다.
- sector concentration
  - bearish mode에서 digest member에만 sector cap 2를 적용한다.
  - single ticker alert는 sector cap으로 suppress하지 않는다.
  - sector coverage가 eligible candidate의 80% 미만이면 suppress하지 않고 insufficient_signal telemetry만 남긴다.
- candidate correlation
  - bearish mode에서 digest member에만 correlation cap 2를 적용한다.
  - single ticker alert는 correlation cap으로 suppress하지 않는다.
  - correlation coverage가 80% 미만이면 suppress하지 않고 insufficient_signal telemetry만 남긴다.

### 기대 효과

- alert volume은 bearish daily final digest 중심으로 소폭 감소한다.
- single alert와 baseline top 후보 보존 가능성이 높다.
- missing signal이 많은 run에서는 현행과 거의 비슷하게 동작할 수 있다.

### 주요 리스크

- noisy run에서 noise 감소 효과가 충분하지 않을 수 있다.
- single alert 단계의 crowded exposure는 일부 남는다.

### production 적용 전 조건

- shadow/fixture 기준 전체 emitted alert count 감소가 baseline 대비 20%를 넘지 않을 것.
- baseline top 5 candidate retention이 90% 이상일 것.
- sector/correlation coverage 부족 상태에서는 suppress가 발생하지 않을 것.
- alert sidecar schema 변경은 additive일 것.

## 옵션 B: Aggressive gate

### 동작 요약

- market regime
  - confirmed bearish면 가장 강한 cap을 적용한다.
  - benchmark context가 없으면 unknown_defensive로 취급하거나, 최소한 shadow-only로 먼저 검증한다.
- sector concentration
  - single ticker alert와 digest member를 합산해 cap을 적용한다.
  - bearish/unknown에서는 동일 sector 최대 1개, normal에서는 최대 2개를 유지한다.
  - missing sector는 unknown-sector bucket으로 묶고 별도 telemetry를 남긴다.
- candidate correlation
  - single ticker alert와 digest member를 합산해 cap을 적용한다.
  - bearish/unknown에서는 동일 group 최대 1개, normal에서는 최대 2개를 유지한다.
  - missing correlation은 unknown-correlation bucket으로 묶고 별도 telemetry를 남긴다.

### 기대 효과

- alert volume과 crowded theme 반복 노출이 뚜렷하게 줄어든다.
- intraday provisional처럼 benchmark context가 빠진 경로에서는 alert 감소 폭이 특히 커질 수 있다.

### 주요 리스크

- sector/correlation enrichment가 불완전하면 unknown bucket suppress가 과해질 수 있다.
- 좋은 상위 후보가 single alert 단계에서 사라질 수 있다.
- intraday benchmark context 연결 전 production 적용은 under-delivery 리스크가 크다.

### production 적용 전 조건

- 사용자가 noise/concentration 감소를 우선한다고 명시적으로 선택할 것.
- sector와 correlation coverage가 shadow/fixture 기준 90% 이상일 것.
- intraday benchmark context가 연결되거나 intraday Aggressive suppress는 shadow-only로 둘 것.
- 전체 emitted alert count 감소가 baseline 대비 45%를 넘지 않을 것.
- single alert 감소율이 baseline 대비 35%를 넘으면 production 적용을 보류할 것.
- baseline top 5 candidate retention이 80% 이상일 것.

## 공통 선행 작업

두 옵션 모두 production threshold 변경 전 다음이 필요하다.

1. Shadow metrics 추가
   - baseline/current, Conservative, Aggressive를 같은 입력에서 비교한다.
   - 저장 지표: eligible candidate count, individual/digest event count, suppressed count, sector/correlation coverage ratio, regime context availability, top-5/top-10 retention.
2. Alert summary telemetry 확장
   - sector/correlation populated counts.
   - regime context availability.
   - insufficient_signal, unknown_defensive 등 신규 상태는 optional/additive로 추가한다.
3. Contract 검증
   - `output/daily/latest/alert-events.json`와 `output/intraday/<NY_DATE>/latest-alert-events.json`의 기존 required field를 제거하지 않는다.
   - 신규 field/status는 schema와 downstream consumer compatibility를 확인한다.
4. Rollback 기준 유지
   - alert under-delivery, top-N retention 하락, schema/entrypoint regression, downstream consumer failure가 있으면 즉시 이전 정책으로 되돌린다.

## 결정 후 필요한 child cards

사용자 선택 전에는 아래 구현 카드를 실행하지 않는다. 선택 후 해당 경로만 unblock/생성한다.

### Conservative 선택 시

1. Implement Conservative alert quality gate shadow metrics
   - 담당: coder
   - 범위: alert summary telemetry, insufficient_signal status, digest-only cap fixture, baseline vs Conservative comparison.
   - 검증: `uv run pytest tests/test_alert_policy.py tests/test_alert_builder.py -q`와 stable entrypoint contract check.

2. Conservative guarded rollout readiness check
   - 담당: coder 또는 default+coder 협업
   - 범위: 최근 fixture 또는 dry-run 10회 이상에서 20% alert-count guardrail, top-5 retention 90%+, additive schema 확인.
   - 결과: production 적용 여부를 사용자에게 다시 보고하고 승인 전까지 threshold 변경 보류.

### Aggressive 선택 시

1. Stabilize alert gate input coverage
   - 담당: coder
   - 범위: main snapshot path에서 sector/gics_sector, correlation_group aliases, intraday benchmark_context coverage를 보강 또는 coverage telemetry로 명확히 분리.
   - 검증: coverage ratio 90%+가 shadow/fixture에서 확인되어야 함.

2. Implement Aggressive gate in shadow/backtest mode
   - 담당: coder
   - 범위: unknown bucket, single+digest unified cap, unknown_defensive status, top-N retention and single-alert drop guardrails.
   - 검증: alert count delta <=45%, single alert drop <=35%, top-5 retention >=80%, schema additive compatibility.

## ready-to-share 사용자 메시지 초안

Alert Quality Gate v2는 지금 바로 구현하기보다, 먼저 정책 우선순위를 선택해야 합니다. 선택지는 두 가지입니다.

1. 좋은 후보 누락 방지 우선: Conservative gate
   - confirmed bearish daily final에서만 완만하게 alert noise를 줄입니다.
   - benchmark/sector/correlation 신호가 부족하면 fail-open 또는 telemetry-only로 두어 좋은 후보 누락을 줄입니다.
   - 현재 데이터 준비 상태를 고려하면 기본 권장안입니다.

2. alert noise와 중복 노출 감소 우선: Aggressive gate
   - single alert와 digest 모두에 sector/correlation cap을 강하게 적용합니다.
   - alert 수는 더 줄어들 수 있지만, sector/correlation coverage가 불완전하거나 intraday benchmark context가 없으면 좋은 후보가 과하게 suppress될 수 있습니다.
   - coverage 90%+와 shadow/backtest 검증 후 단계적으로 적용하는 편이 안전합니다.

제 추천은 Conservative를 먼저 shadow/guarded rollout 후보로 준비하고, Aggressive는 signal coverage와 shadow 지표가 충분해진 뒤 2단계로 검토하는 것입니다. 구현은 사용자가 “좋은 후보 누락 방지”와 “alert noise/concentration 감소” 중 어느 쪽을 우선할지 선택하기 전까지 보류해야 합니다.
