# OpenClaw Cron Runbook

이 문서는 `OpenClaw` 쪽 운영자에게 그대로 전달해도 되는 수준의 cron 등록 및 소비(run + read) 지침입니다. 기준 저장소는 `nasdaq-turnaround-screener` 이고, 이 저장소는 `alert-events.json` producer 역할만 맡습니다. Telegram delivery와 실제 cron orchestration은 `OpenClaw` 가 담당합니다.

## 1. Scope
- 이 저장소가 생성하는 artifact:
  - daily final sidecar: `output/daily/latest/alert-events.json`
  - intraday provisional sidecar: `output/intraday/<NY_DATE>/latest-alert-events.json`
- `OpenClaw` 가 해야 하는 일:
  - America/New_York 거래일 기준으로 정기 실행
  - 각 실행 후 stable consumer entrypoint를 읽기
  - `quality_gate`, `event_type`, `dedupe_key` 기준으로 Telegram delivery 판단

## 2. Assumptions
- project root: `/home/ubuntu/project/nasdaq-turnaround-screener`
- 운영 기준 timezone: `America/New_York`
- cron 등록도 가능하면 `CRON_TZ=America/New_York` 기준으로 잡는 것을 권장
- `--date` 는 항상 NY trading day를 명시적으로 넘긴다.
- `OpenClaw` 가 거래일 계산이 가능하면 미국 휴장일 / 주말에는 실행을 생략하는 것이 가장 안전하다.

## 3. One-Time Bootstrap
최초 1회만 수행하면 됩니다.

```bash
cd /home/ubuntu/project/nasdaq-turnaround-screener
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

Oracle SQL persistence를 쓸 경우에만 아래를 1회 추가합니다.

```bash
cd /home/ubuntu/project/nasdaq-turnaround-screener
.venv/bin/python -m screener.cli.main init-oracle-schema
```

## 4. Secrets And Environment
`OpenClaw` 는 아래 값들을 환경변수 또는 `~/.openclaw/secrets.json` 로 주입하면 됩니다.

- `TWELVE_DATA_API_KEY`
- `ORACLE_DB_USER`
- `ORACLE_DB_PASSWORD`
- `ORACLE_DB_CONNECT_STRING`
- `SCREENER_OPENCLAW_SECRETS_PATH` 또는 `OPENCLAW_SECRETS_PATH`

참고:
- 이 저장소는 환경변수가 없으면 기본적으로 `~/.openclaw/secrets.json` 을 읽습니다.
- daily final run은 기본적으로 `yfinance` 를 쓰고, intraday collector는 `twelve-data` 를 사용합니다.

## 5. Recommended Scheduled Jobs
아래는 권장 cadence입니다. 시간은 모두 `America/New_York` 기준입니다.

### Intraday Provisional Jobs
- `open-1`: 09:40 ET
- `open-2`: 10:10 ET
- `midday-1`: 12:00 ET
- `midday-2`: 13:00 ET
- `power-hour-1`: 15:00 ET
- `power-hour-2`: 16:00 ET

권장 command:

```bash
cd /home/ubuntu/project/nasdaq-turnaround-screener && ./scripts/run_intraday_window.py --date <NY_DATE> --window-id <WINDOW_ID> --skip-install
```

예:

```bash
cd /home/ubuntu/project/nasdaq-turnaround-screener && ./scripts/run_intraday_window.py --date 2026-04-22 --window-id open-1 --skip-install
```

### Daily Final Job
- 권장 시각: 16:30 ET

권장 command:

```bash
cd /home/ubuntu/project/nasdaq-turnaround-screener && ./scripts/run_daily.py --date <NY_DATE> --use-staged-intraday --skip-install
```

예:

```bash
cd /home/ubuntu/project/nasdaq-turnaround-screener && ./scripts/run_daily.py --date 2026-04-22 --use-staged-intraday --skip-install
```

설명:
- daily final은 same-day intraday snapshot을 반영하려면 `--use-staged-intraday` 를 쓰는 것을 권장
- daily final artifact가 같은 날짜 provisional artifact보다 우선한다.

## 6. Example Cron Layout
아래는 Linux cron 문법 예시입니다. `OpenClaw` 가 다른 scheduler를 쓰더라도 같은 cadence만 유지하면 됩니다.

```cron
CRON_TZ=America/New_York

