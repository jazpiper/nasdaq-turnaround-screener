# Roadmap

## Current Status Summary
- Phase 0, 1은 완료
- daily screener, staged intraday collection, Oracle SQL opt-in persistence는 구현 완료
- 현재 관심사는 rule tuning, 운영 안정화, review/audit 가시성 보강

## Phase 0, Documentation (completed)
- 목표/범위 명확화
- signals와 score 초안 작성
- OpenClaw 연동 방식 결정

## Phase 1, MVP Screener (completed)
- project scaffold
- universe loader
- daily price fetch
- BB / RSI / MA 계산
- 후보 필터와 score
- markdown/json report 생성

## Phase 1.5, Operational Persistence (completed)
- staged intraday collection runner
- daily runner와 staged snapshot merge
- Oracle SQL daily/intraday persistence
- candidate-level `indicator_snapshot_json` 저장

## Phase 2, Evaluation and Rule Tuning (current)
- 최근 6~12개월 데이터 기준 샘플 검토
- false positive 유형 정리
- threshold 조정
- weekly trend penalty / severe damage rule 재점검
- rejected candidate audit 필요성 검토

## Phase 3, OpenClaw Automation Hardening (partially done)
- cron schedule 연결
- daily summary prompt 정리
- 실패 알림 / 로그 규칙 정리
- 운영용 query/view 또는 점검 runbook 보강

## Phase 4, Productization
- dashboard 또는 report UI
- watchlist/history 저장
- score trend 시각화
- universe-level feature snapshots 또는 research export
