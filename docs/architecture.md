# Architecture

## 1. System Boundary
- OpenClaw core와 분리된 독립 프로젝트입니다.
- 자동 매매가 아니라 daily research batch를 만드는 스크리너입니다.
- file artifact를 기본 결과물로 두고, Oracle SQL persistence는 opt-in으로 붙습니다.

## 2. Runtime Flows

### Daily Screening
```text
CLI / runner
  -> NASDAQ-100 universe load by default, or explicit custom ticker universe when --tickers is provided
  -> daily price fetch
  -> optional staged intraday merge
  -> indicator calculation
  -> earnings + QQQ context merge
  -> candidate filter
  -> scoring / ranking
  -> run metadata + data-quality counters
  -> markdown + json + metadata output
  -> final alert sidecar output
  -> optional Oracle SQL persistence
```

### Assistant Briefing Build
```text
CLI build-assistant-briefing
  -> read output/daily/latest/daily-report.json by default
  -> extract user tickers, missing/outside-universe tickers, data-quality summary
  -> include compact top-candidate subset
  -> write output/assistant/latest-user-briefing-screener.{json,md}
```

Assistant briefing artifacts are generated from existing daily screener output only. They do not fetch market data, call Oracle, or change the daily report / alert sidecar schemas. The default artifact names remain `latest-user-briefing-screener.{json,md}`; `--artifact-basename` can write a separate compact briefing such as `latest-user-watchlist-screener.{json,md}`. The signals are decision-support only and not buy/sell advice.

### Universe Selection
- Default daily screening remains NASDAQ-100. With no custom ticker option, `Settings.universe_tickers` is `None`, `RunMetadata.universe` stays `NASDAQ-100`, and the existing report/metadata/alert artifact schema is unchanged.
- `--tickers` and `--universe-tickers` are aliases for an explicit comma-separated ticker list. The parser trims, uppercases, converts `.` to `-`, drops blanks, removes duplicates, and preserves first-seen order.
- When custom tickers are provided, the default universe name recorded in metadata is `user-watchlist`; `--universe-name` can override only the metadata/name while using the same custom ticker list. `--universe-name` without custom tickers is rejected to avoid misleading NASDAQ-100 relabeling.
- `scripts/run_daily.py` keeps the NASDAQ-100 cron entrypoint stable by resolving omitted custom `--output-root` values to `output/daily-<universe-name>` (for example `output/daily-user-watchlist`); explicit `--output-root` still wins.
- `StaticUniverseProvider` receives the optional custom ticker tuple from `Settings`; otherwise it delegates to the static NASDAQ-100 list.

### Staged Intraday Collection
```text
CLI / runner
  -> slot id validation / command template expansion
  -> full-universe collect-window invocation by default
  -> minute-batch throttling
  -> early stop on daily credit exhaustion
  -> per-slot artifact write
  -> provisional alert sidecar output
  -> optional Oracle SQL persistence
```

기본 운영의 6개 `window_id` 는 NASDAQ-100 shard가 아니라 스케줄 slot 라벨입니다. wrapper 기본값은 각 slot마다 `collect-window --window-index 0 --total-windows 1 --max-credits-per-minute 5` 를 호출해 전체 유니버스를 다시 수집합니다. raw `collect-window` CLI는 필요하면 여전히 `total_windows > 1` 수동 분할 수집에 쓸 수 있습니다.

장중 수집은 보강 데이터 역할입니다. 장 마감 후 daily run이 가장 최근 staged quote를 읽어 같은 날짜 일봉 bar를 교체하거나 append 합니다.

