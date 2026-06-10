# Alert Quality Gate v2 옵션 비교 (2026-06-10)

## 목적

현재 alert builder/fixture 인벤토리를 기준으로, v2 alert quality gate에 넣을 수 있는 두 가지 정책 옵션을 정리한다.
이 문서는 follow-up implementation card로 바로 쪼갤 수 있도록 정책 동작, 누락 신호 의존성, 예상 alert volume 변화를 명시한다.

## 현재 상태 요약

- market regime
  - `evaluate_regime_gate()`는 QQQ 종가가 20일선 아래이고 `qqq_return_20d < -5%`일 때만 bearish로 판정한다.
  - bearish가 아니거나 `benchmark_context`가 없으면 regime cap은 적용되지 않는다.
  - intraday provisional 경로는 현재 `benchmark_context`를 builder에 넘기지 않아 regime이 사실상 `unknown`이다.
- sector concentration
  - builder는 `sector` / `gics_sector`를 읽을 수 있지만, 기본 pipeline snapshot 생산 경로에서 이 값이 항상 보장되지는 않는다.
  - 현재 fixture는 수동 주입으로만 sector cap 동작을 검증한다.
- candidate correlation
  - builder는 `correlation_group` / `correlation_cluster` / `candidate_correlation_group`를 읽을 수 있지만, 기본 pipeline snapshot 생산 경로에서 이 값이 항상 보장되지는 않는다.
  - 현재 fixture는 수동 주입으로만 correlation cap 동작을 검증한다.
- current cap constants in code
  - bearish watchlist cap: 3
  - bearish sector cap: 2
  - bearish correlation-group cap: 2
- current enforcement surface
  - sector/correlation cap은 bearish일 때만 적용된다.
  - cap은 rank 순서로 적용되며, single ticker alert와 digest member를 함께 본다.
  - 누락된 sector/correlation 값은 cap 계산에서 제외된다.

## 설계 원칙

- v2는 "alert noise 감소"와 "좋은 후보 누락 방지" 사이의 trade-off를 명시적으로 택해야 한다.
- 현재 inventory 기준으로 regime은 daily final에서만 신뢰 가능하고, sector/correlation은 production coverage가 불완전하다.
- 그래서 핵심 차이는 다음 세 가지다.
  1. regime이 `unknown`일 때 fail-open으로 둘지, defensive mode로 둘지
  2. sector/correlation 신호 coverage가 낮을 때 gate를 건너뛸지, unknown bucket으로 묶어 제한할지
  3. single alert까지 concentration gate 대상에 넣을지, digest 위주로 제한할지

## 옵션 비교

| 항목 | Conservative gate | Aggressive gate |
|---|---|---|
| 목표 | false positive/alert flood만 줄이고 false negative는 최소화 | crowded exposure를 적극 줄이고 누락 리스크보다 concentration 리스크를 우선 |
| market regime | confirmed bearish에서만 강화. `unknown`이면 fail-open | confirmed bearish면 가장 강하게 적용. `unknown`도 defensive mode로 간주 |
| watchlist cap | bearish일 때만 3개 cap 유지 | bearish 2개, regime `unknown`도 3개 cap |
| sector concentration | digest 멤버에만 sector cap 2 적용. single alert는 유지 | single + digest 전체에 sector cap 적용. bearish/unknown에서 cap 1, normal에서 cap 2 |
| candidate correlation | digest 멤버에만 correlation cap 2 적용. single alert는 유지 | single + digest 전체에 correlation cap 적용. bearish/unknown에서 cap 1, normal에서 cap 2 |
| missing sector/correlation signal | coverage 부족 시 해당 gate skip + telemetry only | missing 값을 `unknown` bucket으로 묶어 cap 적용 |
| missing regime signal | regime=`unknown`, concentration gate 비활성 | regime=`unknown`이면 defensive caps 활성 |
| 예상 alert volume | 현재 대비 소폭 감소 | 현재 대비 뚜렷한 감소 |
| 예상 candidate exposure | 같은 테마/섹터 반복 노출은 일부 남음 | crowded theme 반복 노출이 강하게 줄어듦 |
| 주요 리스크 | noisy run에서는 충분히 못 줄일 수 있음 | 신호 누락 run에서 좋은 후보를 과하게 누를 수 있음 |

## Option A: Conservative gate

### intended behavior

1. market regime
   - `qqq_below_20d_ma is True` AND `qqq_return_20d < -5.0`일 때만 bearish mode.
   - 그 외 `pass`.
   - `benchmark_context`가 없으면 `unknown`으로 기록하되 fail-open.

2. sector concentration
   - bearish mode에서만 적용.
   - 대상은 digest member만 포함한다.
   - 동일 sector 내 최대 2개까지 유지한다.
   - single ticker alert는 suppress하지 않는다.
   - sector coverage가 eligible candidate의 80% 미만이면 sector gate를 실행하지 않고 `sector_concentration_gate="insufficient_signal"`로 기록한다.

3. candidate correlation
   - bearish mode에서만 적용.
   - 대상은 digest member만 포함한다.
   - 동일 correlation group 내 최대 2개까지 유지한다.
   - single ticker alert는 suppress하지 않는다.
   - correlation coverage가 eligible candidate의 80% 미만이면 correlation gate를 실행하지 않고 `correlation_gate="insufficient_signal"`로 기록한다.

