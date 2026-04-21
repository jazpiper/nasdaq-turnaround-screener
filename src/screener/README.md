# src/screener

스크리너 구현 코드가 들어있는 메인 패키지입니다.

현재 주요 모듈:
- `cli/`: Typer CLI entrypoint
- `collector.py`: staged intraday collection orchestration
- `config.py`: env/OpenClaw secrets 기반 설정 로딩
- `data/`: market data fetch/normalize
- `indicators/`: technical indicator 계산
- `intraday_artifacts.py`: staged intraday artifact 탐색/병합 보조
- `intraday_ops.py`: intraday window plan, command template, output 경로 규칙
- `models/`: pydantic schema
- `pipeline.py`: daily screening pipeline
- `reporting/`: markdown/json report 생성
- `scoring/`: filter/ranking logic
- `secrets.py`: OpenClaw secrets 로딩 보조
- `storage/`: file/Oracle SQL persistence
- `universe/`: NASDAQ-100 universe 로딩
