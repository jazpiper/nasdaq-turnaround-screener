# Operations Runbook

## 1. Bootstrap
```bash
uv sync --extra dev
uv run pytest
```

- OpenClaw는 정기 실행과 secret 주입을 맡고, 이 저장소는 batch 실행과 artifact 생성을 맡습니다.
- `uv.lock` 을 커밋해 운영/개발 환경의 dependency resolution을 고정합니다.
- 운영 기준 날짜는 항상 `America/New_York` 거래일입니다.

## 2. Daily Run
직접 CLI를 써도 되고 runner를 써도 됩니다.

```bash
uv run python -m screener.cli.main run --date 2026-04-21
uv run python -m screener.cli.main run --date 2026-04-21 --use-staged-intraday
uv run python -m screener.cli.main run --date 2026-04-21 --persist-oracle-sql
uv run python -m screener.cli.main run --date 2026-05-01 --tickers TSLA,INFQ,PLTR,RKLB,GOOGL,NVDA
uv run python -m screener.cli.main run --date 2026-05-01 --overlay-tickers SMCI,ARM --overlay-name ai-infra

uv run python scripts/run_daily.py --skip-install --persist-oracle-sql
uv run python scripts/run_daily.py --date ny-today --use-staged-intraday --skip-install --persist-oracle-sql
uv run python scripts/run_daily.py --date 2026-04-21 --skip-install
uv run python scripts/run_daily.py --date 2026-04-21 --use-staged-intraday --skip-install
uv run python scripts/run_daily.py --date 2026-05-01 --skip-install --universe-name user-watchlist --tickers TSLA,INFQ,PLTR,RKLB,GOOGL,NVDA
uv run python scripts/run_daily.py --date 2026-05-01 --skip-install --overlay-file config/hot-sector-overlay.txt --overlay-name hot-sector
uv run python scripts/run_daily.py --date 2026-05-01 --skip-install --tickers TSLA,NVDA --assistant-artifact-basename latest-user-watchlist-screener
```

