# Operations Runbook

## 1. Execution Modes

### Manual local run
```bash
python -m screener.cli run --date 2026-04-21
```

### OpenClaw-triggered run
```text
OpenClaw cron -> project command -> output artifacts -> summary delivery
```

## 2. Expected Workflow
1. OpenClaw가 daily schedule에 맞춰 command 실행
2. 스크리너가 output files 생성
3. OpenClaw가 결과 파일을 읽음
4. 상위 후보 요약을 사용자에게 전달

## 3. Secrets Policy
- Oracle SQL / Mongo API credential은 OpenClaw secrets에서 관리
- repo, docs, test fixture에 credential 저장 금지
- `.env.local`은 local experimentation이 필요할 때만 쓰고 gitignore 유지

## 4. Logging
기본적으로 아래를 남깁니다.
- run date
- processed ticker count
- candidate count
- failed ticker count
- provider name
- persistence mode
- elapsed seconds

## 5. Exit Semantics
- `0`: run success
- `1`: fatal failure
- `2`: configuration or secrets problem
- `3`: provider unavailable / upstream blocked

## 6. Suggested Future Cron
예시:
- 미국장 마감 후 1회
- 필요 시 premarket preview 1회

## 7. First Build Milestones
- CLI skeleton
- provider abstraction
- indicator engine
- file reporting
- optional Oracle persistence
