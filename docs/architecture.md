# Architecture

## 원칙
- OpenClaw core와 분리된 독립 프로젝트
- 결과물은 file artifact로 남기고, OpenClaw는 실행과 요약만 담당
- 나중에 웹서비스로 확장 가능한 구조 유지

## Components
1. `universe`
   - NASDAQ-100 ticker 목록 관리
2. `data`
   - price fetch / cache
3. `indicators`
   - BB, RSI, MA, volume metrics 계산
4. `scoring`
   - filter + ranking logic
5. `reporting`
   - markdown/json output 생성
6. `runner`
   - CLI entrypoint

## OpenClaw Integration
- cron이 daily command 실행
- 결과 파일 생성
- OpenClaw가 결과를 읽고 최종 브리핑 작성
- 향후 Telegram / dashboard delivery 가능

## Proposed Layout
```text
nasdaq-turnaround-screener/
  README.md
  docs/
  src/
  tests/
  output/
```

## Data Source Strategy
초기에는 무료/저비용 소스를 우선 고려하되, 안정성과 속도에 따라 교체 가능하도록 data provider abstraction 유지.

후보:
- Yahoo Finance 계열
- Alpha Vantage
- Twelve Data
- Polygon (향후)

## Reliability Notes
- data fetch failure와 partial data를 구분
- universe list 변동 시 snapshot 기록
- score 계산은 deterministic하게 유지
