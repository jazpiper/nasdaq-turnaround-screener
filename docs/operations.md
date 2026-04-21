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
python -m screener.cli.main init-oracle-schema
python -m screener.cli.main run --date 2026-04-21 --persist-oracle-sql

python scripts/run_daily.py --date 2026-04-21 --skip-install
python scripts/run_daily.py --date 2026-04-21 --use-staged-intraday --skip-install
```

daily runner는 `.venv` 준비, 의존성 설치, `output/daily/YYYY-MM-DD/` 출력, `output/daily/latest` 갱신까지 처리합니다.
`--date` 는 **America/New_York 거래일 기준**으로 넣는 것을 전제로 합니다. 스케줄러가 UTC/KST에서 돈다면 당일 로컬 날짜를 그대로 쓰지 말고 NY trading day를 명시적으로 넘기는 편이 안전합니다.

## 3. Intraday Collection
```bash
python -m screener.cli.main collect-window --date 2026-04-21 --window-index 0
python -m screener.cli.main collect-window --date 2026-04-21 --window-index 0 --persist-oracle-sql

python scripts/run_intraday_window.py --date 2026-04-21 --window-id open-1 --skip-install
python scripts/run_intraday_window.py --date 2026-04-21 --window-id open-1 --skip-install --persist-oracle-sql
```

- 기본 장중 cadence는 `open-1`, `open-2`, `midday-1`, `midday-2`, `power-hour-1`, `power-hour-2` 의 6개 slot입니다.
- OpenClaw/cron wrapper인 `scripts/run_intraday_window.py` 는 각 slot마다 **NASDAQ-100 전체를 다시 수집**합니다. `open-1` 이 17개만 담당하는 식의 분할 수집은 더 이상 기본 동작이 아닙니다.
- wrapper 기본값은 `collect-window --window-index 0 --total-windows 1 --max-credits-per-minute 7` 이며, Twelve Data free plan `8 credits/min` 에 대해 1 credit 버퍼를 남겨 rate-limit 실패를 줄입니다.
- raw `collect-window` CLI는 여전히 `--total-windows` 를 늘려 수동 분할 수집에 사용할 수 있습니다.
- 실제 artifact는 `output/intraday/YYYY-MM-DD/window-XX-of-YY/run-.../` 아래에 기록됩니다. wrapper 기본값에서는 `window-01-of-01` 아래에 쌓입니다.

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
- persistence write path는 더 이상 runtime DDL을 수행하지 않습니다.
- Oracle 저장을 쓰기 전에 `python -m screener.cli.main init-oracle-schema` 를 1회 실행해 schema를 준비해야 합니다.
- 이후 `--persist-oracle-sql` 은 insert만 수행합니다.

## 7. OpenClaw Usage
- 이 저장소는 cron 정의를 포함하지 않습니다. OpenClaw가 외부에서 명령을 호출하는 전제를 둡니다.
- 장중 수집은 `python scripts/run_intraday_window.py --date <NY_DATE> --window-id <ID> --skip-install` 형태로 호출하면 됩니다.
- 장 마감 후 daily run은 `python scripts/run_daily.py --date <NY_DATE> --skip-install` 형태로 호출하면 됩니다.
- Oracle을 쓰는 환경이면 bootstrap 단계에서 `python -m screener.cli.main init-oracle-schema` 를 먼저 1회 실행해야 합니다.
- OpenClaw가 읽어야 하는 daily 결과 진입점은 `output/daily/latest/` 입니다.
- intraday artifact는 daily run 보강용이므로, 기본적으로 OpenClaw가 직접 읽을 필요는 없습니다.

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
{python} -m screener.cli.main collect-window --date {date} --window-index 0 --total-windows 1 --max-credits-per-minute 7 --output-dir {output_root}
```

## 9. Exit and Failure Handling
- 일부 ticker fetch 실패는 metadata에 남기고 run 전체는 계속 진행합니다.
- Oracle SQL credential 누락이나 persistence 실패는 non-zero exit로 올립니다.
- 운영에서는 non-zero exit를 그대로 retry / alert 판단에 사용하면 됩니다.
