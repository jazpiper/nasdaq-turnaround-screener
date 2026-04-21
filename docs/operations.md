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

### Cron-friendly daily runner
```bash
python scripts/run_daily.py --date 2026-04-21
```

runner 동작:
- `.venv` 가 없으면 생성합니다.
- 기본적으로 `pip install -e '.[dev]'` 로 로컬 환경을 맞춥니다.
- 결과를 `output/daily/YYYY-MM-DD/` 아래에 씁니다.
- 성공 시 `output/daily/latest` 를 가장 최근 run으로 갱신합니다.
- 이미 의존성이 준비된 환경이면 `--skip-install` 로 설치 단계를 건너뛸 수 있습니다.

예시:
```bash
python scripts/run_daily.py --date 2026-04-21 --skip-install
python scripts/run_daily.py --dry-run --skip-install
```

## 3. Intended OpenClaw cron usage
이 저장소에서는 cron 자체를 만들지 않습니다. orchestrator가 아래 형태로 호출하면 됩니다.

```bash
cd /path/to/nasdaq-screener-ops && python scripts/run_daily.py --skip-install
```

흐름:
1. OpenClaw cron이 프로젝트 command 실행
2. runner가 날짜별 output directory 준비
3. 스크리너가 markdown/json/metadata artifact 생성
4. OpenClaw가 `output/daily/latest/` 또는 해당 날짜 디렉터리를 읽어 요약 전달

## 4. Secrets policy
- Oracle SQL, Mongo, API key 등 credential은 OpenClaw secrets에서 관리
- repo, docs, test fixture에 credential 저장 금지
- `.env.local`은 local experimentation 용도로만 사용하고 gitignore 유지
- `TWELVE_DATA_API_KEY` 같은 provider secret은 cron 환경 또는 OpenClaw secret injection으로 주입

## 5. Logging and outputs
기본 산출물:
- `daily-report.md`
- `daily-report.json`
- `run-metadata.json`

기본 로그/stdout:
- run date
- candidate count
- artifact paths
- runner 기준 latest path

## 6. Exit semantics
- `0`: run success
- non-zero: Python/CLI failure, dependency install failure, or upstream/provider failure

운영에서는 non-zero exit를 그대로 감지해 retry 또는 alert 판단에 사용하면 됩니다.
