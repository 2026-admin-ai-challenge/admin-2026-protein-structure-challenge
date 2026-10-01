# ADMIN 2026 대회 웹사이트·API

충남대학교 ADMIN 단백질 구조 분류 대회의 웹 화면(Next.js), 운영 API(FastAPI), 사용자·팀·제출 DB(PostgreSQL), 배포 설정을 담은 비공개 저장소입니다.

## 저장소 분리

- 이 저장소: 웹사이트, 인증, DB, 제출 접수와 점수 계산, 운영 화면, Docker 배포
- [`admin-2026-protein-data`](https://github.com/2026-admin-ai-challenge/admin-2026-protein-data): CATH 다운로드·정제·분할·검증, 31개 특징, 베이스라인, 참가자 배포용 파일 생성

생성된 데이터, 원본 CATH 파일, 숨긴 정답과 분할표는 **어느 Git 저장소에도 올리지 않습니다.** 데이터 저장소의 `data/` 디렉터리를 서버에서 이 저장소의 API 컨테이너에 읽기 전용으로 연결합니다.

## 현재 구현 상태

이 코드는 기존 CSV 제출 방식의 프로토타입입니다. 새 대회에 필요한 **운영진 계정 발급, 모델 ZIP 제출, 격리된 추론 채점, 팀당 10회 제한, 5분 간격, 500 MiB·10분 제한**은 아직 구현되지 않았습니다. 구현 전 운영용으로 열지 마세요. 변경 범위와 검수 기준은 [개발 디렉팅 문서](ADMIN_대회_개발_디렉팅.md)에 있습니다.

기존 코드의 회원가입과 공개 test 입력, 외부 데이터 허용 문구 역시 새 운영 규칙과 맞지 않습니다. UI·API·규정 문구를 함께 수정해야 합니다.

## 실행

두 저장소를 같은 상위 디렉터리에 체크아웃하고, **대회 전에** 데이터 저장소의 안내대로 생성·검증을 마칩니다. `data/private/labels.csv`와 `data/public/metadata.json`이 있어야 대회 데이터를 사용할 수 있습니다.

```bash
cp .env.example .env
# .env의 POSTGRES_PASSWORD, SECRET_KEY, APP_ORIGIN을 운영 환경에 맞게 설정
# DATA_HOST_DIR은 생성된 데이터의 host 디렉터리. 기본값: ../admin-2026-protein-data/data
docker compose up --build -d
```

웹 주소는 `http://localhost:3000`입니다. API와 DB는 내부 네트워크에 둡니다. API 시작 과정에서 데이터셋을 다운로드하거나 재생성하지 않습니다. 데이터 마운트는 읽기 전용입니다. `GET /api/health`의 `dataset_ready`로 준비 상태를 확인하세요.

관리자 계정은 `docker compose exec api python -m app.create_admin`으로 생성합니다. 현재 사용자 계정 발급 방식은 별도 구현이 필요합니다.

## 코드 위치

- `apps/web/`: 참가자·운영자 화면
- `apps/api/app/`: 인증, API, DB, CSV 채점 프로토타입
- `apps/api/migrations/`: DB 스키마
- `apps/api/tests/`: API·채점 테스트
- `scripts/postgres_smoke.py`: PostgreSQL 연동 점검
- `docs/`: 운영·평가 문서. 새 대회 규칙으로 갱신되기 전에는 프로토타입 설명입니다.

데이터 형식과 생성 절차는 [데이터 저장소 문서](https://github.com/2026-admin-ai-challenge/admin-2026-protein-data)를 참조하세요.