daily runner는 `uv sync --extra dev` 기반 `.venv` 준비, `output/daily/YYYY-MM-DD/` 출력, `output/daily/latest` 갱신까지 처리합니다.
운영 wrapper의 `--date` 기본값은 현재 `America/New_York` 날짜입니다. `--date`를 생략하거나 `--date auto`/`--date ny-today`를 주면 UTC/KST 스케줄러에서도 NY 기준 날짜를 사용합니다. 명시적 `YYYY-MM-DD` 값은 그대로 보존됩니다.
- `run` CLI는 stdout에 `Run universe: ...` 및 `Data quality: nonempty=..., latest_date_mismatch=..., insufficient_history=...` 요약을 함께 출력합니다.
- `--tickers`/`--universe-tickers`를 명시하면 custom universe가 활성화되고 기본 이름은 `user-watchlist` 입니다. `--universe-name`으로 artifact metadata의 universe 이름을 바꿀 수 있으며, 이 옵션은 custom ticker list와 함께만 허용됩니다.
- ticker list는 comma-separated 입력을 trim/uppercase/`.`→`-` 정규화하고 중복을 순서 보존으로 제거합니다. 옵션을 주지 않으면 기존 NASDAQ-100 기본 동작과 output schema가 유지됩니다.
- `--overlay-tickers` 또는 `--overlay-file`은 기본 NASDAQ-100/custom universe에 hot-sector overlay ticker를 추가합니다. overlay file은 JSON/CSV/newline-separated text를 지원하고, `--overlay-name`은 output root suffix와 artifact metadata label에 쓰입니다.
- `scripts/run_daily.py`는 custom tickers 또는 overlay와 기본 `--output-root` 생략 조합에서 root를 `output/daily-user-watchlist`, `output/daily-user-watchlist-hot-sector`처럼 universe/overlay별로 분리해 `output/daily/latest`와 alert-state 간섭을 피합니다. 명시적으로 같은 `--output-root`를 주면 그 값을 따릅니다.
- custom ticker daily run은 성공 시 `output/assistant/latest-user-briefing-screener.{json,md}`도 함께 생성해 holdings/watchlist/big-tech용 compact briefing을 자동으로 갱신합니다.
- runner assistant briefing은 `--skip-assistant-briefing`으로 끌 수 있고, `--assistant-user-tickers`, `--assistant-output-dir`, `--assistant-artifact-basename`으로 대상 ticker와 artifact 위치/이름을 바꿀 수 있습니다. custom `--tickers` 실행에서는 `--assistant-user-tickers`를 따로 주지 않으면 custom ticker list가 briefing 대상이 됩니다.
- raw `screener run --tickers ... --output-dir ...`는 latest pointer를 갱신하지 않으므로, cron 소비 경로와 분리된 output dir을 직접 지정하는 편이 안전합니다.
- `daily-report.json` 과 `run-metadata.json` 에는 `planned_ticker_count`, `successful_ticker_count`, `failed_ticker_count`, `bars_nonempty_count`, `latest_bar_date_mismatch_count`, `insufficient_history_count`, `planned_tickers`, `market_data_provider_status` 가 함께 기록됩니다.
- `run-metadata.json` 과 `daily-report.json` 에는 `run_started_at`, `run_completed_at`, `run_duration_seconds`, `quality_gate`, `quality_gate_reasons`, `observability` 도 포함되어 실패/지연/품질 게이트 원인을 cron에서 추적할 수 있습니다.
- `scripts/run_daily.py` 는 비 dry-run 실행마다 dated output 디렉터리에 `cron-health.json` 을 기록하고 `output/daily/latest-cron-health.json` 을 마지막 시도 상태로 갱신합니다. 성공한 실행은 `output/daily/last-success.json` 도 갱신하므로 실패가 발생해도 마지막 정상 완료 시각과 해당 output dir을 확인할 수 있습니다. screener subprocess가 metadata 생성 전에 실패해도 `exit_code`, 실행 시간, `screener_subprocess_failed_before_metadata` reason을 남깁니다. `attention_required`/`attention_reasons`는 nonzero exit, `quality_gate` warn/block, metadata unreadable, 15분 초과 지연을 한 번에 추적합니다.
  - `market_data_provider_status` 는 source/provider별 `role`(`primary`/`fallback`), `status`(`ok`/`partial_success`/`rate_limited`/`failed`), ticker 성공/실패 count, `retry_count`, `used_cache`, `used_stale_cache`, `cooldown_active`, `fallback_provider`, 분류된 `error_kind`만 남깁니다.
  - raw URL, query string, API key, token, credential 원문은 provider status나 report에 기록하지 않습니다.
- daily run은 `daily-report.json` 옆에 `alert-events.json` 도 함께 생성합니다.
- OpenClaw는 daily consumer entrypoint로 `output/daily/latest/alert-events.json` 을 읽으면 됩니다.
- earnings calendar 또는 benchmark context fetch가 실패하면 run은 계속 진행하고, 사유는 `run-metadata.json` / `daily-report.json` 의 `notes` 에 남깁니다.
- 운영 모니터링에서는 `latest_bar_date_mismatch_count` 증가를 stale bar 징후로, `insufficient_history_count` 증가를 provider coverage 문제 징후로 먼저 보는 편이 안전합니다.

## 3. Assistant Briefing Artifacts
```bash
uv run python -m screener.cli.main build-assistant-briefing
uv run python -m screener.cli.main build-assistant-briefing \
  --report-path output/daily/latest/daily-report.json \
  --output-dir output/assistant \
  --user-tickers TSLA,INFQ,PLTR,RKLB,GOOGL,NVDA \
  --top-candidates 10
uv run python -m screener.cli.main build-assistant-briefing \
  --report-path output/daily/latest/daily-report.json \
  --output-dir output/assistant \
  --artifact-basename latest-user-watchlist-screener
```

