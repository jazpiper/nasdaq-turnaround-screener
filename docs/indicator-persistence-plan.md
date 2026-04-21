# Indicator Persistence Plan

## 목적
현재 스크리너는 후보를 고를 때 여러 indicator와 context를 사용하지만, Oracle SQL에는 일부 결과만 저장합니다.

지금 문서의 목적은 아래를 분리해서 정의하는 것입니다.

1. **설명 가능성 / 디버깅 / 운영 추적**을 위해 무엇을 저장할지
2. **백테스트 / 모델 개선**을 위해 무엇이 추가로 필요할지
3. Oracle SQL에 어떤 형태로 붙이는 것이 가장 덜 과하고, 확장 가능성이 높은지

---

## 현재 상태

### 이미 Oracle SQL에 저장되는 것
- `screen_runs`
- `screen_candidates`
- `candidate_subscores`
- `intraday_collection_runs`
- `intraday_collection_quotes`

### 현재 candidate 단위 저장 필드
- `ticker`
- `score`
- `close_price`
- `lower_bb`
- `rsi14`
- `distance_to_20d_low`
- `reasons_json`
- `risks_json`
- factor subscores

### 현재 런타임에서 계산하지만 DB에 안 남는 주요 값
- `sma_5`
- `sma_20`
- `sma_60`
- `average_volume_20d`
- `volume_ratio_20d`
- `close_improvement_streak`
- `rsi_3d_change`
- `weekly_sma_5`
- `weekly_sma_10`
- `weekly_trend_penalty`
- `weekly_trend_severe_damage`
- 향후 추가 후보: `atr_pct`, earnings proximity, regime context

---

## 문제 정의
지금 구조는 **결과 요약**에는 충분하지만, 아래 질문에 답하기엔 부족합니다.

- 왜 이 종목이 선택됐는가?
- 왜 다른 종목은 탈락했는가?
- 같은 규칙으로 다시 계산했을 때 결과가 같은가?
- 나중에 scoring 규칙을 바꿀 때, 어떤 항목이 실제로 score를 움직였는가?
- 특정 risk/reason이 어떤 raw indicator에서 나왔는가?

즉 현재 DB는 **final decision summary**는 저장하지만, **decision input snapshot**은 충분히 남기지 않습니다.

---

## 타당성 분석

## 1. candidate-level indicator snapshot 저장안은 타당한가?
**네, 매우 타당합니다.**

단, 목표를 분명히 해야 합니다.

### 이 저장안이 잘 맞는 목표
- 후보 선정 이유 추적
- 운영 장애/이상치 디버깅
- rules 변경 전후 비교
- user-facing explanation 근거 보존
- Oracle SQL 내 간단한 분석 쿼리 보조

### 이 저장안만으로는 부족한 목표
- 전체 universe 기준 백테스트
- 탈락 종목까지 포함한 precision/recall 분석
- threshold tuning 자동화
- factor importance의 정량 비교

즉,
- **운영/설명용으로는 강하게 타당**
- **정식 리서치/백테스트용으로는 불충분**
입니다.

---

## 2. wide columns vs single JSON snapshot

### 옵션 A. indicator마다 SQL column 추가
예:
- `sma_5`
- `sma_20`
- `sma_60`
- `volume_ratio_20d`
- `close_improvement_streak`
- ...

#### 장점
- SQL query가 쉽다
- 컬럼 타입이 명확하다
- BI/대시보드 붙이기 쉽다

#### 단점
- schema churn이 크다
- 규칙 바뀔 때마다 migration 필요
- 실험용 필드가 늘수록 테이블이 지저분해진다
- 지금 단계에서는 과하다

