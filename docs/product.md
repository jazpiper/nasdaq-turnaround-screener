# Product Overview

## 한 줄 정의
NASDAQ-100 안에서 과매도 구간에 진입했지만 무작정 약한 종목이 아니라, 최근 저점을 만들고 반등 전환 가능성이 보이는 종목만 매일 좁혀주는 screener.

## 왜 필요한가
주요 지수 대형주 안에서도 단순 하락 종목과 바닥권 반등 후보는 다릅니다. 매일 전 종목을 수동으로 확인하기 어렵기 때문에, 기계적으로 1차 후보를 좁히고 사람이 최종 판단할 수 있게 해야 합니다.

## 핵심 가치
- 매일 같은 기준으로 반복 가능
- 후보 선정 이유가 명확함
- 과도한 종목 수를 상위 몇 개로 축소
- 장중 staged intraday snapshot으로 EOD 판단 입력을 보강 가능
- OpenClaw가 자동 실행/요약을 담당 가능

## 대상 사용자
- 개인 투자자
- 단기 swing / 중기 rebound 후보를 찾는 사용자
- 완전 자동 매매보다 research workflow를 선호하는 사용자

## Non-goals
- 자동 주문 실행
- 투자 자문 대체
- 초단타/분봉 전략
- 모든 미국 주식 전체를 처음부터 커버

## 성공 기준
- 매일 장 종료 후 안정적으로 후보 리포트 생성
- 필요 시 staged intraday snapshot을 반영한 daily run 수행 가능
- 후보당 2~5개의 핵심 근거 제시
- candidate별 indicator snapshot을 통해 왜 선택됐는지 추적 가능
- 장기적으로 false positive를 줄이도록 rules를 개선 가능