- 기본 입력은 `output/daily/latest/daily-report.json` 입니다.
- 기본 출력은 `output/assistant/latest-user-briefing-screener.json` 와 `output/assistant/latest-user-briefing-screener.md` 입니다.
- `--artifact-basename latest-user-watchlist-screener`를 주면 기본 artifact를 덮어쓰지 않고 `latest-user-watchlist-screener.json` / `.md`를 씁니다.
- custom watchlist daily report에서 planned ticker가 data provider 실패(`data_failures`)로 빠진 경우, assistant briefing은 해당 ticker를 outside-universe가 아니라 `data_failure`로 표시합니다.
- 이 compact artifact는 personal assistant가 daily report 전체 schema를 직접 해석하지 않고 user tickers, missing/outside-universe tickers, top candidates, data-quality summary만 읽도록 만든 안정 진입점입니다.
- payload root에는 `source_contract`, `source_freshness`, `source_reliability`가 포함됩니다. `source_contract`는 입력 report 경로, report-level freshness, market-data reliability label을 요약하며, Markdown의 `Source / freshness / reliability` 섹션은 이 값을 우선 사용하고 누락 시 root `source` / `source_freshness` / `source_reliability`로 fallback합니다.
- assistant briefing의 Data quality 섹션은 daily report에 `market_data_provider_status`가 있으면 market data source 라벨, fallback, partial success, stale cache, classified error를 함께 표시합니다.
- candidate item(`user_tickers` 중 후보와 `top_candidates`)에는 설명 필드가 붙습니다.
  - `source_provenance`: 후보 단위 source provenance/freshness입니다. 기존 후보의 `source_provenance` 또는 `provenance` dict가 있으면 `source_type`, `source_name`, `source_timestamp`, `freshness_label`만 정규화해 사용합니다. 없으면 후보의 `source_type`/`evidence_source_type`/`filing_source_type`와 `source_timestamp`/`latest_source_timestamp`/`latest_source_date`/`filing_date`/`published_at`를 보고, 그래도 market/fallback 계열 timestamp가 없으면 daily report의 `generated_at` 또는 `date`로 fallback합니다. source type은 SEC filing, IR release, market data, fallback 중심으로 정규화되며 freshness는 official / market data / fallback 또는 report reliability label로 표시됩니다.
  - `sector`, `industry`, `relative_strength_context`, `sector_proxy`, `setup_context`: sector/QQQ/sector-proxy 상대 context입니다. `relative_strength_context`는 `stock_return_20d`, `qqq_return_20d`, `rel_strength_20d_vs_qqq`, `sector_return_20d`, `rel_strength_20d_vs_sector`를 후보 root 또는 `indicator_snapshot`에서 가져와 숫자만 반올림해 담습니다. `sector_proxy`는 후보 root/indicator snapshot의 `sector_proxy`, `sector_proxy_ticker`, `sector_etf`를 우선하고 없으면 sector 이름으로 기본 proxy map을 찾습니다. `setup_context`는 weak-sector rebound, sector-wide mean reversion, benchmark-relative rebound 등 사람이 읽을 분류입니다.
  - `risk_flags`: 후보의 `risk_flags` list를 dedupe/trim한 값이며, 없으면 기존 `risks` list로 fallback합니다.
  - `why_not_buy_review_qualified`: 왜 아직 buy-review로 단정하면 안 되는지 설명합니다. `tier == "buy-review"`이면 기술 조건은 충족했지만 valuation/business quality/catalyst 별도 확인이 필요하다고 적고, 그 외에는 `tier_reasons`가 있으면 review-stage reason 뒤에 붙이며 없으면 기본 stage reason을 씁니다.
  - `what_would_need_to_improve`: 다음에 무엇이 개선돼야 하는지 적습니다. `tier_reasons`와 `risk_flags`/`risks`를 합친 blocking item이 있으면 `해소 필요: ...`로 쓰고, buy-review면 현재 기술 신호와 리스크 상태 유지 및 별도 fundamental/catalyst 검증을 요구하며, 그 외에는 risk-adjusted score / 기술적 확인 / risk profile 개선으로 fallback합니다.
- Markdown artifact는 후보 summary 줄에 `source_provenance`와 sector-relative context를 inline으로 표시하고, 아래 보조 bullet에 `risk_flags`, `why_not_buy_review_qualified`, `what_would_need_to_improve`를 표시합니다. 비후보 user ticker에는 이 후보 설명 필드가 붙지 않고 review-stage / data-failure / outside-universe reason만 표시됩니다.
- `--dry-run` 은 source report를 읽고 briefing을 구성하지만 artifact를 쓰지 않습니다.
- 모든 신호는 technical/research 기반 decision-support 용도이며 buy/sell advice가 아닙니다.

