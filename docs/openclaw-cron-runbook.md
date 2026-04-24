# OpenClaw Cron Runbook

이 문서는 `OpenClaw` 쪽 운영자에게 그대로 전달해도 되는 수준의 cron 등록 및 소비(run + read) 지침입니다. 기준 저장소는 `nasdaq-turnaround-screener` 이고, 이 저장소는 `alert-events.json` producer 역할만 맡습니다. Telegram delivery와 실제 cron orchestration은 `OpenClaw` 가 담당합니다.

## 1. Scope
- 이 저장소가 생성하는 artifact:
  - daily final sidecar: `output/daily/latest/alert-events.json`
  - intraday provisional sidecar: `output/intraday/<NY_DATE>/latest-alert-events.json`
- `OpenClaw` 가 해야 하는 일:
  - America/New_York 거래일 기준으로 producer job을 정기 실행
  - stable consumer entrypoint를 읽는 consumer job을 별도로 운영
  - `quality_gate`, `event_type`, `dedupe_key` 기준으로 Telegram delivery 판단

핵심 원칙:
- **producer와 consumer를 분리**합니다.
- screener run job은 artifact와 sidecar를 만드는 역할만 맡습니다.
- OpenClaw consumer job은 stable sidecar를 여러 번 읽어도 안전한 idempotent reader 역할을 맡습니다.
- repo 내부 `output/alerts/YYYY-MM-DD/alert-state.json` 은 producer가 다음 sidecar를 만들 때 쓰는 내부 상태입니다. Telegram delivery dedupe 상태와는 별개입니다.

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
uv sync --extra dev
```

Oracle SQL persistence를 쓸 경우에만 아래를 1회 추가합니다.

```bash
cd /home/ubuntu/project/nasdaq-turnaround-screener
uv run python -m screener.cli.main init-oracle-schema
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

### Producer Jobs
producer는 screener를 실행해 raw artifact와 stable sidecar를 갱신합니다. producer는 delivery 판단을 하지 않아야 합니다.

#### Intraday Provisional Producers
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

#### Daily Final Producer
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
- daily final artifact가 같은 날짜 provisional artifact보다 우선합니다.

### Consumer Jobs
consumer는 producer가 이미 만든 stable sidecar를 읽고, 새 dedupe key가 있을 때만 Telegram delivery를 수행합니다.

#### Daily Consumer
- 권장 시각: 16:35 ET, 16:40 ET, 16:45 ET
- 읽는 경로: `output/daily/latest/alert-events.json`
- local consumer state 예시: `/home/ubuntu/clawd/state/screener-daily-consumer.json`

권장 동작:
- `alert-events.json` 이 없거나 malformed면 조용히 종료
- `summary.quality_gate == "block"` 이면 조용히 종료
- `digest_alert` 우선
- 선택한 event의 `dedupe_key` 가 local consumer state와 같으면 조용히 종료
- 새 key면 state를 갱신한 뒤 Telegram delivery

#### Intraday Consumer
- 권장 시각: 장중 5~10분 cadence, 또는 각 provisional producer 직후 1~2회 재시도
- 읽는 경로: `output/intraday/<NY_DATE>/latest-alert-events.json`
- local consumer state 예시: `/home/ubuntu/clawd/state/screener-intraday-consumer.json`

권장 동작:
- provisional은 보수적으로 소비합니다.
- `summary.quality_gate == "pass"` 일 때만 normal delivery를 고려합니다.
- `warn` 이면 짧은 caution digest만 허용하거나 skip 합니다.
- 같은 날짜 daily final이 이미 존재하면 daily final을 authoritative artifact로 우선합니다.

## 6. Example Cron Layout
아래는 Linux cron 문법 예시입니다. `OpenClaw` 가 다른 scheduler를 쓰더라도 같은 cadence만 유지하면 됩니다.

producer와 consumer를 분리한 예시입니다.

```cron
CRON_TZ=America/New_York

# producers
40 9  * * 1-5 cd /home/ubuntu/project/nasdaq-turnaround-screener && ./scripts/run_intraday_window.py --date $(TZ=America/New_York date +\%F) --window-id open-1 --skip-install
10 10 * * 1-5 cd /home/ubuntu/project/nasdaq-turnaround-screener && ./scripts/run_intraday_window.py --date $(TZ=America/New_York date +\%F) --window-id open-2 --skip-install
0  12 * * 1-5 cd /home/ubuntu/project/nasdaq-turnaround-screener && ./scripts/run_intraday_window.py --date $(TZ=America/New_York date +\%F) --window-id midday-1 --skip-install
0  13 * * 1-5 cd /home/ubuntu/project/nasdaq-turnaround-screener && ./scripts/run_intraday_window.py --date $(TZ=America/New_York date +\%F) --window-id midday-2 --skip-install
0  15 * * 1-5 cd /home/ubuntu/project/nasdaq-turnaround-screener && ./scripts/run_intraday_window.py --date $(TZ=America/New_York date +\%F) --window-id power-hour-1 --skip-install
0  16 * * 1-5 cd /home/ubuntu/project/nasdaq-turnaround-screener && ./scripts/run_intraday_window.py --date $(TZ=America/New_York date +\%F) --window-id power-hour-2 --skip-install
30 16 * * 1-5 cd /home/ubuntu/project/nasdaq-turnaround-screener && ./scripts/run_daily.py --date $(TZ=America/New_York date +\%F) --use-staged-intraday --skip-install

# monthly threshold tuning — 매월 첫 월요일 17:30 ET (장 마감 후)
# proposal JSON만 생성. tiering.py 반영은 사람이 검토 후 수동으로 수행.
30 17 1-7 * 1 cd /home/ubuntu/project/nasdaq-turnaround-screener && uv run python -m screener.cli.main tune --start-date $(TZ=America/New_York date -d "6 months ago" +\%F) --end-date $(TZ=America/New_York date +\%F) --output-dir output/tuning --skip-install 2>&1 | tee -a output/tuning/tune-cron.log

# daily consumer retries
35,40,45 16 * * 1-5 /path/to/openclaw-daily-consumer
```

