# Storage Strategy

## Goal
스크리너 결과를 어디에 저장할지 미리 분리해서, 구현 초기에 file output만 쓰더라도 나중에 DB persistence를 자연스럽게 붙일 수 있게 합니다.

## 1. Storage Modes

### A. File Only
초기 기본값.
- 장점: 가장 단순함
- 용도: MVP, 로컬 검증, artifact 기반 OpenClaw 브리핑
- 생성물: markdown/json report

### B. Oracle SQL
정형 데이터와 조회용 저장.
- 장점:
  - daily candidate history 조회 용이
  - score 추세 비교 용이
  - 운영/설명용 decision snapshot 추적 가능
  - backtest/분석 쿼리에 강함
- 추천 저장 대상:
  - run metadata
  - daily candidates
  - factor subscores
  - candidate-level indicator snapshots
  - watchlist snapshots

### C. Oracle Mongo API
유연한 document 저장.
- 장점:
  - 리포트 원문 JSON 저장이 쉬움
  - schema 변화 대응이 유연함
  - 실험 단계 artifact 저장에 적합
- 추천 저장 대상:
  - raw report documents
  - candidate explanation payload
  - debug artifacts

## 2. Recommendation
초기 추천 구조:
- 기본 truth artifact: file output
- 구조화 history: Oracle SQL
- 원문 document archive: Oracle Mongo API optional

즉, SQL을 주 저장소로 보고 Mongo API는 보조 저장소로 쓰는 편이 좋습니다.

## 3. Example SQL Entities
- `screen_runs`
- `screen_candidates`
- `candidate_subscores`
- `universe_snapshots`

`screen_candidates`에는 relational column 외에 `indicator_snapshot_json` 같은 설명/디버그용 feature snapshot을 함께 둘 수 있습니다. 이 snapshot은 백테스트용 full warehouse가 아니라, 왜 해당 candidate가 선택되었는지 추적하기 위한 decision snapshot으로 봅니다.

## 4. Example Mongo Collections
- `daily_reports`
- `candidate_payloads`
- `debug_runs`

## 5. Secret References
OpenClaw secrets에 저장된 credential을 사용합니다.

예시 key:
- `/oracleDb/user`
- `/oracleDb/password`
- `/oracleDb/connectString`
- `/oracleMongoDb/user`
- `/oracleMongoDb/password`
- `/oracleMongoDb/uri`

프로젝트 코드에는 plaintext secret을 저장하지 않습니다.
