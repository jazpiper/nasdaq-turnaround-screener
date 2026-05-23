---
project: Nasdaq Turnaround Screener
type: Dashboard
related: [Log.md, Handoff.md, architecture.md, operations.md, signals.md, openclaw-cron-runbook.md]
updated: 2026-05-23
---

# 📊 Nasdaq Turnaround Screener Dashboard

Welcome to the **Nasdaq Turnaround Screener** documentation hub. This screener evaluates turnaround candidates (mostly NASDAQ-100 by default or custom universes) based on technical, volume, and weekly indicators.

---

## 🎯 Project Overview & Status

This project operates as a signal generator. It fetches daily and intraday OHLCV bars, scores potential turnaround candidate tickers, applies risk-adjusted and technical overrides, and builds alert-ready sidecars (`alert-events.json`) for downstream consumers (like OpenClaw for Telegram notifications).

- **Current Version:** v1.1 (OpenClaw Alert Event Sidecar integrated)
- **Primary Tech Stack:** Python 3.11/3.12, Pydantic, pandas, Twelve Data & yfinance APIs, SQLite/Oracle SQL, pytest

---

## 🗺️ Documentation Directory

| 문서 (Link) | 유형 (Type) | 상태 (Status) | 설명 (Summary) |
| :--- | :--- | :--- | :--- |
| [Handoff.md](./Handoff.md) | Handoff | Active | 활성 스프린트 백로그, 태스크 보드 및 현재 상태 |
| [Log.md](./Log.md) | Log | Active | 프로젝트 개발의 연대기적 변경 로그 |
| [architecture.md](./architecture.md) | Architecture | Active | 시스템 아키텍처, 런타임 플로우, 모듈 설명 및 바운더리 |
| [operations.md](./operations.md) | Operations | Active | 운영 매뉴얼, CLI 실행 명령어, 장애 처리 가이드 |
| [signals.md](./signals.md) | Signals | Active | 스크리닝 필터, 서브스코어링 가중치, 페널티 규칙 |
| [openclaw-cron-runbook.md](./openclaw-cron-runbook.md) | Runbook | Active | OpenClaw 연동 크론 레이아웃 및 알림 정책 |
| [Archive/doc-review-2026-04-22.md](./Archive/doc-review-2026-04-22.md) | Review | Archived | 2026-04-22 문서 리뷰 및 후속 조치 반영 현황 |
| [Archive/improvements-2026-04-24.md](./Archive/improvements-2026-04-24.md) | Review | Archived | 개선 아이디어 서베이 및 우선순위 선정 |
| [Archive/backtest-feedback-loop.md](./Archive/backtest-feedback-loop.md) | Proposal | Archived | 백테스트 파라미터 자동 피드백 루프 개선 제안서 |
| [Archive/backtest-feedback-loop-plan.md](./Archive/backtest-feedback-loop-plan.md) | Plan | Archived | 백테스트 피드백 루프 개발 구현 계획서 |
| [Archive/2026-04-24-alert-regime-gate.md](./Archive/2026-04-24-alert-regime-gate.md) | Plan | Archived | 시장 Regime을 고려한 Alert Gate 구축 계획서 |
| [Archive/2026-04-24-alert-regime-gate-design.md](./Archive/2026-04-24-alert-regime-gate-design.md) | Spec | Archived | Regime Gate 상세 스펙 설계서 |
| [Archive/v1.1-update-plan.md](./Archive/v1.1-update-plan.md) | Spec | Archived | v1.1 OpenClaw Alert Sidecar 기획 및 요구 사양서 |
| [Archive/v1.1-update-implementation-plan.md](./Archive/v1.1-update-implementation-plan.md) | Plan | Archived | v1.1 Alert Sidecar 구현 및 단계별 테스트 계획서 |

---

## 🚀 TODO Overview & Milestone Status

- [x] **v1.0 Core Pipeline**: Daily screening, staged intraday collection, file output, Oracle SQL persistence, and historical backtesting skeletal setup.
- [x] **v1.1 OpenClaw Integration**: Signal producer sidecars (`alert-events.json` daily and intraday), Telegram notification readiness, local state deduplication.
- [ ] **v1.2 Parameter Auto-Tuning**: Walk-forward parameter grid search feedback loops (Scheduled).

---

## 🔗 Related Documents
| 문서 | 관계 |
| :--- | :--- |
| [Log.md](./Log.md) | 작업 로그 |
| [Handoff.md](./Handoff.md) | 핸드오프 및 태스크 보드 |
| [architecture.md](./architecture.md) | 시스템 아키텍처 |
| [operations.md](./operations.md) | 운영 매뉴얼 및 명령어 |
| [signals.md](./signals.md) | 스크리닝 시그널 규칙 |
| [openclaw-cron-runbook.md](./openclaw-cron-runbook.md) | OpenClaw 크론 탭 가이드 |