## 3. Artifact Consumers
- 운영 오케스트레이터가 읽는 기본 daily consumer entrypoint는 `output/daily/latest/alert-events.json` 입니다.
- personal assistant용 compact screener entrypoint는 `output/assistant/latest-user-briefing-screener.json` 와 `output/assistant/latest-user-briefing-screener.md` 입니다.
- provisional intraday consumer entrypoint는 `output/intraday/YYYY-MM-DD/latest-alert-events.json` 입니다.
- same-day staged intraday merge는 `collection-metadata.json` 전체를 해석하지 않고, 각 run의 `completed_at` 또는 `started_at` 으로 최신 snapshot을 고른 뒤 `collected-quotes.json` 을 읽습니다.
- `collection-metadata.json` 의 `failures`, `skipped_due_to_credit_exhaustion` 같은 필드는 운영 해석과 Oracle 적재에는 쓰이지만, 현재 이 저장소 안의 daily merge 경로가 직접 소비하지는 않습니다.
- Oracle `intraday_collection_runs` / `intraday_collection_quotes` 는 현재 이 저장소 안에서는 write-only persistence 경로입니다.

## 4. Backtest & Tuning Loop

### Backtest
```text
CLI backtest
  -> historical daily history load
  -> trading-date replay
  -> same scoring rules 재적용
  -> forward N-day return observation 저장 (subscores + snapshot 포함)
```

### Parameter Tuning (Walk-Forward)
```text
CLI tune
  -> HistoricalBacktestRunner.generate_observations() 호출
  -> 충분한 데이터 있으면: 슬라이딩 창 walk-forward
       train 창: grid 400조합 평가 (TierThresholds 재분류만, 지표 재계산 없음)
       eval 창: 최적 조합 out-of-sample 검증
       안정성: min_wins 창 이상 우승한 조합만 proposal
  -> 데이터 부족 시: single-window 그리드서치 fallback
  -> output/tuning/<end-date>/ 에 proposal JSON + diff MD + walkforward JSON 저장
  -> 사람이 proposal 승인 후 scripts/apply_tuning_proposal.py --write 로 tiering.py 반영
  -> uv run pytest 자동 실행, 실패 시 tiering.py 원복
```

사람 승인 없이 자동 적용되지 않습니다. `apply_tuning_proposal.py` 기본 모드는 dry-run입니다.

## 5. Main Modules
- `src/screener/cli/main.py`: `run`, `build-assistant-briefing`, `collect-window`, `init-oracle-schema`, `backtest`, `tune`
- `src/screener/pipeline.py`: 공개 facade
- `src/screener/_pipeline/`: provider, context merge, snapshot, orchestration (`contracts.py` 에 ABC 정의)
- `src/screener/backtest.py`: historical replay와 forward-return artifact 생성. `generate_observations()` 로 관찰치 생성과 집계를 분리
- `src/screener/tuning/`: walk-forward 그리드서치 패키지 (`grid`, `objective`, `runner`, `walkforward`, `report`)
- `src/screener/collector.py`: intraday 계획 생성, 분당 throttle, daily-credit exhaustion short-circuit, artifact write
- `src/screener/intraday_ops.py`: slot id normalization과 cron/OpenClaw용 collector command template 조립
- `src/screener/intraday_artifacts.py`: daily merge 경로에서 staged intraday artifact를 읽는 reader
- `src/screener/config.py`: 설정·환경변수 해석·OpenClaw secrets 로딩. `universe_tickers=None` 이면 NASDAQ-100 기본값, tuple이면 explicit custom universe
- `src/screener/secrets.py`: OpenClaw secrets file reader
- `src/screener/models/schemas.py`: pipeline 전반에서 쓰는 Pydantic 데이터 모델
- `src/screener/data/`: `yfinance` / Twelve Data fetch와 OHLCV normalization
- `src/screener/indicators/technicals.py`: BB, RSI, SMA, ATR, weekly context, candle metrics 계산
- `src/screener/scoring/ranking.py`: hard filter, subscore, penalty, ranking
- `src/screener/scoring/thresholds.py`: threshold 상수 모음
- `src/screener/reporting/`: markdown / json report 생성, assistant briefing compact artifact 생성
- `src/screener/storage/`: file output과 Oracle SQL persistence

## 6. Data Sources and Configuration
- daily 기본 provider는 `yfinance` 입니다.
- Twelve Data는 staged intraday collection과 명시적 provider override에 사용합니다.
- earnings context는 `SCREENER_EARNINGS_CALENDAR_PATH` 기반 file-backed source를 사용합니다.
- 설정과 secret은 환경변수 또는 OpenClaw secrets(`~/.openclaw/secrets.json`)에서 읽습니다.