## 4. Daily Top 3 Recommendation Artifacts
```bash
uv run python -m screener.cli.main build-daily-top3-recommendations
uv run python -m screener.cli.main build-daily-top3-recommendations \
  --daily-report-path output/daily/latest/daily-report.json \
  --db-path output/recommendations/recommendations.sqlite3 \
  --output-dir output/recommendations
```

- 입력은 기존 daily run이 만든 `daily-report.json` 입니다. 외부 API key가 없거나 새 daily fetch를 원하지 않는 경우에도 이미 생성된 fixture/기존 artifact 기반으로 재현 가능합니다.
- 출력은 `output/recommendations/<NY_DATE>/daily-top3-recommendations.json` 및 `.md` 입니다. Markdown은 Telegram cron/LLM consumer가 바로 읽기 쉽게 Top 3, 왜 이 3개인가, 주의점, DB 반영 상태 섹션을 포함합니다.
- SQLite DB 기본 경로는 `output/recommendations/recommendations.sqlite3` 입니다. 테이블은 `algorithm_versions`, `recommendation_runs`, `recommendations`, `recommendation_features`, `recommendation_outcomes` 입니다.
- 추천 snapshot은 선정 시점 가격, score/subscore/penalty, rationale, risk flags, data quality, source freshness, SPY/QQQ benchmark context, 원본 feature snapshot을 저장합니다.
- outcome row는 D+1/D+5/D+20/D+60을 `pending`으로 생성합니다. 사후 settlement 계산은 별도 후속 기능이며 현재 명령은 selection snapshot만 저장합니다.
- hard gate는 임박 실적(3일 이내), 심한 주봉 훼손, risk-adjusted score 누락을 제외합니다. 정렬은 `risk_adjusted_score desc`, `final_score desc`, `ticker asc` 입니다.
- 이 명령은 advisory artifact만 만들며 자동매수, 주문, 브로커 API 호출을 절대 수행하지 않습니다.

Cron prompt 초안:
```text
After the daily screener run succeeds, read output/daily/latest/daily-report.json and run:
uv run python -m screener.cli.main build-daily-top3-recommendations --daily-report-path output/daily/latest/daily-report.json --db-path output/recommendations/recommendations.sqlite3 --output-dir output/recommendations
Then send output/recommendations/<NY_DATE>/daily-top3-recommendations.md to the Telegram summary channel. Do not place trades or call broker APIs.
```

## 5. Intraday Collection
```bash
# raw CLI 기본값: 6분할 계획 중 1개 window, 8 credits/min
uv run python -m screener.cli.main collect-window --date 2026-04-21 --window-index 0
# raw CLI로 full-universe 재수집을 강제하려면 아래처럼 명시
uv run python -m screener.cli.main collect-window --date 2026-04-21 --window-index 0 --total-windows 1 --max-credits-per-minute 5
uv run python -m screener.cli.main collect-window --date 2026-04-21 --window-index 0 --persist-oracle-sql

# 운영 권장 entrypoint: wrapper
uv run python scripts/run_intraday_window.py --skip-install --window-id open-1 --persist-oracle-sql
uv run python scripts/run_intraday_window.py --date ny-today --window-id open-1 --skip-install --persist-oracle-sql
uv run python scripts/run_intraday_window.py --date 2026-04-21 --window-id open-1 --skip-install
uv run python scripts/run_intraday_window.py --date 2026-04-21 --window-id open-1 --skip-install --persist-oracle-sql
```