주의:
- 위 예시는 `월-금` 만 실행합니다. 실제 미국 휴장일 필터가 가능하면 그 필터를 쓰는 쪽이 더 낫습니다.
- `run_intraday_window.py` 는 slot 라벨별로 full-universe 재수집을 수행합니다. shard 분할 수집이 아닙니다.
- 월간 튜닝 크론은 proposal만 생성하며, `tiering.py` 를 자동으로 수정하지 않습니다. 반영은 `scripts/apply_tuning_proposal.py --write` 를 사람이 직접 실행해야 합니다.

## 7. Consumer Paths
`OpenClaw` 가 읽어야 할 stable path는 아래 두 개입니다.

- daily final: `output/daily/latest/alert-events.json`
- intraday provisional: `output/intraday/<NY_DATE>/latest-alert-events.json`

중요:
- consumer는 raw report JSON이 아니라 **stable sidecar path** 를 우선 읽습니다.
- consumer는 한 번만 실행하는 것이 아니라, **sidecar 생성 시점 이후 여러 번 돌아도 안전한 방식** 으로 운영하는 편이 맞습니다.
- 이때 idempotency 기준은 `event.dedupe_key` 입니다.
- OpenClaw는 repo 내부 `output/alerts/YYYY-MM-DD/alert-state.json` 을 Telegram dedupe state로 재사용하지 말고, 별도의 local consumer state를 둬야 합니다.

권장 정책:
- intraday provisional은 slot 실행 직후 + 짧은 재시도 cadence로 읽기
- daily final은 장 마감 후 daily producer 성공 직후 + 1~2회 재시도 cadence로 읽기
- 같은 날짜에 daily final이 존재하면 daily final을 authoritative artifact로 봅니다.

## 8. CLI Success Signals
성공 시 stdout에서 아래 경로들을 확인할 수 있습니다.

### `run`
- `Alert events: ...`
- `Stable alert entrypoint: ...`

### `collect-window`
- `Provisional alert events: ...`
- `Stable provisional alert entrypoint: ...`

즉 producer 쪽에서는 process exit code뿐 아니라, 성공 로그에 stable path가 찍혔는지도 같이 확인할 수 있습니다.
consumer 쪽에서는 이 stdout을 직접 믿기보다 stable sidecar path를 다시 읽는 편이 더 안전합니다.

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
- `quality_gate == "warn"` 이면 digest 위주로 보수적으로 전송하거나 skip
- `quality_gate == "pass"` 이면 normal delivery 가능
- dedupe는 `event.dedupe_key` 기준
- provisional과 final이 같은 ticker에 대해 모두 존재할 수 있으므로, final을 우선합니다.
- daily는 `digest_alert` 우선 소비를 기본값으로 두는 편이 안정적입니다.
- consumer local state는 최소한 `last_daily_dedupe_key` 또는 `last_intraday_dedupe_key`, `last_run_date`, `last_event_type`, `updated_at` 정도는 저장하는 편이 좋습니다.

## 11. OpenClaw Implementation Note
별도 daemon 없이도 OpenClaw 기본 툴만으로 consumer 구현이 가능합니다.

가능한 기본 구성:
- producer job: `exec` 로 screener runner 실행
- consumer job: `read` 로 stable sidecar 읽기
- consumer dedupe state: `write` 로 local JSON 저장
- delivery: cron job의 announce delivery 또는 일반 agent 응답 사용

즉 새 서비스보다 **producer cron + consumer cron + local consumer state file** 구조를 권장합니다.

## 12. Recommended Handoff Message
아래 블록을 그대로 `OpenClaw` 쪽에 전달하면 됩니다.

```text
다음 저장소를 America/New_York 기준으로 cron 등록해 주세요.

repo root:
/home/ubuntu/project/nasdaq-turnaround-screener

one-time bootstrap:
cd /home/ubuntu/project/nasdaq-turnaround-screener
uv sync --extra dev

scheduled jobs:
- producer 09:40 ET: ./scripts/run_intraday_window.py --date <NY_DATE> --window-id open-1 --skip-install
- producer 10:10 ET: ./scripts/run_intraday_window.py --date <NY_DATE> --window-id open-2 --skip-install
- producer 12:00 ET: ./scripts/run_intraday_window.py --date <NY_DATE> --window-id midday-1 --skip-install
- producer 13:00 ET: ./scripts/run_intraday_window.py --date <NY_DATE> --window-id midday-2 --skip-install
- producer 15:00 ET: ./scripts/run_intraday_window.py --date <NY_DATE> --window-id power-hour-1 --skip-install
- producer 16:00 ET: ./scripts/run_intraday_window.py --date <NY_DATE> --window-id power-hour-2 --skip-install
- producer 16:30 ET: ./scripts/run_daily.py --date <NY_DATE> --use-staged-intraday --skip-install
- daily consumer 16:35/16:40/16:45 ET: read stable daily sidecar and deliver only when dedupe_key is new

consumer paths:
- daily final: output/daily/latest/alert-events.json
- intraday provisional: output/intraday/<NY_DATE>/latest-alert-events.json

consumer state:
- do not reuse repo output/alerts/YYYY-MM-DD/alert-state.json for Telegram dedupe
- keep a separate local consumer state file

delivery policy:
- quality_gate == block 이면 미전송
- dedupe_key 기준 중복 억제
- daily consumer는 digest_alert 우선
- daily final이 provisional보다 우선
```