### 옵션 B. `indicator_snapshot_json` 1개 저장
예:
```json
{
  "schema_version": 1,
  "close": 57.31,
  "bb_lower": 56.33,
  "rsi_14": 44.47,
  "sma_5": 57.42,
  "sma_20": 58.12,
  "sma_60": 61.21,
  "distance_to_20d_low": 1.29,
  "average_volume_20d": 3245000,
  "volume_ratio_20d": 0.76,
  "close_improvement_streak": 2,
  "rsi_3d_change": 3.8,
  "weekly": {
    "close": 57.31,
    "sma_5": 58.4,
    "sma_10": 60.2,
    "close_improving": false,
    "trend_penalty": 3.0,
    "severe_damage": false
  }
}
```

#### 장점
- schema 변경이 매우 유연하다
- 지금 단계에 가장 덜 과하다
- rules 설명용 근거를 거의 그대로 저장 가능
- 신규 indicator 실험 비용이 낮다

#### 단점
- SQL query는 다소 불편하다
- 값 타입 검증을 app layer에서 더 신경 써야 한다
- snapshot 안에 무엇을 넣는지 discipline이 필요하다

### 판단
**지금 프로젝트 단계에서는 옵션 B가 더 적절합니다.**

추천 이유:
- 현재 우선순위는 운영 안정화와 설명 가능성
- 아직 factor set이 계속 바뀌는 중
- schema migration 부담을 최소화해야 함
- candidate-level traceability만 먼저 확보해도 가치가 큼

---

## 3. 단일 JSON만으로 충분한가?
**초기 단계는 충분합니다.**

단, 아래 원칙이 필요합니다.

### 원칙 1. 이미 relational로 충분한 것은 중복 최소화
예:
- `score`
- `subscores`
- `ticker`
- `generated_at`

이 값들은 이미 relational 필드가 있으므로 JSON에 중복 저장하더라도 “debug convenience” 수준으로만 보고, SQL truth는 기존 컬럼을 유지합니다.

### 원칙 2. JSON은 “판단 근거” 중심으로 제한
넣을 것:
- score 판단에 사용한 final feature values
- weekly penalty/reject 판단값
- explanation에 직접 연결되는 값

안 넣을 것:
- 전 기간 raw OHLCV 전체
- 중간 계산 배열 전체
- intraday raw payload 전체
- provider 원문 응답 전체

### 원칙 3. schema version 필수
`snapshot_schema_version` 또는 JSON 내부 `schema_version`이 필요합니다.

그래야 나중에:
- ATR 추가
- weekly filter 규칙 변경
- earnings proximity 추가
같은 변화가 생겨도 해석이 가능합니다.

---

## 4. 이 안의 가장 큰 한계
가장 중요한 한계는,
**후보로 살아남은 종목만 snapshot이 남는다면, 리서치 데이터로는 편향된 표본**이라는 점입니다.

예를 들어:
- 왜 어떤 날 후보가 적었는지
- 탈락 종목이 어디서 가장 많이 잘렸는지
- threshold를 바꾸면 universe 전체가 어떻게 달라지는지

이건 candidate-only 저장으로는 답하기 어렵습니다.

따라서 아래처럼 분리하는 것이 좋습니다.

### Phase 1
- candidate-level indicator snapshot 저장
- 목표: 운영/설명/디버그

### Phase 2
- optional universe-level feature snapshot 또는 audit sample 저장
- 목표: 리서치/백테스트/threshold tuning

현재는 **Phase 1까지만** 하는 것이 맞습니다.

---

## 권장 설계

## Recommendation
### 이번 라운드에서 할 것
`screen_candidates`에 아래 2개만 추가

1. `indicator_snapshot_json CLOB`
2. `snapshot_schema_version NUMBER DEFAULT 1 NOT NULL`

### 저장 내용
초기 snapshot에 포함할 최소 항목:
- `close`
- `low`
- `bb_lower`
- `rsi_14`
- `sma_5`
- `sma_20`
- `sma_60`
- `distance_to_20d_low`
- `distance_to_60d_low`
- `average_volume_20d`
- `volume_ratio_20d`
- `close_improvement_streak`
- `rsi_3d_change`
- `market_context_score`
- weekly context:
  - `weekly_close`
  - `weekly_sma_5`
  - `weekly_sma_10`
  - `weekly_close_improving`
  - `weekly_trend_penalty`
  - `weekly_trend_severe_damage`

