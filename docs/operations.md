# Operations Runbook

## 1. Manual bootstrap
프로젝트 루트에서 한 번만 준비합니다.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest
```

## 2. Manual run
기본 CLI를 직접 실행해도 되고, 일상 운영용 runner를 써도 됩니다.

### Direct CLI
```bash
. .venv/bin/activate
python -m screener.cli.main run --date 2026-04-21 --output-dir output/manual-2026-04-21
```

### Cron-friendly intraday window runner
```bash
python scripts/run_intraday_window.py --date 2026-04-21 --window-id open-1 --skip-install
```

runner 동작:
- `.venv` 가 없으면 생성합니다.
- 필요하면 `pip install -e '.[dev]'` 로 로컬 환경을 맞춥니다.
- `SCREENER_INTRADAY_COLLECTOR_COMMAND` 또는 `--collector-command` 템플릿에 `date`, `window_id`, `output_dir`, `python`, `project_root` 를 주입합니다.
- 기본 output은 `output/intraday/YYYY-MM-DD/<window-id>/` 입니다.
- collector 구현은 다른 branch/module이 담당하고, 이 runner는 cron에서 한 window를 안정적으로 호출하는 thin wrapper만 제공합니다.

예시:
```bash
export SCREENER_INTRADAY_COLLECTOR_COMMAND='{python} -m screener.cli.collect_intraday --date {date} --window-id {window_id} --output-dir {output_dir}'
python scripts/run_intraday_window.py --window-id midday-1 --skip-install
python scripts/run_intraday_window.py --date 2026-04-21 --window-id power-hour-2 --collector-command '{python} -m custom.collector --date {date} --window {window_id} --out {output_dir}'
```

### Cron-friendly daily runner
```bash
python scripts/run_daily.py --date 2026-04-21
python scripts/run_daily.py --date 2026-04-21 --use-staged-intraday
```

runner 동작:
- `.venv` 가 없으면 생성합니다.
- 기본적으로 `pip install -e '.[dev]'` 로 로컬 환경을 맞춥니다.
- 결과를 `output/daily/YYYY-MM-DD/` 아래에 씁니다.
- `--use-staged-intraday` 를 주면 `output/intraday/YYYY-MM-DD/window-*/run-*/` 에서 가장 최근 staged snapshot을 읽어 같은 날짜 latest quote를 우선 반영합니다. 필요 시 `--intraday-output-root` 또는 `SCREENER_INTRADAY_OUTPUT_ROOT` 로 root를 바꿀 수 있습니다.
- 성공 시 `output/daily/latest` 를 가장 최근 run으로 갱신합니다.
- 이미 의존성이 준비된 환경이면 `--skip-install` 로 설치 단계를 건너뛸 수 있습니다.

예시:
```bash
python scripts/run_daily.py --date 2026-04-21 --skip-install
python scripts/run_daily.py --dry-run --skip-install
```

## 3. Intended OpenClaw cron usage
이 저장소에서는 cron 자체를 만들지 않습니다. orchestrator가 아래 형태로 호출하면 됩니다.

### Recommended 6-run intraday cadence
권장 window는 아래 6개입니다.
- `open-1`: 개장 직후 첫 수집
- `open-2`: opening volatility가 조금 가라앉은 뒤 재확인
- `midday-1`
- `midday-2`
- `power-hour-1`
- `power-hour-2`: 마감 직전 final staged snapshot

8회 대신 6회를 기본으로 두는 이유:
- Twelve Data quota와 retry budget을 더 보수적으로 관리하기 쉽습니다.
- 장초반/장후반 핵심 구간은 유지하면서 noon 영역은 과도하게 잘게 쪼개지 않습니다.
- cron/job 수가 줄어 장애 triage와 로그 확인이 단순해집니다.
- 최종 의사결정은 daily screener 리포트에서 이루어지므로, 장중 snapshot은 보강 데이터 역할이면 충분합니다.

### Execution shape
```bash
cd /path/to/nasdaq-screener-ops && python scripts/run_intraday_window.py --window-id open-1 --skip-install
cd /path/to/nasdaq-screener-ops && python scripts/run_daily.py --skip-install
```

흐름:
1. OpenClaw cron이 장중에는 window별 collector wrapper를 실행합니다.
2. 각 run이 `output/intraday/YYYY-MM-DD/<window-id>/` 아래에 staged artifacts를 남깁니다.
3. 장 마감 후 daily runner가 일봉 스크리닝과 report 생성을 수행합니다.
4. OpenClaw가 `output/daily/latest/` 또는 해당 날짜 디렉터리를 읽어 요약 전달합니다.

환경 knob:
- `SCREENER_INTRADAY_WINDOW_IDS`: 기본 6-window 목록 override
- `SCREENER_INTRADAY_OUTPUT_ROOT`: 장중 snapshot root override
- `SCREENER_INTRADAY_COLLECTOR_COMMAND`: collector command template override

## 4. Secrets policy
- Oracle SQL, Mongo, API key 등 credential은 OpenClaw secrets에서 관리
- repo, docs, test fixture에 credential 저장 금지
- `.env.local`은 local experimentation 용도로만 사용하고 gitignore 유지
- `TWELVE_DATA_API_KEY` 같은 provider secret은 cron 환경 또는 OpenClaw secret injection으로 주입

## 5. Logging and outputs
장중 기본 산출물 위치:
- `output/intraday/YYYY-MM-DD/<window-id>/...`

일별 기본 산출물:
- `daily-report.md`
- `daily-report.json`
- `run-metadata.json`

기본 로그/stdout:
- intraday run date / window id / output dir / collector command
- daily run date
- candidate count
- artifact paths
- runner 기준 latest path

## 6. Exit semantics
- `0`: run success
- non-zero: Python/CLI failure, dependency install failure, or upstream/provider failure

운영에서는 non-zero exit를 그대로 감지해 retry 또는 alert 판단에 사용하면 됩니다.