- 기본 장중 cadence는 `open-1`, `open-2`, `midday-1`, `midday-2`, `power-hour-1`, `power-hour-2` 의 6개 slot입니다.
- OpenClaw/cron wrapper인 `scripts/run_intraday_window.py` 는 각 slot마다 **NASDAQ-100 전체를 다시 수집**합니다. `open-1` 이 17개만 담당하는 식의 분할 수집은 더 이상 기본 동작이 아닙니다.
- bare `collect-window --window-index 0` 예시는 raw CLI 기본값을 보여주는 용도입니다. 이 경우 실제 동작은 `total_windows=6`, `max_credits_per_minute=8` 이므로 NASDAQ-100 전체가 아니라 1개 shard만 수집합니다.
- wrapper 기본값은 `collect-window --window-index 0 --total-windows 1 --max-credits-per-minute 5` 이며, Twelve Data free plan `8 credits/min` 대비 여유를 더 남겨 rate-limit 실패를 줄입니다.
- wrapper의 `--date` 기본값은 현재 `America/New_York` 날짜입니다. KST/UTC cron 또는 LLM prompt producer는 날짜를 직접 계산하지 말고 `--date`를 생략하거나 `--date ny-today`를 쓰면 됩니다.
- 운영에서는 wrapper 사용을 기본값으로 두고, raw `collect-window` CLI는 수동 분할 수집이나 ad-hoc 점검 용도로 보는 편이 안전합니다.
- 실제 artifact는 `output/intraday/YYYY-MM-DD/window-XX-of-YY/run-.../` 아래에 기록됩니다. wrapper 기본값에서는 `window-01-of-01` 아래에 쌓입니다.
- `collection-metadata.json` 에는 `planned_tickers`, `minute_batches`, `successes`, `failures`, `skipped_due_to_credit_exhaustion`, `remaining_tickers`, `uncollected_tickers` 와 집계 count가 함께 기록됩니다.
- 각 completed intraday run은 `collected-quotes.json` 옆에 provisional `alert-events.json` 도 함께 생성합니다.
- OpenClaw는 intraday consumer entrypoint로 `output/intraday/<NY_DATE>/latest-alert-events.json` 을 읽으면 됩니다.
- `collect-window` CLI stdout은 `Failures` 만 바로 보여주므로, 일일 크레딧 소진으로 인한 미시도 ticker 수는 `collection-metadata.json` 의 `skipped_due_to_credit_exhaustion_count` 로 확인하는 편이 정확합니다.

## 6. Backtest
```bash
uv run python -m screener.cli.main backtest --start-date 2026-03-01 --end-date 2026-04-21
uv run python -m screener.cli.main backtest --start-date 2026-03-01 --end-date 2026-04-21 --horizons 5,10,20
```

- candidate 발생 시점별 점수와 `N` 거래일 후 수익률을 CSV/JSON으로 남깁니다.
- artifact는 기본적으로 `output/backtests/` 아래에 생성됩니다.
- `generate_observations()` 가 분리되어 있어 tuning 루프가 동일 관찰치를 재활용합니다.

## 7. Threshold Tuning (Walk-Forward)

### 튜닝 실행
```bash
# walk-forward 그리드서치 (데이터 >= train_days + eval_days 거래일 시 자동 선택)
uv run python -m screener.cli.main tune \
  --start-date 2025-10-01 --end-date 2026-04-21

# 파라미터 직접 지정 예시
uv run python -m screener.cli.main tune \
  --start-date 2025-10-01 --end-date 2026-04-21 \
  --train-days 90 --eval-days 20 --stride 20 \
  --forward-horizon 10 --min-samples 5 --min-wins 2
```

산출물은 `output/tuning/<end-date>/` 아래에 생성됩니다.

- `tuning-walkforward.json`: 창별 in-sample best + OOS eval + 안정성 랭킹
- `tuning-proposal.json`: 최종 추천 파라미터 (status: `proposal` 또는 `no_proposal`)
- `tuning-diff.md`: 현재값 vs 제안값 한눈에 보기
- `tuning-grid.csv`: single-window fallback 시 전체 조합 점수 (walk-forward 미사용 시)

### Proposal 검토 및 적용

```bash
# 1단계: 드라이런으로 diff 확인 (파일 미수정)
uv run python scripts/apply_tuning_proposal.py output/tuning/<date>/tuning-proposal.json

# 2단계: 승인 후 tiering.py 반영 + 자동 pytest
uv run python scripts/apply_tuning_proposal.py output/tuning/<date>/tuning-proposal.json --write
```

