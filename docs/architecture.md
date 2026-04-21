# Architecture

## 1. System Boundary
- OpenClaw core와 분리된 독립 프로젝트입니다.
- 자동 매매가 아니라 daily research batch를 만드는 스크리너입니다.
- file artifact를 기본 결과물로 두고, Oracle SQL persistence는 opt-in으로 붙습니다.

## 2. Runtime Flows

### Daily Screening
```text
CLI / runner
  -> NASDAQ-100 universe load
  -> daily price fetch
  -> optional staged intraday merge
  -> indicator calculation
  -> earnings + QQQ context merge
  -> candidate filter
  -> scoring / ranking
  -> markdown + json + metadata output
  -> optional Oracle SQL persistence
```

### Staged Intraday Collection
```text
CLI / runner
  -> 6-window plan build
  -> Twelve Data quote fetch
  -> per-window artifact write
  -> optional Oracle SQL persistence
```

장중 수집은 보강 데이터 역할입니다. 장 마감 후 daily run이 가장 최근 staged quote를 읽어 같은 날짜 일봉 bar를 교체하거나 append 합니다.

### Backtest Skeleton
```text
CLI
  -> historical daily history load
  -> trading-date replay
  -> same scoring rules 재적용
  -> forward N-day return observation 저장
```

현재 backtest는 calibration 준비용 skeleton이며, 별도 전략 엔진이나 portfolio simulation은 아직 없습니다.

## 3. Main Modules
- `src/screener/cli/main.py`: `run`, `collect-window`, `init-oracle-schema`, `backtest`
- `src/screener/pipeline.py`: 공개 facade
- `src/screener/_pipeline/`: provider, context merge, snapshot, orchestration
- `src/screener/backtest.py`: historical replay와 forward-return artifact 생성
- `src/screener/collector.py`: intraday window planning, fetch, artifact write
- `src/screener/data/`: `yfinance` / Twelve Data fetch와 OHLCV normalization
- `src/screener/indicators/technicals.py`: BB, RSI, SMA, ATR, weekly context, candle metrics 계산
- `src/screener/scoring/ranking.py`: hard filter, subscore, penalty, ranking
- `src/screener/scoring/thresholds.py`: threshold 상수 모음
- `src/screener/reporting/`: markdown / json report 생성
- `src/screener/storage/`: file output과 Oracle SQL persistence

## 4. Data Sources and Configuration
- daily 기본 provider는 `yfinance` 입니다.
- Twelve Data는 staged intraday collection과 명시적 provider override에 사용합니다.
- earnings context는 `SCREENER_EARNINGS_CALENDAR_PATH` 기반 file-backed source를 사용합니다.
- 설정과 secret은 환경변수 또는 OpenClaw secrets(`~/.openclaw/secrets.json`)에서 읽습니다.

## 5. Outputs
- daily output: `output/daily/YYYY-MM-DD/`
  - `daily-report.md`
  - `daily-report.json`
  - `run-metadata.json`
- latest pointer: `output/daily/latest`
- intraday output: `output/intraday/YYYY-MM-DD/window-XX-of-YY/run-.../`
  - `collection-metadata.json`
  - `collected-quotes.json`

## 6. Persistence
- 기본 truth artifact는 file output입니다.
- `--persist-oracle-sql` 또는 `SCREENER_ORACLE_SQL_ENABLED=1` 이면 Oracle SQL에도 저장합니다.
- schema 생성은 `init-oracle-schema` command로 분리되어 있습니다.
- 현재 저장 범위:
  - `screen_runs`
  - `screen_candidates`
  - `candidate_subscores`
  - `intraday_collection_runs`
  - `intraday_collection_quotes`
- candidate에는 `indicator_snapshot_json` 과 `snapshot_schema_version` 이 함께 저장됩니다.
- snapshot schema version은 현재 `2` 입니다.

## 7. OpenClaw Role
- 이 저장소는 데이터 처리와 artifact 생성을 담당합니다.
- OpenClaw는 실행 orchestration, secret 주입, 결과 요약과 전달을 담당합니다.
- 운영 기준 command와 환경변수는 `docs/operations.md`, 현재 규칙은 `docs/signals.md`를 기준으로 봅니다.
