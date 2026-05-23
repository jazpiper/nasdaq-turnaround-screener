# 제안: 백테스트 결과 → 스코어링 파라미터 피드백 루프

작성일: 2026-04-24
상태: 제안 (Proposed)
연관: [../improvements-2026-04-24.md](../improvements-2026-04-24.md) #1

---

## 1. 문제 정의

현재 스코어링 시스템은 수동 튜닝된 상수에 의존한다.

- `src/screener/scoring/thresholds.py` — 스코어 구성 요소별 max score / scale / penalty 상수 수십 개.
- `src/screener/scoring/tiering.py` — `BUY_REVIEW_MIN_SCORE = 60`, `BUY_REVIEW_MIN_REVERSAL = 15`, `BUY_REVIEW_MIN_VOLUME_RATIO = 0.8`, `BUY_REVIEW_MAX_RISK_COUNT = 3` 등 tier 결정 컷오프.

한편 `src/screener/backtest.py`는 이미 다음을 계산한다.

- tier별 forward return 요약 (`_summarize_by_tier`)
- score cutoff별 요약 (`_summarize_by_score_cutoff`)
- daily top-N 요약 (`_summarize_daily_top_n`)
- 산출물: `output/backtests/<run>/backtest-summary.json`, `backtest-observations.csv`

**단절**: 백테스트 결과는 artifact로만 남고, threshold 튜닝으로는 연결되지 않는다. 시장 regime이 바뀌면 컷오프가 뒤처진다.

## 2. 목표

1. **정량적 근거 있는 threshold 업데이트**: "왜 60점이 buy-review 컷오프인가?"에 대한 답을 walk-forward 백테스트 수치로 제시.
2. **재현 가능한 튜닝 파이프라인**: 월 1회 또는 수동 트리거 시, 동일 입력에서 동일 추천 파라미터가 나오도록 결정적(deterministic).
3. **안전한 배포**: 자동 적용이 아니라 **제안(proposal) JSON** 산출 → 사람이 승인 → `thresholds.py` 반영. 블랙박스 자가학습 지양.

**Non-goal**: 실시간/온라인 학습, 신경망 기반 스코어링, per-ticker 파라미터.

## 3. 접근 (Walk-Forward 그리드서치)

### 3.1 튜닝 대상 파라미터 (v1 범위)

우선 의사결정에 직접 영향을 주는 tier 컷오프만 먼저 다룬다.

| 파라미터 | 파일 | 현재값 | 그리드 후보 |
|---|---|---|---|
| `BUY_REVIEW_MIN_SCORE` | tiering.py | 60 | 50, 55, 60, 65, 70 |
| `BUY_REVIEW_MIN_REVERSAL` | tiering.py | 15 | 10, 12, 15, 18, 20 |
| `BUY_REVIEW_MIN_VOLUME_RATIO` | tiering.py | 0.8 | 0.6, 0.8, 1.0, 1.2 |
| `BUY_REVIEW_MAX_RISK_COUNT` | tiering.py | 3 | 2, 3, 4, 5 |

전체 조합 = 5 × 5 × 4 × 4 = 400. 허용 범위.

v2에서 `MINIMUM_TOTAL_SCORE`, `OVERSOLD_RSI_TRIGGER`, `VOLUME_HOT_RATIO` 등 스코어 산출 레벨 상수를 추가한다.

### 3.2 Walk-forward 스키마

- 학습창 (train): 과거 90 거래일
- 평가창 (eval): 다음 20 거래일
- 창 한 칸씩 슬라이드 (stride = 20일)
- 각 창별 최적 파라미터 → 전체 창에서 안정성 측정 (rank 평균, IR)

### 3.3 목적 함수

이 프로젝트는 리서치 스크리너이지 자동 매매가 아니다. 목적 함수는 **buy-review tier의 T+10 평균 forward return - QQQ 벤치마크 return**, 부가 제약:

- 샘플 수 ≥ 창당 5건 (과소 샘플 컷오프 자동 탈락)
- downside stdev 중앙값 ≤ 현 운영값의 1.2배 (리스크 무제한 상승 방지)

### 3.4 출력

```
output/tuning/<YYYY-MM-DD>/
  tuning-proposal.json     # 최적 파라미터 + 지표 + 신뢰구간
  tuning-grid.csv          # 전체 조합별 점수
  tuning-walkforward.json  # 창별 베스트
  tuning-diff.md           # 현재값 vs 제안값 diff (리뷰용)
```

## 4. 시스템 설계

### 4.1 신규 모듈

```
src/screener/tuning/
  __init__.py
  objective.py     # objective function + 제약
  grid.py          # 그리드 생성 + 조합 iteration
  walkforward.py   # 학습/평가 창 분할
  runner.py        # 전체 튜닝 실행 파사드
  report.py        # proposal JSON / diff MD 생성
```

### 4.2 재사용

- `backtest.py`의 `_run_observations()` / `_summarize_*()`를 재사용 가능하도록 리팩터 (현재는 한 번에 aggregate). 관찰치(observations) 생성과 파라미터별 re-scoring을 분리한다.
- **핵심 아이디어**: 관찰치 한 번만 생성 → 파라미터 변경에 따라 tier 재분류만 반복. 그리드 400 조합 × 재분류는 O(N) 가벼움.

### 4.3 CLI

```bash
uv run python -m screener.cli.main tune \
  --start-date 2025-10-01 --end-date 2026-04-21 \
  --train-days 90 --eval-days 20 --stride 20 \
  --output-dir output/tuning
```

### 4.4 배포 (사람 승인)

- `tuning-proposal.json`을 사람이 검토.
- 승인 시 `scripts/apply_tuning_proposal.py` 가 `thresholds.py` / `tiering.py`의 해당 상수만 rewrite 후 `uv run pytest` 재실행. 테스트 통과 시 PR 커밋용 패치 생성.

## 5. 리스크 & 완화

| 리스크 | 완화 |
|---|---|
| 과적합 (in-sample 베스트가 out-of-sample에서 무너짐) | walk-forward 창별 rank stability 지표. 단일 창 베스트는 리젝트. |
| 샘플 부족 (buy-review tier는 원래 희소) | 각 조합 최소 샘플 수 제약 + 부트스트랩 신뢰구간 병행. |
| 데이터 leak (earnings 갭 등) | backtest 관찰치 생성 시 기존 `_pipeline/core.py` 경로 재사용, forward return 계산에 T+1 open 이후만 사용. |
| 자동 적용의 위험 | 자동 적용 금지. JSON proposal + diff MD + 사람 승인 단계 필수. |
| 시장 regime 한 방향 편향 | 학습창 최소 길이와 bear/bull 양쪽 포함 여부 검증 룰. |

## 6. 성공 기준

- v1 런칭 후 60일 내 1회 이상 proposal 채택 & 반영.
- 반영 전후 buy-review tier의 out-of-sample T+10 초과수익률이 **유의하게 감소하지 않음** (baseline 대비).
- 튜닝 runner 단일 실행이 NASDAQ-100 / 6개월 입력에서 10분 이내.

## 7. 개방 질문

- 그리드 대신 베이지안 최적화(`scikit-optimize`)를 써야 할 만큼 차원이 커지는 시점은? → v2 스코어 상수까지 포함하면 고려.
- proposal 거부 이력을 어디에 기록? → `output/tuning/<date>/decision.md` 수기 기록이 v1 안.
- Russell 2000 확장 시 유니버스별 별도 proposal vs 공통 proposal? → 일단 유니버스별 분리.

## 8. 후속

개발 계획과 일정은 [backtest-feedback-loop-plan.md](backtest-feedback-loop-plan.md) 참고.
