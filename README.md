# ADMIN 2026 대회 웹사이트·API

충남대학교 ADMIN 단백질 구조 분류 대회의 웹 화면(Next.js), 운영 API(FastAPI), 채점 작업자(worker), 사용자·팀·제출 DB(PostgreSQL), 배포 설정을 담은 비공개 저장소입니다.

## 저장소 분리

- 이 저장소: 웹사이트, 인증, DB, 제출 접수, 채점 대기열과 격리 추론, 운영 화면, Docker 배포
- [`admin-2026-protein-data`](https://github.com/2026-admin-ai-challenge/admin-2026-protein-data): CATH 다운로드·정제·분할·검증, 31개 특징, 베이스라인, 참가자 배포용 파일 생성

생성된 데이터, 원본 CATH 파일, 숨긴 정답과 분할표, 참가자 계정 시트는 **어느 Git 저장소에도 올리지 않습니다.**

## 대회 방식과 구현 상태

참가자는 운영진이 발급한 팀 계정으로 로그인해, 학습된 모델과 추론 코드를 ZIP으로 제출합니다. 서버는 숨긴 평가 입력으로 **추론만** 실행해 채점합니다.

```text
참가자 ZIP 업로드 → API가 저장·DB 기록(queued) → worker가 하나씩 꺼냄(running)
                                              → 격리 컨테이너에서 추론 → 정답과 비교 → DB·리더보드 갱신
```

| 항목 | 상태 |
| --- | --- |
| 운영진 계정 발급, 회원가입 제거 | 구현 |
| 모델 ZIP 접수, 팀당 전체 10회 제한 | 구현 |
| DB 대기열 worker, 재시작 복구 | 구현 |
| mock 평가기(가짜 점수로 전체 흐름 시연) | 구현, 기본값 |
| Docker 격리 평가기(네트워크 차단, 10분 제한) | 구현. **입출력 계약은 임시**이며 데이터팀과 확정 필요 |
| 관리자 화면(계정, 대기열, 실패, 데이터 승인, 조작 기록) | 구현 |

실제 대회 데이터와 확정된 추론 계약이 들어오기 전까지 결과는 **mock 기반 개발 완료**입니다. 화면과 관리자 페이지에 mock 모드임이 표시됩니다. 미확정 운영 규칙(실패 제출 차감, 최종 순위 제출물, 해제 후 용량)은 설정값으로 뒀습니다. 팀별 업무와 미결정 질문은 [팀별 남은 과제와 문의사항](ADMIN_팀별_남은_과제와_문의사항.md)을 보세요.

## 실행 (개발: mock 채점)

```bash
cp .env.example .env
python scripts/make_demo.py --out var/demo     # 가짜 데모 데이터와 예제 ZIP (선택)
# .env의 DATA_HOST_DIR을 데이터 디렉터리로 지정. 데모라면 ./var/demo/data
docker compose up --build -d
```

웹 주소는 `http://localhost:3000`입니다. nginx `gateway`가 유일한 입구이고 API·DB·worker는 내부 네트워크에만 있습니다. 큰 ZIP 업로드는 `gateway`가 API로 직접 흘려보냅니다(Next.js 프록시는 10 MB에서 막힙니다).

```bash
docker compose exec api python -m app.create_admin                                   # 관리자 계정
docker compose exec -T api python -m app.sync_accounts < accounts/participants.csv   # 참가자 계정
# Windows PowerShell은 < 를 지원하지 않으므로 아래처럼 실행
cmd /c "docker compose exec -T api python -m app.sync_accounts < accounts\participants.csv"
```

## 참가자 계정

참가자는 **사전에 배부한 아이디로만** 로그인합니다. 계정 시트 `accounts/participants.csv`(Git 제외)가 수정 가능한 원본입니다.

```csv
team_name,username,password,display_name
Team 01,k7m2xq9rtd,임시비밀번호,Team 01
```

- 새로 만들기: `python -m app.generate_accounts --count 10 --out accounts/participants.csv` (랜덤 10자리 아이디, 12자리 임시 비밀번호)
- 수정 반영: 시트를 고친 뒤 `sync_accounts`를 다시 실행합니다. 팀 이름·비밀번호 변경, 계정 추가가 반영됩니다.
- 시트에 없는 참가자 계정까지 막으려면 `--exclusive`를 붙입니다.
- DB에는 비밀번호 해시만 저장됩니다. 관리자 화면에서도 팀·계정 발급, 비밀번호 재설정, 차단을 할 수 있습니다.

## 실제 채점 (Docker 격리 평가기)

```bash
docker build -t admin-evaluator:latest apps/evaluator
# .env: EVAL_WORK_HOST_DIR, EVAL_INPUT_HOST_DIR 설정
docker compose -f docker-compose.yml -f docker-compose.evaluator.yml up --build -d
```

worker만 Docker 소켓과 숨긴 정답을 읽습니다. API와 참가자 컨테이너에는 주지 않습니다. 자세한 절차는 [배포·운영 문서](docs/deployment.md)에 있습니다.

## 코드 위치

- `apps/web/app/`: 화면. `components/`(참가자 패널), `components/admin/`(관리자 섹션), `lib/api.ts`(API 호출)
- `apps/api/app/routers/`: `auth`, `public`, `submissions`, `admin`
- `apps/api/app/worker.py`, `evaluators/`: 채점 작업자와 평가기(mock, docker)
- `apps/api/app/zipcheck.py`, `storage.py`: ZIP 검사와 비공개 저장
- `apps/api/app/accounts.py`: 계정 발급과 시트 동기화
- `apps/api/migrations/`: DB 스키마
- `apps/evaluator/`: 고정 채점 이미지 초안
- `deploy/nginx.conf`: 입구 프록시 설정
- `scripts/`: PostgreSQL 통합 점검, 데모 자료 생성

## 문서

- [API·상태 계약](docs/api-contract.md): 네 사람이 같이 쓰는 응답 예시, 상태, 실패 코드, ZIP·추론 규격
- [참가자 안내](docs/competition.md) · [평가 방식](docs/evaluation.md)
- [배포·운영](docs/deployment.md) · [운영진 가이드](docs/operations.md) · [임시 HTTPS 공유](docs/temporary-preview.md)
- [검증 기록](docs/validation.md)

## 테스트

```bash
pip install -r apps/api/requirements.txt   # Windows에서는 uvloop 줄을 빼고 설치
pytest -q
docker compose exec -T -w /srv/apps/api api python /srv/scripts/postgres_smoke.py
```
