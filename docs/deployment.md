# 배포와 서버 구성

## 구성

| 서비스 | 역할 | 접근하는 것 |
| --- | --- | --- |
| `gateway` | nginx. 유일한 입구(포트 3000). 화면은 `web`으로, `/api`는 `api`로 직접 전달 | — |
| `web` | Next.js 화면 | — |
| `api` | 인증, 접수, 조회, 관리자 API | DB, 참가자 공개 데이터(읽기 전용), 제출 ZIP 저장소(쓰기) |
| `worker` | 대기열 채점 | DB, 제출 ZIP 저장소(읽기 전용). 실제 채점 시 Docker 소켓, 숨긴 정답 |
| `postgres` | 계정·팀·제출·점수·순위·조작 기록 | — |

제출 ZIP은 Docker 볼륨 `submissions`에 있고 웹으로 공개되는 경로가 아닙니다. 숨긴 정답은 `api`에 연결하지 않습니다.

`/api`를 Next.js를 거치지 않고 `api`로 직접 보내는 이유는 업로드 때문입니다. Next.js의 프록시는 요청 본문을 10 MB까지만 전달해서 그보다 큰 ZIP은 실패합니다(실측). `gateway`는 업로드를 버퍼링 없이 흘려보내고, 크기 상한은 API가 `MAX_ZIP_BYTES`로 정확히 검사합니다. 설정은 `deploy/nginx.conf`입니다. Docker 없이 `npm run dev`로만 띄우면 Next.js 프록시를 쓰게 되어 10 MB 넘는 업로드는 되지 않습니다.

## 로컬 개발 (mock 채점)

```bash
cp .env.example .env
docker compose up --build -d
docker compose exec api python -m app.create_admin
docker compose exec -T api python -m app.sync_accounts < accounts/participants.csv
# Windows PowerShell은 < 를 지원하지 않으므로 아래처럼 실행
cmd /c "docker compose exec -T api python -m app.sync_accounts < accounts\participants.csv"
```

웹: http://localhost:3000. 데이터가 없어도 관리자가 일정을 넣고 대회를 열면 제출·대기열·mock 점수·리더보드까지 흐름이 동작합니다. `python scripts/make_demo.py`로 가짜 데이터와 예제 ZIP(`var/demo/`)을 만들 수 있습니다.

`docker compose logs -f worker`로 채점 로그를, `GET /api/health`의 `evaluator`로 현재 평가기를 확인합니다.

## 실제 채점 (Docker 격리 평가기)

1. 채점 이미지를 만듭니다. 패키지 목록(`apps/evaluator/requirements.txt`)은 데이터팀과 합의한 것으로 고정합니다.
   ```bash
   docker build -t admin-evaluator:latest apps/evaluator
   ```
2. `.env`에 호스트 경로를 적습니다.
   ```bash
   DATA_HOST_DIR=/srv/admin-data            # public/, private/ 가 있는 데이터 디렉터리
   EVAL_INPUT_HOST_DIR=/srv/admin-eval-input  # 숨긴 평가 입력
   EVAL_WORK_HOST_DIR=/srv/admin-eval-work    # 제출을 풀어 놓는 빈 디렉터리
   EVAL_CPUS=4
   EVAL_MEMORY=8g
   ```
