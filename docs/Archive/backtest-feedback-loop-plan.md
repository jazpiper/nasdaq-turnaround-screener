# 개발 계획서: 백테스트 피드백 루프

작성일: 2026-04-24
상태: 계획 (Planning)
연관: [backtest-feedback-loop.md](backtest-feedback-loop.md)

---

## 0. 마일스톤 개요

| 단계 | 기간(예상) | 산출물 | 검증 |
|---|---|---|---|
| M1. 리팩터 준비 | 1일 | `backtest.py` 관찰치 생성/분류 분리 | 기존 pytest 그린 유지 |
| M2. 튜닝 MVP | 2-3일 | `screener/tuning/` 모듈 + CLI `tune` | 그리드 400조합 / 6개월 입력 10분 이내 |
| M3. Walk-forward | 1-2일 | 창별 best + stability 지표 | 합성 데이터 단위 테스트 |
| M4. Proposal & 승인 파이프라인 | 1일 | `tuning-proposal.json`, `tuning-diff.md`, `scripts/apply_tuning_proposal.py` | 드라이런에서 thresholds 미변경 확인 |
| M5. 운영 투입 | 0.5일 | OpenClaw 월간 크론 엔트리, 문서 갱신 | runbook dry-run |

총 예상: **~1주** 집중 작업.

---

## M1. 리팩터 준비

### 범위
- `src/screener/backtest.py`에서 관찰치 생성 파이프라인과 집계(`_summarize_*`)를 분리.
- `RankedCandidateScorer`에서 tier 컷오프를 **주입 가능한 파라미터**로 받도록 시그니처 확장 (현재는 `tiering.py` 상수 직접 참조).

### 구체 작업
1. `src/screener/scoring/tiering.py`에 `TierThresholds` dataclass 신설. 기본값은 기존 상수.
2. `classify_investability_tier(...)`가 `thresholds: TierThresholds | None = None`을 받도록 변경.
3. `_pipeline/core.py: RankedCandidateScorer`에서 주입 경로 추가. 기본은 `TierThresholds()`.
4. `backtest.py`에 `generate_observations(...)` 분리 — 스코어링만 하고 tier/집계는 후속 함수에서.

### 테스트
- 기존 `tests/test_backtest.py`, `tests/test_pipeline.py`, `tests/test_cli.py` 그대로 그린.
- 새로 추가: `tests/test_tiering.py`에서 `TierThresholds(buy_review_min_score=70)` 주입 시 분류가 달라지는지 확인.

### 리스크
- 기본값 시그니처 변경으로 인한 회귀. 기본 경로는 현상 유지이므로 테스트 위주로 방어.

---

## M2. 튜닝 MVP

### 범위
- `src/screener/tuning/` 패키지 신설.
- 그리드 400조합 × tier 재분류만으로 목적함수 계산 (관찰치 재사용).
- 단일 학습/평가 창에서 best 파라미터 도출까지.

### 파일
```
src/screener/tuning/
  __init__.py        # public export
  grid.py            # TierThresholdsGrid.iter() → Iterable[TierThresholds]
  objective.py       # objective(observations, thresholds) -> Score
  runner.py          # tune_single_window(...) 파사드
  report.py          # write_grid_csv / write_proposal_json
tests/
  test_tuning_grid.py
  test_tuning_objective.py
  test_tuning_runner.py
```

### CLI
- `src/screener/cli/main.py`에 `tune` 서브커맨드 추가.
- 옵션: `--start-date`, `--end-date`, `--output-dir` (기본 `output/tuning`), `--forward-horizon` (기본 10).

### 목적함수 v1
```
score = mean(buy_review forward_return @ horizon) - mean(QQQ forward_return @ horizon)
제약: sample_count >= 5
```
제약 미충족 조합은 `None` → 자동 탈락.

### 검증
- 합성 observations fixture로 "명백히 하위 조합이 최저 점수" 단위 테스트.
- NASDAQ-100 / 2026-03-01 ~ 2026-04-21 실입력에서 CLI end-to-end 실행.

---

## M3. Walk-forward & 안정성

### 범위
- 학습 90일 / 평가 20일 / stride 20일 슬라이딩.
- 창별 best → 전 창 rank 통계 (평균 rank, 베스트 등장 횟수, IR).
- 단일 창 우승 조합 자동 리젝트 (등장 창 수 < 2).

