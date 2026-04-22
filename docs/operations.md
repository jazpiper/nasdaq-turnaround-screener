# Operations Runbook

## 1. Bootstrap
```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest
```

- OpenClaw는 정기 실행과 secret 주입을 맡고, 이 저장소는 batch 실행과 artifact 생성을 맡습니다.
- 운영 기준 날짜는 항상 `America/New_York` 거래일입니다.

## 2. Daily Run
직접 CLI를 써도 되고 runner를 써도 됩니다.

```bash
python -m screener.cli.main run --date 2026-04-21
python -m screener.cli.main run --date 2026-04-21 --use-staged-intraday
python -m screener.cli.main run --date 2026-04-21 --persist-oracle-sql

python scripts/run_daily.py --date 2026-04-21 --skip-install
python scripts/run_daily.py --date 2026-04-21 --use-staged-intraday --skip-install
```

daily runner는 `.venv` 준비, 의존성 설치, `output/daily/YYYY-MM-DD/` 출력, `output/daily/latest` 갱신까지 처리합니다.
`--date` 는 **America/New_York 거래일 기준**으로 넣는 것을 전제로 합니다. 스케줄러가 UTC/KST에서 돈다면 당일 로컬 날짜를 그대로 쓰지 말고 NY trading day를 명시적으로 넘기는 편이 안전합니다.
- `run` CLI는 stdout에 `Data quality: nonempty=..., latest_date_mismatch=..., insufficient_history=...` 요약을 함께 출력합니다.
- `daily-report.json` 과 `run-metadata.json` 에는 `planned_ticker_count`, `successful_ticker_count`, `failed_ticker_count`, `bars_nonempty_count`, `latest_bar_date_mismatch_count`, `insufficient_history_count`, `planned_tickers` 가 함께 기록됩니다.
- earnings calendar 또는 benchmark context fetch가 실패하면 run은 계속 진행하고, 사유는 `run-metadata.json` / `daily-report.json` 의 `notes` 에 남깁니다.
- 운영 모니터링에서는 `latest_bar_date_mismatch_count` 증가를 stale bar 징후로, `insufficient_history_count` 증가를 provider coverage 문제 징후로 먼저 보는 편이 안전합니다.

## 3. Intraday Collection
```bash
# raw CLI 기본값: 6분할 계획 중 1개 window, 8 credits/min
python -m screener.cli.main collect-window --date 2026-04-21 --window-index 0
# raw CLI로 full-universe 재수집을 강제하려면 아래처럼 명시
python -m screener.cli.main collect-window --date 2026-04-21 --window-index 0 --total-windows 1 --max-credits-per-minute 5
python -m screener.cli.main collect-window --date 2026-04-21 --window-index 0 --persist-oracle-sql

# 운영 권장 entrypoint: wrapper
python scripts/run_intraday_window.py --date 2026-04-21 --window-id open-1 --skip-install
python scripts/run_intraday_window.py --date 2026-04-21 --window-id open-1 --skip-install --persist-oracle-sql
```

- 기본 장중 cadence는 `open-1`, `open-2`, `midday-1`, `midday-2`, `power-hour-1`, `power-hour-2` 의 6개 slot입니다.
- OpenClaw/cron wrapper인 `scripts/run_intraday_window.py` 는 각 slot마다 **NASDAQ-100 전체를 다시 수집**합니다. `open-1` 이 17개만 담당하는 식의 분할 수집은 더 이상 기본 동작이 아닙니다.
- bare `collect-window --window-index 0` 예시는 raw CLI 기본값을 보여주는 용도입니다. 이 경우 실제 동작은 `total_windows=6`, `max_credits_per_minute=8` 이므로 NASDAQ-100 전체가 아니라 1개 shard만 수집합니다.
- wrapper 기본값은 `collect-window --window-index 0 --total-windows 1 --max-credits-per-minute 5` 이며, Twelve Data free plan `8 credits/min` 대비 여유를 더 남겨 rate-limit 실패를 줄입니다.
- 운영에서는 wrapper 사용을 기본값으로 두고, raw `collect-window` CLI는 수동 분할 수집이나 ad-hoc 점검 용도로 보는 편이 안전합니다.
- 실제 artifact는 `output/intraday/YYYY-MM-DD/window-XX-of-YY/run-.../` 아래에 기록됩니다. wrapper 기본값에서는 `window-01-of-01` 아래에 쌓입니다.
- `collection-metadata.json` 에는 `planned_tickers`, `minute_batches`, `successes`, `failures`, `skipped_due_to_credit_exhaustion`, `remaining_tickers`, `uncollected_tickers` 와 집계 count가 함께 기록됩니다.
- `collect-window` CLI stdout은 `Failures` 만 바로 보여주므로, 일일 크레딧 소진으로 인한 미시도 ticker 수는 `collection-metadata.json` 의 `skipped_due_to_credit_exhaustion_count` 로 확인하는 편이 정확합니다.

## 4. Backtest
```bash
python -m screener.cli.main backtest --start-date 2026-03-01 --end-date 2026-04-21
python -m screener.cli.main backtest --start-date 2026-03-01 --end-date 2026-04-21 --horizons 5,10,20
```

- 현재 backtest는 threshold calibration용 최소 skeleton입니다.
- candidate 발생 시점별 점수와 `N` 거래일 후 수익률을 CSV/JSON으로 남깁니다.
- artifact는 기본적으로 `output/backtests/` 아래에 생성됩니다.