## 7. Outputs
- daily output: `output/daily/YYYY-MM-DD/`
  - `daily-report.md`
  - `daily-report.json`: candidate list와 함께 `planned_ticker_count`, `successful_ticker_count`, `failed_ticker_count`, `bars_nonempty_count`, `latest_bar_date_mismatch_count`, `insufficient_history_count`, `planned_tickers`, `data_failures`, `notes` 를 포함
  - `run-metadata.json`: 전체 `RunMetadata` snapshot. planning / quality field와 `data_failures`, `notes` 를 함께 기록
  - `alert-events.json`: OpenClaw consumer contract용 final alert sidecar
- latest pointer: `output/daily/latest`
- assistant briefing output: `output/assistant/`
  - `latest-user-briefing-screener.json`: compact personal-assistant payload with schema version, source report path, data-quality summary, user ticker signal summaries, missing/outside-universe tickers, and top candidates
  - `latest-user-briefing-screener.md`: compact human-readable briefing with the same decision-support caution
  - custom basename option: `--artifact-basename latest-user-watchlist-screener` writes `latest-user-watchlist-screener.json` and `.md` without changing the default artifact contract
- intraday output: `output/intraday/YYYY-MM-DD/window-XX-of-YY/run-.../`
  - `collection-metadata.json`: `planned_tickers`, `minute_batches`, `successes`, `failures`, `skipped_due_to_credit_exhaustion`, `remaining_tickers`, `uncollected_tickers`, 각종 count를 포함
  - `collected-quotes.json`
  - `alert-events.json`: 해당 run 기준 provisional alert sidecar
- stable consumer entrypoints:
  - `output/daily/latest/alert-events.json`
  - `output/assistant/latest-user-briefing-screener.json`
  - `output/assistant/latest-user-briefing-screener.md`
  - `output/intraday/YYYY-MM-DD/latest-alert-events.json`
- local dedupe state:
  - `output/alerts/YYYY-MM-DD/alert-state.json`

## 8. Persistence
- 기본 truth artifact는 file output입니다.
- `--persist-oracle-sql` 또는 `SCREENER_ORACLE_SQL_ENABLED=1` 이면 Oracle SQL에도 저장합니다.
- schema 생성은 `init-oracle-schema` command로 분리되어 있습니다.
- daily Oracle persistence는 `screen_runs` 에 `candidate_count`, `data_failures_json`, `notes_json` 을 저장하고, candidate별로 `screen_candidates`, `candidate_subscores` 를 적재합니다. planning / data-quality counter는 현재 file artifact에는 기록되지만 `screen_runs` 에는 별도 컬럼으로 확장되지 않았습니다.
- intraday Oracle persistence는 `collection-metadata.json` 을 읽어 `planned_tickers`, `minute_batches`, `successes`, `failures`, `skipped_due_to_credit_exhaustion`, `remaining_tickers`, `uncollected_tickers` 요약을 `intraday_collection_runs` 에 함께 적재합니다.
- 현재 저장 범위:
  - `screen_runs`
  - `screen_candidates`
  - `candidate_subscores`
  - `intraday_collection_runs`
  - `intraday_collection_quotes`
- candidate에는 `indicator_snapshot_json` 과 `snapshot_schema_version` 이 함께 저장됩니다.
- snapshot schema version 값은 `src/screener/_pipeline/snapshot.py` 의 `INDICATOR_SNAPSHOT_SCHEMA_VERSION` 상수를 기준으로 봅니다.

## 9. OpenClaw Boundary
- 이 저장소는 데이터 처리와 alert-ready sidecar 생성을 담당하고, OpenClaw는 실행 orchestration과 Telegram delivery를 담당합니다.
- 운영 명령과 환경변수는 `docs/operations.md`, 현재 screening 규칙은 `docs/signals.md` 를 기준 문서로 봅니다.