- `--write` 없으면 아무 파일도 수정하지 않습니다.
- pytest 실패 시 `tiering.py` 는 자동 원복됩니다.
- 반영 후 반드시 git commit으로 이력을 남깁니다.

### 운영 cadence 권장
- 월 1회 (매월 첫 월요일 장 마감 후) 지난 6개월 구간으로 실행.
- proposal이 `no_proposal` 이면 현재 threshold가 적절하다는 신호로 해석.
- proposal 채택/거부 이력은 `output/tuning/<date>/decision.md` 에 수기 기록.

주의: 자동 적용 없음. 사람이 `tuning-diff.md` 를 검토하고 `--write` 를 명시적으로 실행해야 합니다.

## 8. Environment and Secrets
- `SCREENER_MARKET_DATA_PROVIDER`: daily provider override (`yfinance`, `twelve-data`, `finnhub`, `fmp`, 또는 `finnhub,twelve-data,fmp,yfinance` 같은 comma-separated fallback chain). 기본값은 `finnhub,twelve-data,fmp,yfinance` 입니다.
- `TWELVE_DATA_API_KEY`: Twelve Data API key
- `TWELVE_DATA_BASE_URL`: Twelve Data endpoint override. API key가 query string으로 붙으므로 public routable `http(s)` endpoint만 허용되며, localhost/private IP/userinfo URL은 거부됩니다.
- `FINNHUB_API_KEY` 또는 `SCREENER_FINNHUB_API_KEY`: Finnhub API key
- `FMP_API_KEY`, `FINANCIAL_MODELING_PREP_API_KEY`, 또는 `SCREENER_FMP_API_KEY`: Financial Modeling Prep API key
- `SCREENER_EARNINGS_CALENDAR_PATH`: earnings calendar JSON path
- `SCREENER_DAILY_INTRADAY_SOURCE_MODE=prefer-staged`: same-day staged quote 병합 활성화
- `SCREENER_INTRADAY_WINDOW_IDS`: intraday window 목록 override
- `SCREENER_INTRADAY_OUTPUT_ROOT`: intraday artifact root override
- `SCREENER_INTRADAY_COLLECTOR_COMMAND`: intraday runner command template override
- `SCREENER_ORACLE_SQL_ENABLED=1`: Oracle SQL persistence 기본 활성화
- `ORACLE_DB_USER`, `ORACLE_DB_PASSWORD`, `ORACLE_DB_CONNECT_STRING`: Oracle SQL credential
- `SCREENER_ORACLE_SQL_USER`, `SCREENER_ORACLE_SQL_PASSWORD`, `SCREENER_ORACLE_SQL_CONNECT_STRING`: 기존/레거시 Oracle SQL credential alias. 같은 값이 둘 다 있으면 `ORACLE_DB_*` 가 우선합니다.
- `SCREENER_OPENCLAW_SECRETS_PATH` 또는 `OPENCLAW_SECRETS_PATH`: OpenClaw secrets file path override

환경변수가 없으면 기본적으로 `~/.openclaw/secrets.json` 에서 provider / Oracle credential을 읽습니다.

## 9. Oracle SQL Notes
```bash
uv run python -m screener.cli.main init-oracle-schema
```

- persistence write path는 더 이상 runtime DDL을 수행하지 않습니다.
- Oracle 저장을 쓰기 전에 `uv run python -m screener.cli.main init-oracle-schema` 를 1회 실행해 schema를 준비해야 합니다.
- `--persist-oracle-sql` 이 켜진 non-dry-run `run` / `collect-window` 는 데이터 수집 전에 Oracle credential/import/connectivity preflight를 먼저 실행합니다. credential 누락은 secret 값을 출력하지 않고 non-zero exit로 즉시 실패합니다.
- preflight가 성공한 뒤 DB가 중간에 장애를 일으키면 persistence 단계에서 non-zero exit가 날 수 있습니다. 이 경우 raw artifact가 이미 남아 있을 수 있으므로 producer 성공 기준은 process exit code와 `Oracle SQL run id`/`Oracle SQL collection id` 로그를 함께 확인합니다.
- `risk_adjusted_score` 같은 새 저장 컬럼이 추가된 배포 후에는 기존 DB에도 같은 명령을 다시 1회 실행해 additive migration을 적용해야 합니다.
- 이후 `--persist-oracle-sql` 은 insert만 수행합니다.