### 파일
- `src/screener/tuning/walkforward.py` — 창 분할 + 집계.
- `tests/test_tuning_walkforward.py`.

### 산출물 추가
```
output/tuning/<date>/
  tuning-walkforward.json    # 창별 best + 스코어 분포
  tuning-grid.csv            # 창 평균 스코어로 정렬
  tuning-proposal.json       # 최종 추천 (안정성 통과분)
```

### 검증
- 합성 데이터: 명백한 optimum이 존재하도록 설계된 observations에서 해당 조합이 뽑히는지.
- 실데이터: walk-forward 결과가 proposal 탈락 없이 적어도 1개 조합을 반환 (또는 "no proposal" 상태를 명시적으로 반환).

---

## M4. Proposal 적용 파이프라인

### 범위
- `scripts/apply_tuning_proposal.py` 신설.
- 입력: `tuning-proposal.json` 경로.
- 동작:
  1. 현재 `tiering.py` 상수 파싱.
  2. proposal과 diff 계산 → stdout/`tuning-diff.md`.
  3. `--write` 플래그 있으면 `tiering.py` 해당 라인만 교체 후 `uv run pytest` 실행.
  4. 테스트 통과 시 종료. 실패 시 원복.

### 안전장치
- 기본은 **드라이런**. `--write`가 명시적으로 필요.
- `scripts/`는 CI 대상 밖이라 pytest 수동 실행이 기본 workflow.
- 반영 이력은 git commit으로만 기록 (별도 ledger 불필요).

### 검증
- 드라이런이 파일을 수정하지 않는지 테스트.
- `--write`가 상수 이외 라인을 건드리지 않는지 (정확한 토큰 매칭).

---

## M5. 운영 투입

### 범위
- OpenClaw 월 1회 크론 엔트리: 매월 첫 월요일 05:30 ET에 지난 6개월 구간 튜닝 실행, proposal만 산출.
- 문서 갱신:
  - `docs/architecture.md`에 튜닝 루프 섹션 추가.
  - `docs/openclaw-cron-runbook.md`에 신규 크론 문서화.
  - `docs/operations.md`에 proposal 리뷰 절차 추가.

### 검증
- dry-run 크론으로 `output/tuning/<date>/tuning-proposal.json` 생성 확인.
- 첫 실 proposal은 사람이 반드시 검토 후 수동 반영.

---

## 작업 분할 (PR 단위)

1. **PR #1 — M1 리팩터**: `TierThresholds` dataclass 도입, 기본 동작 불변. 기존 테스트 그린.
2. **PR #2 — M2 튜닝 MVP**: 단일 창 그리드 + CLI `tune`.
3. **PR #3 — M3 walk-forward**: 창별 집계 + proposal 안정성 필터.
4. **PR #4 — M4 적용 스크립트**: `apply_tuning_proposal.py` + 드라이런 테스트.
5. **PR #5 — M5 문서 + 크론**: 운영 문서 + OpenClaw 엔트리.

각 PR은 단일 논리 변경만 포함하며 기존 커밋 규약(`feat: ...`, `docs: ...`)을 따른다.

## 검증 기준 (Definition of Done)

- [ ] `uv run pytest` 전 테스트 통과.
- [ ] `uv run python -m screener.cli.main tune --start-date 2025-10-01 --end-date 2026-04-21` 10분 이내 완료.
- [ ] `output/tuning/<date>/tuning-proposal.json`과 `tuning-diff.md`가 생성되고 사람이 읽을 수 있는 형식.
- [ ] `scripts/apply_tuning_proposal.py --dry-run`이 파일을 수정하지 않음.
- [ ] `docs/architecture.md`, `docs/operations.md`, `docs/openclaw-cron-runbook.md` 업데이트 완료.

## 향후 확장 (v2+)

- 스코어 구성 상수(예: `OVERSOLD_RSI_TRIGGER`, `VOLUME_HOT_RATIO`) 튜닝 대상 편입.
- 베이지안 최적화 도입 (`scikit-optimize`) — 차원 > 6일 때.
- 유니버스별 proposal 분리 (Russell 2000 확장 시).
- 시장 regime 기반 조건부 파라미터 (bull/bear 별 threshold 세트).