3. 평가기 설정을 얹어 실행합니다.
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.evaluator.yml up --build -d
   ```
4. 관리자 화면 "현황·설정"에서 채점 작업자가 **정상**인지 확인합니다. 이미지나 정답 파일이 없으면 "준비 안 됨"과 사유가 표시되고, 그동안 제출은 대기열에 쌓이기만 합니다.

### 격리 내용

참가자 컨테이너는 `--network none`, 읽기 전용 루트, 사용자 65534, 모든 capability 제거, `no-new-privileges`, 프로세스·CPU·메모리 제한, `/tmp`만 쓰기 가능으로 실행합니다. 마운트는 제출 내용(읽기 전용), 평가 입력(읽기 전용), 출력 디렉터리 하나뿐입니다. 10분을 넘으면 worker가 강제 종료하고, worker가 죽어도 컨테이너 안의 타이머가 종료시킵니다. 출력 디렉터리가 5 MB를 넘어도 종료합니다.

**주의:** worker는 Docker 소켓을 쓰므로 호스트의 root와 같은 권한을 가집니다. worker 컨테이너에는 운영진 코드만 들어가며, 참가자 코드는 worker가 띄우는 별도 컨테이너에서만 실행됩니다. 채점 컴퓨터는 Linux를 권장합니다.

### 자원 정하기

동방 컴퓨터에서 베이스라인과 구조 기반 모델을 각각 같은 방식으로 실행해 시간과 메모리를 재고 `EVAL_CPUS`, `EVAL_MEMORY`를 정합니다. worker 하나는 한 번에 한 건만 채점합니다. 동시에 여러 건을 돌리려면 `docker compose ... up -d --scale worker=2`처럼 worker 수를 늘리되, `worker 수 × EVAL_MEMORY`와 웹·API·DB가 쓸 몫을 합쳐 실제 메모리 안에 들어와야 합니다. 대회 중에는 이 컴퓨터에서 다른 학습을 돌리지 않습니다.

## HTTPS 운영

- `.env`의 `SECRET_KEY`와 `POSTGRES_PASSWORD`를 새 난수로 바꿉니다. URL에 들어가는 비밀번호는 영숫자를 쓰거나 URL 인코딩합니다.
- TLS 리버스 프록시를 `gateway`의 3000 포트 앞에 두고 정확한 `APP_ORIGIN`, `COOKIE_SECURE=true`를 설정합니다. `gateway`는 기본으로 loopback에만 열려 있습니다.
- **앞단 프록시의 요청 본문 한도를 ZIP 상한(500 MB)보다 크게** 잡고, 업로드가 끝날 때까지 끊기지 않게 요청 시간 제한을 늘립니다. 한도가 작으면 큰 ZIP이 접수되지 않습니다. 대회 전에 실제 크기의 파일로 올려 봅니다.
- 앱은 전달된 `X-Forwarded-For`를 신뢰하지 않습니다. 로그인 시도 제한은 아이디별로 분당 10회입니다.
- Linux에서 데이터 디렉터리는 컨테이너 UID 10001이 읽을 수 있어야 합니다(실제 채점 모드의 worker는 root로 실행).

## 용량·환경변수

| 변수 | 기본값 | 비고 |
| --- | --- | --- |
| `MAX_ZIP_BYTES` | 524288000 (500 MB) | 확정 |
| `INFERENCE_TIMEOUT_SECONDS` | 600 | 확정 |
| `TEAM_SUBMISSION_LIMIT` | 10 | 새 DB의 초기값. 이후 관리자 화면에서 변경 |
| `MAX_UNZIPPED_BYTES` | 2147483648 | **임시**. 운영진 결정 후 변경 |
| `MAX_ZIP_ENTRIES` | 2000 | **임시** |
| `ZIP_REQUIRED` | `inference.py,train.py,requirements.txt,model/` | **임시**. 데이터팀과 확정 |
| `EVALUATOR` | `mock` | compose 파일이 정함. `.env`로 바꾸지 않음 |

제출 ZIP 저장 공간은 최악의 경우 `팀 수 × 10 × 500 MB`입니다. 30팀이면 150 GB입니다.

## DB 마이그레이션

`alembic upgrade head`는 API가 시작할 때 자동 실행됩니다. `0003`은 제출 파일 정보를 `submission_files` 테이블로 옮깁니다(`team_id`, `submission_id`로 연결, 삭제 기록 포함). `0002`는 CSV 프로토타입 스키마를 모델 제출 방식으로 바꿉니다(아이디 로그인, 팀당 여러 계정, 제출 상태·저장 정보, 조작 기록, worker 상태). 프로토타입 시절의 제출은 `evaluator='csv'`로 남고 순위에 들어가지 않습니다. **실제 대회는 새 DB로 시작하는 것을 권장합니다.**

되돌리기는 `docker compose exec api alembic downgrade 0001`입니다. 팀당 계정이 둘 이상이면 옛 스키마의 제약 때문에 실패하므로, 되돌리기 전에 백업을 받아 두세요.

## 백업과 복구

```bash
# DB
docker compose exec -T postgres pg_dump -U admin challenge > backup-$(date +%Y%m%d-%H%M).sql
# 제출 ZIP
docker run --rm -v admin-2026-protein-structure-challenge_submissions:/data:ro -v "$PWD":/backup alpine \
  tar czf /backup/submissions-$(date +%Y%m%d-%H%M).tar.gz -C /data .
```

DB 백업에는 Private 점수와 저장된 예측이 들어 있으므로 운영진만 접근하는 곳에 둡니다. `docker compose down`은 데이터를 지우지 않습니다. `down -v`는 DB와 제출 ZIP을 **모두 삭제**합니다.

복구는 빈 DB에 `psql`로 백업을 넣고 제출 볼륨에 tar를 풉니다. 수상 후보의 최종 제출물과 검증 기록은 재현 심사가 끝날 때까지 보관합니다.

## 재시작

모든 서비스에 `restart: unless-stopped`가 걸려 있습니다. 서버나 worker가 채점 중에 꺼지면 그 제출은 `running`으로 남고, worker가 다시 떠서 120초 동안 신호가 없는 것을 확인하면 `queued`로 되돌려 다시 채점합니다. 같은 제출이 세 번 중단되면 `system_error`로 실패 처리하며 횟수는 차감하지 않습니다. `queued` 제출은 DB에 있으므로 재시작으로 사라지지 않습니다.

## 점검 명령

```bash
docker compose ps
docker compose logs --tail 100 worker
docker compose exec -T -w /srv/apps/api api python /srv/scripts/postgres_smoke.py   # 임시 DB로 전체 흐름 점검
docker compose exec -w /srv api pytest -q -c /srv/apps/api/pytest.docker.ini
docker compose exec api python -m app.check_files          # 저장된 ZIP과 DB 기록 비교
```

`postgres_smoke.py`는 무작위 이름의 시험용 DB만 만들고 지웁니다. 대회 데이터는 건드리지 않습니다.