40 9  * * 1-5 cd /home/ubuntu/project/nasdaq-turnaround-screener && ./scripts/run_intraday_window.py --date $(TZ=America/New_York date +\%F) --window-id open-1 --skip-install
10 10 * * 1-5 cd /home/ubuntu/project/nasdaq-turnaround-screener && ./scripts/run_intraday_window.py --date $(TZ=America/New_York date +\%F) --window-id open-2 --skip-install
0  12 * * 1-5 cd /home/ubuntu/project/nasdaq-turnaround-screener && ./scripts/run_intraday_window.py --date $(TZ=America/New_York date +\%F) --window-id midday-1 --skip-install
0  13 * * 1-5 cd /home/ubuntu/project/nasdaq-turnaround-screener && ./scripts/run_intraday_window.py --date $(TZ=America/New_York date +\%F) --window-id midday-2 --skip-install
0  15 * * 1-5 cd /home/ubuntu/project/nasdaq-turnaround-screener && ./scripts/run_intraday_window.py --date $(TZ=America/New_York date +\%F) --window-id power-hour-1 --skip-install
0  16 * * 1-5 cd /home/ubuntu/project/nasdaq-turnaround-screener && ./scripts/run_intraday_window.py --date $(TZ=America/New_York date +\%F) --window-id power-hour-2 --skip-install
30 16 * * 1-5 cd /home/ubuntu/project/nasdaq-turnaround-screener && ./scripts/run_daily.py --date $(TZ=America/New_York date +\%F) --use-staged-intraday --skip-install
```

주의:
- 위 예시는 `월-금` 만 실행합니다. 실제 미국 휴장일 필터가 가능하면 그 필터를 쓰는 쪽이 더 낫습니다.
- `run_intraday_window.py` 는 slot 라벨별로 full-universe 재수집을 수행합니다. shard 분할 수집이 아닙니다.

## 7. Consumer Paths
`OpenClaw` 가 읽어야 할 stable path는 아래 두 개입니다.

- daily final: `output/daily/latest/alert-events.json`
- intraday provisional: `output/intraday/<NY_DATE>/latest-alert-events.json`

권장 정책:
- intraday provisional은 slot 실행 직후 읽기
- daily final은 장 마감 후 daily run 성공 직후 읽기
- 같은 날짜에 daily final이 존재하면 daily final을 authoritative artifact로 본다.

## 8. CLI Success Signals
성공 시 stdout에서 아래 경로들을 확인할 수 있습니다.

### `run`
- `Alert events: ...`
- `Stable alert entrypoint: ...`

### `collect-window`
- `Provisional alert events: ...`
- `Stable provisional alert entrypoint: ...`

즉 `OpenClaw` 는 process exit code뿐 아니라, 성공 로그에 stable path가 찍혔는지도 같이 확인할 수 있습니다.

## 9. Failure Semantics
- `Alert sidecar generation failed: ...` 가 출력되면 non-zero exit로 본다.
- daily / intraday 모두 alert sidecar 생성 실패는 non-zero exit다.
- 다만 raw report / raw collection artifact는 sidecar 실패 이전에 이미 남아 있을 수 있다.
- intraday에서 Twelve Data 일일 크레딧 소진은 process crash가 아니라 metadata 기록 후 종료될 수 있다.

운영에서 같이 봐야 할 필드:
- `collection-metadata.json` 의 `failed_count`
- `collection-metadata.json` 의 `skipped_due_to_credit_exhaustion_count`
- `run-metadata.json` 의 `notes`
- alert sidecar의 `summary.quality_gate`

## 10. Delivery Policy For OpenClaw
권장 consumer policy는 아래와 같습니다.

- `quality_gate == "block"` 이면 Telegram 전송 금지
- `quality_gate == "warn"` 이면 digest 위주로 보수적으로 전송
- `quality_gate == "pass"` 이면 normal delivery 가능
- dedupe는 `event.dedupe_key` 기준
- provisional과 final이 같은 ticker에 대해 모두 존재할 수 있으므로, final을 우선한다.

## 11. Recommended Handoff Message
아래 블록을 그대로 `OpenClaw` 쪽에 전달하면 됩니다.

```text
다음 저장소를 America/New_York 기준으로 cron 등록해 주세요.

repo root:
/home/ubuntu/project/nasdaq-turnaround-screener

one-time bootstrap:
cd /home/ubuntu/project/nasdaq-turnaround-screener
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'

scheduled jobs:
- 09:40 ET: ./scripts/run_intraday_window.py --date <NY_DATE> --window-id open-1 --skip-install
- 10:10 ET: ./scripts/run_intraday_window.py --date <NY_DATE> --window-id open-2 --skip-install
- 12:00 ET: ./scripts/run_intraday_window.py --date <NY_DATE> --window-id midday-1 --skip-install
- 13:00 ET: ./scripts/run_intraday_window.py --date <NY_DATE> --window-id midday-2 --skip-install
- 15:00 ET: ./scripts/run_intraday_window.py --date <NY_DATE> --window-id power-hour-1 --skip-install
- 16:00 ET: ./scripts/run_intraday_window.py --date <NY_DATE> --window-id power-hour-2 --skip-install
- 16:30 ET: ./scripts/run_daily.py --date <NY_DATE> --use-staged-intraday --skip-install

consumer paths:
- daily final: output/daily/latest/alert-events.json
- intraday provisional: output/intraday/<NY_DATE>/latest-alert-events.json

delivery policy:
- quality_gate == block 이면 미전송
- dedupe_key 기준 중복 억제
- daily final이 provisional보다 우선
```
