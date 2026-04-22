# Documentation And Follow-up Status — 2026-04-22

이 문서는 2026-04-22 기준 문서 리뷰 결과, 실제 반영 사항, 후속 개선 후보를 한 곳에 묶어 둔 상태 문서입니다. 현재 구현의 기준 문서는 `README.md`, `docs/architecture.md`, `docs/operations.md`, `docs/signals.md` 입니다.

## 1. Canonical Documents
- `README.md`: 프로젝트 개요와 빠른 실행 진입점
- `docs/architecture.md`: 시스템 경계, artifact 구조, persistence 범위
- `docs/operations.md`: 운영 명령, OpenClaw 경계, alert / failure 해석
- `docs/signals.md`: hard filter, subscore, overlay, ranking 규칙

## 2. Review Items Reflected
아래 항목은 현재 문서 또는 구현에 반영되었습니다.

- raw `collect-window` CLI 기본값과 wrapper 기본값 차이 명시
- earnings / volatility overlay의 max-penalty 규칙 명시
- volatility overlay penalty 수치 명시
- `relative_strength_score` 가 scoring-derived field임을 명시
- `weekly_trend_severe_damage` 정의와 tie-break 규칙 명시
- exit code만으로 credit exhaustion alert를 놓칠 수 있다는 운영 주의사항 반영
- README Current Scope 축약과 Oracle setup 분리
- snapshot schema version source of truth를 `_pipeline/snapshot.py` 기준으로 정리

## 3. Implementation Status
이번 정리 흐름에서 실제 코드까지 반영된 항목은 아래와 같습니다.

- intraday credit exhaustion 이후 미시도 ticker를 `skipped_due_to_credit_exhaustion` 으로 분리 기록
- Oracle `intraday_collection_runs` 에 `credit_exhaustion_skips_json`, `credit_exhaustion_skip_count` 컬럼 반영
- `MINIMUM_TOTAL_SCORE = 1` cutoff 도입으로 0점 후보 제거
- scoring invariant 테스트 추가
- 실 Oracle schema init 및 intraday persistence smoke test 완료

## 4. Downstream Consumer Check
이 저장소와 같은 머신의 형제 프로젝트까지 확인한 결과, 현재 확인된 local consumer 경계는 아래와 같습니다.

- OpenClaw의 기본 소비 진입점은 `output/daily/latest/`
- same-day staged merge는 `collection-metadata.json` 의 `completed_at` 또는 `started_at` 만 이용해 최신 run을 고르고, 실제 데이터는 `collected-quotes.json` 에서 읽음
- `collection-metadata.json` 의 `failures` / `skipped_due_to_credit_exhaustion` 를 직접 해석하는 local consumer는 현재 없음
- Oracle `intraday_collection_runs` / `intraday_collection_quotes` 를 조회하는 local reader도 현재 없음

즉 이번 metadata 확장과 Oracle intraday 컬럼 추가는 현재 저장소 안의 기존 reader를 깨지 않습니다.

## 5. Remaining Follow-ups
아래는 문서 오류라기보다 설계 개선 또는 운영 가시성 개선 후보로 남겨둡니다.

- market context missing-data를 명시적으로 계수하는 metadata 확장
- `rel_strength_60d_vs_qqq >= strong` 일 때 reason 문구 추가 여부 결정
- volume saturation 구간과 reversal candle bonus 구조 재검토
- earnings unavailable count 같은 운영용 추가 집계 검토

## 6. Maintenance Rule
- 구현 기준 설명은 위 canonical docs에 반영하고, 이 문서는 검토 기록과 후속 상태만 짧게 유지합니다.
- 새 기능이 문서 구조를 바꿀 정도가 아니면 이 문서에 긴 분석을 다시 쌓지 않고 해당 기준 문서만 갱신합니다.