### 저장하지 않을 것
- raw daily series 전체
- raw intraday series 전체
- provider response body
- 모든 중간 score 계산 과정

---

## 스키마/코드 영향

## Oracle schema
### 변경 대상
`screen_candidates`

### 추가 컬럼
- `indicator_snapshot_json CLOB`
- `snapshot_schema_version NUMBER DEFAULT 1 NOT NULL`

### migration 전략
현재 `_ensure_schema()`는 `CREATE TABLE IF NOT EXISTS` 스타일에 가까운 초기 생성만 다룹니다.
따라서 컬럼 추가는 아래 둘 중 하나가 필요합니다.

1. `_ensure_schema()`에 `ALTER TABLE ... ADD ...` guarded block 추가
2. 별도 one-time migration 함수 추가

추천은 **1번**입니다.
작고 단순하며 현 구조와 맞습니다.

---

## 모델/앱 레이어
### CandidateResult 확장
선택지:
- A. `indicator_snapshot: dict[str, Any] | None`
- B. 전용 `IndicatorSnapshot` pydantic model

초기 추천은 **A**입니다.
이유:
- 속도가 빠름
- 현재 필드가 실험 중
- schema evolution이 쉬움

단, JSON builder 함수는 별도로 두는 것이 좋습니다.
예:
- `build_indicator_snapshot(indicators: dict[str, Any]) -> dict[str, Any]`

이렇게 해야 DB persistence와 scoring logic이 직접 엉키지 않습니다.

---

## 문서/운영 관점
문서에는 아래가 명확해야 합니다.

- relational columns는 조회 최적화용 핵심 값
- snapshot JSON은 설명/디버그용 feature bundle
- snapshot schema는 버전 관리됨
- 백테스트 truth dataset은 별도 단계에서 다룸

즉 사용자 기대치를 이렇게 맞춰야 합니다.

> “이 저장은 왜 뽑혔는지 보려는 저장이지,
> 전체 연구용 데이터 웨어하우스를 대체하는 것은 아니다.”

---

## 개발 범위 제안

## Phase 1, 이번에 진행할 범위
1. `CandidateResult`에 optional snapshot 필드 추가
2. pipeline에서 final indicator snapshot 생성
3. Oracle SQL `screen_candidates`에 snapshot JSON + version 저장
4. 테스트 추가
   - snapshot builder unit test
   - Oracle persistence test
   - JSON roundtrip sanity test
5. 문서 업데이트

### Acceptance Criteria
- candidate 1건 조회 시 raw indicator snapshot을 같이 볼 수 있다
- snapshot 없이 기존 read path가 깨지지 않는다
- 기존 relational query는 그대로 동작한다
- `pytest -q` 통과

---

## Phase 2, 나중에 볼 것
- universe-level feature snapshot 저장
- rejected candidate audit log
- snapshot 내부 field normalization spec 고정
- Oracle JSON function 기반 query/view 추가
- backtest dataset export path 설계

---

## 권장 결론

### 결론 1
**indicator snapshot JSON 저장안은 타당하다.**
특히 운영, 설명, 디버깅, 규칙 추적 용도로는 매우 좋은 개선이다.

### 결론 2
하지만 이것만으로는 **백테스트 데이터 레이어**를 대체할 수 없다.
즉 이건 “research warehouse”가 아니라 “decision snapshot”이다.

### 결론 3
지금 단계에서는
- wide column 확장보다
- `indicator_snapshot_json + schema_version`
이 가장 적절하다.

---

## 바로 다음 액션 추천
1. 이 문서 방향 승인
2. `screen_candidates` snapshot JSON 저장 구현
3. daily 1회 실행 후 실제 row 예시 검증
4. 필요하면 그 다음에 universe-level 저장을 별도 기획
