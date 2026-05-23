# 개선 아이디어 서베이 (2026-04-24)

현재 코드베이스(`src/screener/` 기준 약 4.8K LOC)를 훑고 도출한 개선/확장 후보입니다.
각 항목은 실제 파일 경로와 함께 기록했고, 진척 상태는 필요 시 이 문서에서 업데이트합니다.

관련 상세 문서:
- [proposals/backtest-feedback-loop.md](proposals/backtest-feedback-loop.md) — 1번 상세 제안
- [proposals/backtest-feedback-loop-plan.md](proposals/backtest-feedback-loop-plan.md) — 1번 개발 계획서

---

## High-impact

### 1. 백테스트 결과 → 스코어링 파라미터 자동 튜닝 루프 ⭐
- **현재 상태**: `src/screener/backtest.py`가 tier별 / score_cutoff별 / daily top-N별 forward return을 계산해 `output/backtests/<run>/backtest-summary.json`에 저장. 결과는 artifact에만 쌓이고, `src/screener/scoring/thresholds.py`와 `src/screener/scoring/tiering.py`의 상수값은 수동으로만 조정됨.
- **개선**: 주기적(예: 월 1회) walk-forward 백테스트 → threshold/가중치 그리드서치 → 베스트 파라미터를 `scoring/thresholds.py`에 반영할 수 있는 JSON으로 출력하는 닫힌 루프.
- **근거 효과**: 파라미터 드리프트 자동 방어. 시스템이 스스로 개선.
- **상세**: [proposals/backtest-feedback-loop.md](proposals/backtest-feedback-loop.md) 참고.

### 2. Universe 확장 (Russell 2000 / S&P 500 추가)
- **현재 상태**: `src/screener/universe/loader.py` 는 universe-agnostic 구조이나 실 구현은 `nasdaq100.py` / `nasdaq100_names.py` 뿐.
- **개선**: Russell 2000 로더 추가. turnaround edge는 소형주 쪽이 크다는 학계/실무 근거가 강함.
- **주의**: 유니버스가 20배 커지므로 Twelve Data credit budget 재설계 필요 (`config.py: DEFAULT_INTRADAY_OUTPUT_ROOT` 인근 설정).

### 3. Data provider 이중화
- **현재 상태**: `src/screener/data/market_data.py` 단일 Twelve Data 의존. yfinance fallback은 `_pipeline/core.py`의 intraday provisional 경로에만 있음.
- **개선**: primary 실패 시 yfinance 또는 stooq로 graceful degrade. `run-metadata.json`에 사용 provider 기록.

---

## Mid-impact

### 4. Alert 품질 게이트 강화
- **현재 상태**: `src/screener/alerts/policy.py` — 개수·중복·쿨다운 위주.
- **개선**: 섹터 집중도 게이트, 시장 regime 게이트 (QQQ MA / VIX threshold), 후보 간 상관 게이트. 다운마켓에서 watchlist가 수십 개로 폭주하는 현상 완화.
- **관측 근거**: 2026-04-23 런에서 40건 중 30건이 watchlist로 쏠림.

### 5. Earnings 근접 필터 개선
- **현재 상태**: `src/screener/data/earnings.py` — T-5 cutoff + penalty 단일 룰 (`thresholds.py: EARNINGS_NEAR_TERM_DAYS`).
- **개선**: post-earnings drift 로직 추가 — 실적 직후 gap 방향/volume 조합으로 turnaround 시점 품질을 상향.

### 6. 빈 intraday 윈도우 디렉터리 제거
- **현재 상태**: `scripts/run_intraday_window.py:80`의 `output_dir.mkdir(parents=True, exist_ok=True)`가 `open-1` / `midday-1` 등을 매 실행 생성. 기본 collector 커맨드 템플릿(`intraday_ops.py:17`)은 `{output_root}`에 쓰기 때문에 이 디렉터리는 항상 비어 있음.
- **개선**: mkdir 제거 또는 커맨드 템플릿을 `{output_dir}` 사용으로 통일. 현재는 단순 쓰레기.

---

## Nice-to-have

### 7. Daily report Markdown에 전일 후보 outcome 섹션
- **현재 상태**: `src/screener/reporting/markdown.py`는 당일 후보만 렌더링. 전일 watchlist/buy-review 후보가 실제로 어떻게 움직였는지는 백테스트 artifact에만 존재.
- **개선**: 전일 후보의 T+1 forward return 표를 상단에 추가. 사용자 눈에 피드백 루프가 보임.

### 8. Structured logging + run summary Prometheus export
- **현재 상태**: `run-metadata.json`은 있으나 OpenClaw 크론 환경에서 관측성은 약함.
- **개선**: `run-metadata.json`을 Prometheus textfile로 복제. alerting/대시보드 연결이 쉬워짐. `docs/openclaw-cron-runbook.md`에 통합.

---

## 판단 요약

ROI 상위 2개는 **1번 (피드백 루프)** 과 **4번 (alert 품질 게이트)**. 나머지는 방향은 맞으나 이 둘보다 체감 효과가 작거나 외부 의존(Russell 2000 credit budget 등)이 끼어듦.

진행 우선순위: **1 → 4 → 7 → 5 → 6 → 2 → 3 → 8** (사용자 확정 전 잠정).