### dependencies on missing signals

- daily final에서만 regime 신뢰 가능. intraday provisional은 별도 `benchmark_context` 전달 전까지 fail-open 유지.
- `sector`/`gics_sector`, `correlation_group` alias들이 snapshot에 안정적으로 실리지 않으면 해당 gate는 suppress보다 telemetry 역할이 커진다.
- 따라서 이 옵션의 선행 카드 1순위는 "coverage 측정 + schema/status 확장"이다.

### expected impact

- alert volume
  - bearish daily final digest에서만 완만하게 감소.
  - single alert 건수는 거의 유지.
  - regime `unknown` run에서는 현행과 거의 동일.
- candidate exposure
  - digest에서 동일 sector/group 과밀은 줄지만, single alert 단계의 crowded exposure는 남는다.
  - 좋은 상위 conviction name을 놓칠 확률은 낮다.

### implementation notes

- 현재 builder의 `_apply_context_cap()`를 digest-only 대상으로 분리하는 follow-up이 필요하다.
- `AlertSummary` gate status enum에 `insufficient_signal`을 추가해야 한다.
- coverage 계산용 카운터를 summary에 추가하는 것이 바람직하다.

## Option B: Aggressive gate

### intended behavior

1. market regime
   - confirmed bearish면 strongest caps 적용.
   - `benchmark_context`가 없으면 fail-open하지 않고 `unknown_defensive`로 취급한다.
   - normal regime에서도 완전 해제하지 않고 light cap을 유지한다.

2. sector concentration
   - single ticker alert와 digest member를 합산해 적용한다.
   - bearish 또는 `unknown_defensive`: 동일 sector 최대 1개.
   - normal regime: 동일 sector 최대 2개.
   - sector 값이 없으면 `unknown-sector` bucket으로 묶고 동일 bucket cap을 적용한다.

3. candidate correlation
   - single ticker alert와 digest member를 합산해 적용한다.
   - bearish 또는 `unknown_defensive`: 동일 correlation group 최대 1개.
   - normal regime: 동일 group 최대 2개.
   - correlation 값이 없으면 `unknown-correlation` bucket으로 묶고 동일 bucket cap을 적용한다.

4. watchlist cap
   - bearish: watchlist 최대 2개.
   - `unknown_defensive`: watchlist 최대 3개.
   - normal: watchlist cap 없음.

### dependencies on missing signals

- 이 옵션은 missing signal을 사실상 "리스크"로 해석한다.
- 그래서 sector/correlation enrichment가 안정화되지 않으면 `unknown-*` bucket이 과대해져 suppress가 급격히 늘 수 있다.
- intraday provisional에 benchmark_context가 계속 없으면 defensive mode가 자주 발동해 intraday alert volume이 크게 줄어든다.

### expected impact

- alert volume
  - bearish run뿐 아니라 regime `unknown` run에서도 눈에 띄게 감소.
  - single alert도 줄어들 수 있다.
  - intraday provisional volume이 가장 크게 줄 가능성이 높다.
- candidate exposure
  - 동일 테마/섹터 반복 노출은 크게 줄어든다.
  - 반면 metadata enrichment가 약한 날에는 상위 후보가 과도하게 밀릴 수 있다.

### implementation notes

- `_apply_context_cap()`는 unknown bucket 처리와 regime별 동적 cap을 지원하도록 리팩터링해야 한다.
- `AlertSummary`에 `unknown_defensive` 같은 상태를 추가하거나, `regime_gate_reason`에 defensive fallback 사유를 남겨야 한다.
- production snapshot coverage가 올라오기 전까지는 false negative 분석용 fixture/backtest 카드가 필수다.

## 권장 순서

1. 먼저 Conservative gate를 구현해 production coverage telemetry를 확보한다.
2. sector/correlation snapshot coverage가 안정적으로 90%+가 확인되면 Aggressive gate를 A/B 또는 backtest shadow mode로 검증한다.
3. intraday provisional에 `benchmark_context`가 연결되기 전에는 Aggressive gate를 기본값으로 두지 않는다.

## follow-up implementation cards

1. Add signal coverage telemetry to alert summary
   - sector/correlation populated candidate counts
   - regime context availability
   - gate status extensions: `insufficient_signal`, optional `unknown_defensive`
2. Split context caps by enforcement surface
   - digest-only path for Conservative
   - single+digest unified path for Aggressive
3. Stabilize snapshot inputs
   - ensure `sector`/`gics_sector` and correlation aliases are emitted on the main pipeline path
4. Extend test fixtures
   - partial coverage cases
   - unknown bucket behavior
   - intraday `benchmark_context` missing cases
5. Add shadow/backtest comparison
   - compare alert count deltas
   - compare top-rank candidate retention under both options

## bottom line

- Conservative gate는 현재 inventory의 한계를 인정하고, 확실한 bearish daily final에서만 noise를 줄이는 방안이다.
- Aggressive gate는 concentration risk를 더 강하게 제어하지만, 지금 상태의 missing signal/intraday unknown regime에서는 suppress 과잉 가능성이 높다.
- 현 시점 기본안으로는 Conservative가 더 안전하고, Aggressive는 signal coverage 보강 이후 2단계 옵션으로 두는 편이 맞다.
