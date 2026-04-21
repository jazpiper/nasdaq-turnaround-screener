# Operations Runbook

## 1. Bootstrap
```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest
```

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

- 기본 장중 cadence는 `open-1`, `open-2`, `midday-1`, `midday-2`, `power-hour-1`, `power-hour-2` 의 6개 window입니다.
- collector는 NASDAQ-100 universe를 window별로 고정 분할하고, 분당 최대 8건 기준으로 보수적으로 수집합니다.
- 실제 artifact는 `output/intraday/YYYY-MM-DD/window-XX-of-YY/run-.../` 아래에 기록됩니다.

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
- 이 저장소는 cron 스케줄을 직접 만들지 않습니다.
- OpenClaw는 장중에는 window별 intraday runner를, 장 마감 후에는 daily runner를 호출하면 됩니다.
- OpenClaw는 최종적으로 `output/daily/latest/` 또는 특정 날짜 디렉터리를 읽어 요약을 생성합니다.

## 8. Exit and Failure Handling
- 일부 ticker fetch 실패는 metadata에 남기고 run 전체는 계속 진행합니다.
- Oracle SQL credential 누락이나 persistence 실패는 non-zero exit로 올립니다.
- 운영에서는 non-zero exit를 그대로 retry / alert 판단에 사용하면 됩니다.
