# ADMIN 2026 대회 웹사이트·API

충남대학교 ADMIN 단백질 구조 분류 대회의 웹 화면(Next.js), 운영 API(FastAPI), 채점 작업자(worker), 사용자·팀·제출 DB(PostgreSQL), 배포 설정을 담은 비공개 저장소입니다.

## 저장소 분리

- 이 저장소: 웹사이트, 인증, DB, 제출 접수, 채점 대기열과 격리 추론, 운영 화면, Docker 배포
- [`admin-2026-protein-data`](https://github.com/2026-admin-ai-challenge/admin-2026-protein-data): CATH 다운로드·정제·분할·검증, 31개 특징, 베이스라인, 참가자 배포용 파일 생성

이 웹 저장소에는 생성 데이터, 원본 CATH 파일, 숨긴 정답·분할표, 참가자 계정 시트를 커밋하지 않습니다. 데이터 저장소는 운영진 전용 비공개 저장소로 생성 데이터와 평가 정답·정책 파일을 관리합니다. 두 저장소를 참가자에게 공유하거나 공개 전환하지 않습니다.

## 대회 방식과 구현 상태

참가자는 운영진이 발급한 팀 계정으로 로그인해, 학습된 모델과 추론 코드를 ZIP으로 제출합니다. 서버는 숨긴 평가 입력으로 **추론만** 실행해 채점합니다.

```text
참가자 ZIP 업로드 → API가 저장·DB 기록(queued) → worker가 하나씩 꺼냄(running)
                                              → 격리 컨테이너에서 추론 → 정답과 비교 → DB·리더보드 갱신
```

| 항목 | 상태 |
| --- | --- |
| 운영진 계정 발급, 회원가입 제거 | 구현 |
| 모델 ZIP 접수, 팀당 전체 20회 제한 | 구현 |
| DB 대기열 worker, 재시작 복구 | 구현 |
| mock 평가기(가짜 점수로 전체 흐름 시연) | 구현, 기본값 |
| Docker 격리 평가기(네트워크 차단, 10분 제한) | 구현. **입출력 계약은 임시**이며 데이터팀과 확정 필요 |
| 관리자 화면(계정, 대기열, 실패, 데이터 승인, 조작 기록) | 구현 |

mock과 Docker 평가기가 모두 구현돼 있습니다. 기본 개발 스택은 mock이며, 실제 채점은 evaluator compose와 준비된 데이터·이미지를 사용합니다. 코드 병합은 운영 서버 배포나 최종 리허설 완료를 뜻하지 않습니다. 실행 중인 평가기는 API와 화면의 `evaluator` 표시로 확인합니다. 압축 해제 후 용량은 미확정 설정값으로 뒀습니다. 제출 차감은 ZIP 규격 위반·서버 오류만 제외하고 나머지 채점 실패는 1회 차감하는 것으로 확정됐습니다. 대회 운영 시 실패 제출 차감(`count_failed`)을 켜 둡니다. 최종 순위 제출물은 Public 최고 제출물로 확정됐습니다(`final_selection=best_public`, 기본값). 팀별 업무와 미결정 질문은 [팀별 남은 과제와 문의사항](ADMIN_팀별_남은_과제와_문의사항.md)을 보세요.

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

## 관리자 사용법

관리자 화면은 관리자 계정으로 로그인하면 보이는 **Admin** 탭입니다. 장애 대응과 종료 절차까지 포함한 자세한 내용은 [운영진 가이드](docs/operations.md)에 있습니다.

### 1. 관리자 계정 만들기 (서버에서 한 번)

```bash
docker compose exec api python -m app.create_admin
```

`Admin ID`에는 **새로 정할 아이디**를 입력합니다(영문 소문자·숫자 3자 이상). 비밀번호는 12자 이상이고 입력할 때 화면에 보이지 않습니다. 같은 아이디로 다시 실행하면 비밀번호를 재설정합니다.

### 2. 대회 열기

1. **Admin → 현황·설정**에서 시작 시간과 종료 시간을 넣고 **Save settings**를 누릅니다.
2. **Open competition**을 누릅니다. 화면 위쪽이 "Competition open"으로 바뀌면 제출을 받습니다.
3. 학습 데이터 다운로드까지 열려면 **데이터** 메뉴에서 **현재 버전 승인**을 누릅니다. 제출만 시험할 때는 필요 없습니다.

제출은 "대회가 열려 있고, 현재 시각이 시작~종료 사이"일 때만 받습니다.

### 3. 메뉴별로 할 수 있는 일

| 메뉴 | 할 수 있는 일 |
| --- | --- |
| 현황·설정 | 대기·채점 중·실패 건수와 채점 작업자 상태 확인, 일정·팀당 제출 횟수 설정, 대회 열기/닫기, 순위 동결, 최종 순위 공개, 대회 초기화 |
| 팀·계정 | 팀 만들기·이름 변경, 계정 발급, 비밀번호 재설정, 차단·해제, 팀별 제출 횟수와 ZIP 용량 확인 |
| 제출·대기열 | 전체 제출 조회(상태·실패 사유 필터, 검색), 실행 로그, 다시 채점, 횟수 복구, ZIP 받기, 파일 삭제, 파일 정합성 검사 |
| 데이터 | 데이터 버전과 파일 해시 확인, 공개 승인, 변경 여부 검사, 버전 잠금 |
| 조작 기록 | 누가 언제 무엇을 했는지 확인 |

### 4. 자주 하는 일

- **계정 발급**: 팀·계정에서 팀을 만들고 **랜덤 아이디로 발급**을 누릅니다. 임시 비밀번호는 **그때 한 번만** 표시되니 닫기 전에 전달합니다.
- **비밀번호를 잊은 팀**: **비밀번호 재설정**을 누르고 새 임시 비밀번호를 전달합니다. 기존 로그인은 즉시 풀립니다.
- **실패 문의**: 제출·대기열에서 접수 ID로 검색하고 **로그**를 봅니다. 로그에는 평가 입력이 섞일 수 있으니 참가자에게 그대로 주지 않습니다.
- **서버 탓으로 실패한 제출**: 원인을 고친 뒤 **다시 채점**을 누릅니다. 서버 오류(`system_error`)는 제출 횟수를 차감하지 않습니다.
- **제출 횟수 돌려주기**: 해당 제출의 **횟수 복구**를 누릅니다.
- **제출 ZIP 확인**: **ZIP 받기**로 내려받습니다(재현 심사용, 조작 기록에 남음).
- **ZIP 자동 보관**: 기본 `ZIP_RETENTION=best_public`은 팀 최고 Public 제출과 채점 중·서버 오류·리더보드 참조 ZIP 등을 보존하고 나머지 완료 ZIP을 정리합니다. 기존 완료 제출에도 적용됩니다. 삭제된 ZIP은 복구하거나 재추론할 수 없습니다. 전체 보관이 필요하면 API·worker에 `keep_all`을 동일하게 설정합니다.
- **디스크 정리**: **파일 삭제**를 누르고 사유를 적습니다. 점수와 기록은 남고 파일만 지워집니다. 순위에 반영된 제출과 채점 중인 제출은 삭제할 수 없습니다.

### 5. 대회 종료

1. **Close competition**으로 닫습니다. 종료 시각 전에 접수된 제출은 계속 채점됩니다.
2. 대기 중·채점 중이 0이 될 때까지 기다립니다.
3. **Publish final leaderboard**를 누르면 최종(Private) 순위가 공개됩니다.

### 6. 다음 대회 준비 (초기화)

닫힌 대회에서 **현황·설정 → Reset competition**을 누르고 `초기화`를 입력합니다. 제출, ZIP, Public·최종 순위, 조작 기록이 비워지고 접수 번호(1번부터)와 일정·동결·최종 공개 상태가 처음으로 돌아갑니다. **되돌릴 수 없고 따로 보관하지 않으니** 필요하면 먼저 백업하세요. 팀·계정, 제출 정책, 데이터 승인은 그대로입니다. 자세한 내용은 [운영진 가이드](docs/operations.md#다음-대회-준비-초기화)에 있습니다.

### 주의할 점

- **최종 순위 공개는 되돌릴 수 없습니다.** 이후에는 대회 재개, 계정 차단, 다시 채점이 막힙니다. 다시 열려면 대회 초기화로 제출과 순위를 모두 비워야 합니다.
- **대회 초기화도 되돌릴 수 없습니다.** 제출 ZIP과 점수·순위·조작 기록이 영구 삭제됩니다.
- **파일 삭제도 되돌릴 수 없습니다.** 삭제한 제출은 다시 채점할 수 없습니다.
- 화면에서 재설정한 비밀번호는 계정 시트(`accounts/participants.csv`)에 반영되지 않습니다. 이후 시트를 다시 불러오면 시트의 비밀번호로 돌아가므로 한 가지 방법만 쓰세요.
- 화면에 "mock 채점" 표시가 있으면 점수가 가짜입니다. 실제 대회는 아래의 Docker 격리 평가기로 실행합니다.
- `docker compose down -v`는 계정, 제출 기록, 점수, 제출 ZIP을 **전부 삭제**합니다. 서비스를 내릴 때는 `-v` 없이 `down`이나 `stop`만 씁니다.
- ngrok 등 공개 주소로 띄운 동안에는 그 주소에서만 로그인됩니다. `localhost:3000`에서는 로그인이 거절됩니다.

### 서버에서 쓰는 명령

```bash
docker compose ps                                        # 서비스 상태
docker compose logs --tail 100 worker                    # 채점 로그
docker compose restart worker                            # 채점 작업자 재시작 (대기열은 유지됨)
docker compose exec api python -m app.check_files        # 저장된 ZIP과 DB 기록 비교
cmd /c "docker compose exec -T postgres pg_dump -U admin challenge > backup.sql"   # DB 백업 (Windows)
```

## 실제 채점 (Docker 격리 평가기)

```bash
docker build -t admin-evaluator:latest apps/evaluator
# .env: EVAL_WORK_HOST_DIR, EVAL_INPUT_HOST_DIR 설정
docker compose -f docker-compose.yml -f docker-compose.evaluator.yml up --build -d
```

제출 requirements.txt의 패키지는 추론 전에 제출 전용 환경에 설치합니다. 이미지의 wheel을 네트워크 없이 먼저 사용하고, 부족하면 별도 설치 컨테이너가 PyPI에 접속합니다. 추론 컨테이너는 계속 네트워크가 차단됩니다. 채점 이미지 변경 후에는 다시 빌드하고 실제 모델로 검증합니다.

worker만 Docker 소켓과 숨긴 정답을 읽습니다. API와 참가자 컨테이너에는 주지 않습니다. 자세한 절차는 [배포·운영 문서](docs/deployment.md)에 있습니다.

## 코드 위치

- `apps/web/app/`: 화면. `components/`(참가자 패널), `components/admin/`(관리자 섹션), `lib/api.ts`(API 호출)
- `apps/api/app/routers/`: `auth`, `public`, `submissions`, `admin`
- `apps/api/app/worker.py`, `evaluators/`: 채점 작업자와 평가기(mock, docker)
- `apps/api/prediction_validator/`, `contract/`: 데이터팀 예측 파일 검증기와 계약 사본. 검증기 구현은 원본과 동기화하고, 웹 운영 정책 문구는 `prediction_validator/README.md`의 사본 관리 기준으로 대조합니다. `app/scoring/`에서 호출
- `apps/api/app/zipcheck.py`, `storage.py`, `files.py`: ZIP 검사, 비공개 저장, 파일 기록(`submission_files`) 관리
- `apps/api/app/accounts.py`: 계정 발급과 시트 동기화
- `apps/api/migrations/`: DB 스키마
- `apps/evaluator/`: 기본 패키지·89개 목록의 wheel·제출별 패키지 설치 스크립트를 담은 채점 이미지
- `deploy/nginx.conf`: 입구 프록시 설정
- `scripts/`: PostgreSQL 통합 점검, 데모 자료 생성

## 문서

- [API·상태 계약](docs/api-contract.md): 네 사람이 같이 쓰는 응답 예시, 상태, 실패 코드, ZIP·추론 규격
- [참가자 안내](docs/competition.md) · [평가 방식](docs/evaluation.md)
- [참가자 배포 후보](docs/participant-release-candidates.md): 권장 파일 구조, 공개 금지 자료, 환경 검증 원칙과 두 ZIP 다운로드 협의안
- [배포·운영](docs/deployment.md) · [운영진 가이드](docs/operations.md) · [임시 HTTPS 공유](docs/temporary-preview.md)
- [수동 테스트 체크리스트](docs/manual-test-checklist.md) · [검증 기록](docs/validation.md)

## 테스트

```bash
pip install -r apps/api/requirements.txt   # Windows에서는 uvloop 줄을 빼고 설치
pytest -q
docker compose exec -T -w /srv/apps/api api python /srv/scripts/postgres_smoke.py
```