## 10. OpenClaw Usage
- 이 저장소는 cron 정의를 포함하지 않습니다. OpenClaw가 외부에서 명령을 호출하는 전제를 둡니다.
- 장중 수집은 `uv run python scripts/run_intraday_window.py --window-id <ID> --skip-install --persist-oracle-sql` 형태로 호출하면 됩니다. wrapper가 `America/New_York` 현재 날짜를 자동 적용합니다.
- 장 마감 후 daily run은 `uv run python scripts/run_daily.py --use-staged-intraday --skip-install --persist-oracle-sql` 형태로 호출하면 됩니다.
- Oracle을 쓰는 환경이면 bootstrap 단계에서 `uv run python -m screener.cli.main init-oracle-schema` 를 먼저 1회 실행해야 합니다.
- 이번 알고리즘/DB schema 변경처럼 새 Oracle 컬럼이 추가된 배포 뒤에는 OpenClaw producer cron을 재개하기 전에 `init-oracle-schema` 를 한 번 더 실행해야 합니다.
- OpenClaw가 읽어야 하는 daily 결과 진입점은 `output/daily/latest/alert-events.json` 입니다.
- daily report JSON/Markdown에는 candidate별 ticker와 company name이 함께 포함됩니다.
- intraday raw artifact는 daily run 보강용이지만, OpenClaw는 provisional consumer entrypoint `output/intraday/<NY_DATE>/latest-alert-events.json` 을 읽을 수 있습니다.
- same-day staged merge는 intraday metadata 전체를 읽는 것이 아니라, 각 run의 `completed_at` 또는 `started_at` 으로 최신 snapshot을 고른 뒤 `collected-quotes.json` 을 사용합니다.
- 운영에서는 `output/daily`, `output/intraday`, `output/alerts` 를 screener producer 계정만 쓸 수 있게 두는 것을 권장합니다. consumer는 stable sidecar를 읽기만 하고 내부 artifact/state를 수정하지 않아야 합니다.

## 11. OpenClaw Command Template
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

## 12. Exit and Failure Handling
- 일부 ticker fetch 실패는 metadata에 남기고 run 전체는 계속 진행합니다.
- daily market data fetch는 provider별 짧은 in-process cache/cooldown과 429 전용 retry/backoff를 적용합니다. `SCREENER_MARKET_DATA_PROVIDER=twelve-data,yfinance`처럼 fallback chain을 쓰면 primary 실패 ticker만 fallback provider에 넘기고 source별 상태를 숨기지 않습니다.
- Twelve Data가 일일 크레딧 소진(`run out of API credits for the day` 류) 응답을 주면, 해당 slot의 추가 ticker 호출을 즉시 중단하고 이후 planned ticker는 미시도 상태로 metadata에 남깁니다.
- metadata에서는 실제 호출 후 실패한 ticker는 `failures` 에 남기고, 아직 호출하지 못한 ticker는 `skipped_due_to_credit_exhaustion` 으로 별도 분리합니다.
- 위 크레딧 소진은 현재 구현상 process crash로 취급하지 않습니다. `collect-window` 는 artifact와 failure metadata를 남기고 종료하며, non-zero exit는 설정 오류나 Oracle persistence 실패 같은 시스템 오류에 주로 사용합니다.
- alert sidecar generation 실패는 non-zero exit로 처리합니다.
- alert sidecar generation이 실패하더라도 raw report / collection artifact는 이미 기록되어 남아 있을 수 있습니다.
- Oracle SQL credential 누락이나 persistence 실패는 non-zero exit로 올립니다.
- 운영 alert는 non-zero exit만 보지 말고 `collection-metadata.json` 의 `failed_count`, `skipped_due_to_credit_exhaustion_count`, `failures`, 또는 credit exhaustion failure reason 문자열도 함께 감시하는 편이 안전합니다.