## 5. Environment and Secrets
- `SCREENER_MARKET_DATA_PROVIDER`: daily provider override (`yfinance`, `twelve-data`)
- `TWELVE_DATA_API_KEY`: Twelve Data API key
- `TWELVE_DATA_BASE_URL`: Twelve Data endpoint override
- `SCREENER_EARNINGS_CALENDAR_PATH`: earnings calendar JSON path
- `SCREENER_DAILY_INTRADAY_SOURCE_MODE=prefer-staged`: same-day staged quote 병합 활성화
- `SCREENER_INTRADAY_WINDOW_IDS`: intraday window 목록 override
- `SCREENER_INTRADAY_OUTPUT_ROOT`: intraday artifact root override
- `SCREENER_INTRADAY_COLLECTOR_COMMAND`: intraday runner command template override
- `SCREENER_ORACLE_SQL_ENABLED=1`: Oracle SQL persistence 기본 활성화
- `ORACLE_DB_USER`, `ORACLE_DB_PASSWORD`, `ORACLE_DB_CONNECT_STRING`: Oracle SQL credential override
- `SCREENER_OPENCLAW_SECRETS_PATH` 또는 `OPENCLAW_SECRETS_PATH`: OpenClaw secrets file path override

환경변수가 없으면 기본적으로 `~/.openclaw/secrets.json` 에서 provider / Oracle credential을 읽습니다.

## 6. Oracle SQL Notes
```bash
python -m screener.cli.main init-oracle-schema
```

- persistence write path는 더 이상 runtime DDL을 수행하지 않습니다.
- Oracle 저장을 쓰기 전에 `python -m screener.cli.main init-oracle-schema` 를 1회 실행해 schema를 준비해야 합니다.
- 이후 `--persist-oracle-sql` 은 insert만 수행합니다.

## 7. OpenClaw Usage
- 이 저장소는 cron 정의를 포함하지 않습니다. OpenClaw가 외부에서 명령을 호출하는 전제를 둡니다.
- 장중 수집은 `python scripts/run_intraday_window.py --date <NY_DATE> --window-id <ID> --skip-install` 형태로 호출하면 됩니다.
- 장 마감 후 daily run은 `python scripts/run_daily.py --date <NY_DATE> --skip-install` 형태로 호출하면 됩니다.
- Oracle을 쓰는 환경이면 bootstrap 단계에서 `python -m screener.cli.main init-oracle-schema` 를 먼저 1회 실행해야 합니다.
- OpenClaw가 읽어야 하는 daily 결과 진입점은 `output/daily/latest/` 입니다.
- daily report JSON/Markdown에는 candidate별 ticker와 company name이 함께 포함됩니다.
- intraday artifact는 daily run 보강용이므로, 기본적으로 OpenClaw가 직접 읽을 필요는 없습니다.
- same-day staged merge는 intraday metadata 전체를 읽는 것이 아니라, 각 run의 `completed_at` 또는 `started_at` 으로 최신 snapshot을 고른 뒤 `collected-quotes.json` 을 사용합니다.

## 8. OpenClaw Command Template
`SCREENER_INTRADAY_COLLECTOR_COMMAND` 를 쓰면 wrapper가 아래 placeholder를 치환합니다.

- `{python}`
- `{date}`
- `{window_id}`
- `{window_index}`
- `{output_dir}`
- `{output_root}`
- `{project_root}`

기본 template는 아래와 같습니다.

```bash
env PYTHONPATH={project_root}/src {python} -m screener.cli.main collect-window --date {date} --window-index 0 --total-windows 1 --max-credits-per-minute 5 --output-dir {output_root}
```

- `env PYTHONPATH={project_root}/src ...` prefix는 cron/OpenClaw 환경에서 `src/` import가 누락되지 않게 하려는 의도입니다.
- `window_id` 는 스케줄 slot 라벨 검증용이고, 기본 template는 의도적으로 `window-index 0`, `total-windows 1` 로 전체 유니버스를 다시 수집합니다.

## 9. Exit and Failure Handling
- 일부 ticker fetch 실패는 metadata에 남기고 run 전체는 계속 진행합니다.
- Twelve Data가 일일 크레딧 소진(`run out of API credits for the day` 류) 응답을 주면, 해당 slot의 추가 ticker 호출을 즉시 중단하고 이후 planned ticker는 미시도 상태로 metadata에 남깁니다.
- metadata에서는 실제 호출 후 실패한 ticker는 `failures` 에 남기고, 아직 호출하지 못한 ticker는 `skipped_due_to_credit_exhaustion` 으로 별도 분리합니다.
- 위 크레딧 소진은 현재 구현상 process crash로 취급하지 않습니다. `collect-window` 는 artifact와 failure metadata를 남기고 종료하며, non-zero exit는 설정 오류나 Oracle persistence 실패 같은 시스템 오류에 주로 사용합니다.
- Oracle SQL credential 누락이나 persistence 실패는 non-zero exit로 올립니다.
- 운영 alert는 non-zero exit만 보지 말고 `collection-metadata.json` 의 `failed_count`, `skipped_due_to_credit_exhaustion_count`, `failures`, 또는 credit exhaustion failure reason 문자열도 함께 감시하는 편이 안전합니다.
