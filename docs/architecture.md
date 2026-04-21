# Architecture

## 1. Design Goals
- OpenClaw core와 분리된 독립 프로젝트로 유지
- daily batch 실행에 최적화된 구조
- 데이터 수집, 신호 계산, 점수화, 리포팅, 저장을 느슨하게 분리
- file output을 기본 truth artifact로 유지하고, Oracle SQL persistence를 opt-in으로 붙인다
- Mongo/API 계열 document 저장은 future option으로 남긴다

## 2. Runtime Model
기본 실행 단위는 하루 1회 batch run입니다.

```text
scheduler(OpenClaw cron/manual)
  -> runner CLI
    -> universe loader
    -> market data fetcher
    -> indicator engine
    -> candidate filter
    -> scoring engine
    -> report builder
    -> storage adapter(optional)
    -> output artifacts(md/json)
```

## 3. Main Components

### 3.1 Runner / CLI
역할:
- 실행 날짜와 모드 지정
- dry-run / daily-run / backfill 모드 처리
- 전체 pipeline orchestration

현재 command 예시:
```bash
python -m screener.cli.main run --date 2026-04-21
python -m screener.cli.main run --date 2026-04-21 --persist-oracle-sql
screener run --date 2026-04-21
```

### 3.2 Universe Layer
역할:
- NASDAQ-100 티커 목록 관리
- 추후 index 구성 종목 변경 이력 snapshot 가능

출력:
- normalized ticker list
- metadata(optional): name, sector, industry

### 3.3 Data Layer
역할:
- 가격 데이터 fetch
- provider abstraction 유지
- partial failure를 종목 단위로 격리

후보 provider:
- Yahoo Finance 계열
- Alpha Vantage
- Twelve Data
- Polygon (향후)

핵심 원칙:
- provider interface 고정
- raw fetch와 normalized OHLCV를 분리
- 재시도와 throttle 처리

### 3.4 Indicator Engine
역할:
- Bollinger Bands(20, 2)
- RSI(14)
- short moving averages
- recent low distance
- volume ratio
- optional volatility / trend metrics

출력:
- ticker별 normalized feature set

### 3.5 Candidate Filter
역할:
- BB 하단 근접/이탈 여부 확인
- 최근 저점 부근인지 판단
- 최소 유동성/데이터 품질 기준 적용

이 단계는 강한 1차 필터입니다.
점수화 전에 명백히 아닌 종목을 제외합니다.

### 3.6 Scoring Engine
역할:
- turnaround 가능성을 설명 가능한 점수로 환산
- factor별 subscore 생성
- 최종 score와 ranking 생성

예시 factor:
- oversold context
- local bottom context
- reversal evidence
- volume behavior
- market / sector context

### 3.7 Reporting Layer
역할:
- markdown 리포트 생성
- JSON artifact 생성
- candidate별 reason / risk summary 생성

출력 파일:
- `<output-dir>/daily-report.md`
- `<output-dir>/daily-report.json`
- `<output-dir>/run-metadata.json`

JSON artifact는 candidate 전체를 `model_dump(mode="json")` 로 직렬화하므로, `indicator_snapshot` 이 있으면 그대로 노출됩니다. Markdown은 요약형으로 유지합니다.

### 3.8 Storage Adapter
역할:
- 선택적으로 결과 저장
- 현재는 Oracle SQL persistence 지원
- file artifact와 DB persistence를 분리

현재 구현:
- daily run Oracle SQL persistence
- intraday collection Oracle SQL persistence
- `screen_candidates.indicator_snapshot_json` + `snapshot_schema_version`

future option:
- document/archive 계열 저장소 추가

storage adapter가 필요한 이유:
- file artifact와 DB persistence를 분리
- 구현 순서를 유연하게 가져감
- 나중에 서비스화할 때 저장소 교체 비용을 낮춤

## 4. Source Layout
```text
src/
  screener/
    cli/
      main.py
    collector.py
    config.py
    data/
      market_data.py
    indicators/
      technicals.py
    intraday_artifacts.py
    intraday_ops.py
    models/
      schemas.py
    pipeline.py
    reporting/
      markdown.py
      json_report.py
    scoring/
      ranking.py
    secrets.py
    storage/
      files.py
      oracle_sql.py
    universe/
      loader.py
      nasdaq100.py
```

## 5. OpenClaw Integration

### 5.1 Responsibility Split
- screener project: 데이터 처리와 artifact 생성
- OpenClaw: 실행 orchestration, secret access, 결과 요약, delivery

### 5.2 Secret Strategy
OpenClaw secrets를 통해 다음 credential을 참조합니다.
- Oracle SQL credential
- 향후 market data provider API key
- 필요해질 경우 future document store credential

### 5.3 Delivery Flow
```text
OpenClaw cron
  -> run screener command
  -> read generated artifact
  -> summarize top candidates
  -> send dashboard / Telegram briefing
```

## 6. Failure Handling
- provider fetch failure와 pipeline fatal failure를 구분
- 일부 종목 실패는 run 전체 실패로 간주하지 않음
- artifact metadata에 실패 종목 수 / 데이터 품질 경고 포함
- CLI exit code는 운영 자동화에 사용 가능하게 유지

## 7. Evolution Path
- Current: file output + optional Oracle SQL persistence
- Next: historical candidate store/query hardening + review/audit views
- Later: universe-level feature snapshots or rejection audit
- V3: dashboard/service layer
