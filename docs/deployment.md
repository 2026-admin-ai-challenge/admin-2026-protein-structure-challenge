# 배포와 서버 구성

## 구성

| 서비스 | 역할 | 접근하는 것 |
| --- | --- | --- |
| `gateway` | nginx. 유일한 입구(포트 3000). 화면은 `web`으로, `/api`는 `api`로 직접 전달 | — |
| `web` | Next.js 화면 | — |
| `api` | 인증, 접수, 조회, 관리자 API | DB, 참가자 공개 데이터(읽기 전용), 제출 ZIP 저장소(쓰기) |
| `worker` | 대기열 채점 | DB, 제출 ZIP 저장소(읽기·삭제: 보관 정책에 따른 정리). 실제 채점 시 Docker 소켓, 숨긴 정답 |
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

1. 채점 이미지를 만듭니다. 기본 패키지(`apps/evaluator/requirements.txt`)는 설치하고, 데이터팀의 89개 고정 목록(`apps/evaluator/requirements-competition.lock.txt`)은 Linux용 wheel만 `/opt/wheels`에 받아 둡니다. 빌드할 때 수 GB를 받습니다.
   ```bash
   docker build -t admin-evaluator:latest apps/evaluator
   ```
   89개 목록은 데이터 저장소 `runtime/requirements-competition.lock.txt`의 사본입니다. 그쪽이 바뀌면 파일을 다시 복사하고 이미지를 새로 빌드합니다. 사본이 낡아도 채점은 되지만, 빠진 패키지는 매번 PyPI에서 받습니다.
   채점 컴퓨터는 **PyPI(`pypi.org`, `files.pythonhosted.org`)와 `download.pytorch.org`에 접속할 수 있어야** 합니다. 목록 밖 패키지를 요구하는 제출만 이 접속을 씁니다.
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

참가자 컨테이너는 `--network none`, 읽기 전용 루트, 사용자 65534, 모든 capability 제거, `no-new-privileges`, 프로세스·CPU·메모리 제한, `/tmp`만 쓰기 가능으로 실행합니다. 마운트는 제출 내용(읽기 전용), 평가 입력(읽기 전용), 출력 디렉터리 하나, 그리고 `requirements.txt`가 패키지를 요구한 경우 패키지 볼륨(읽기 전용)뿐입니다. 10분을 넘으면 worker가 강제 종료하고, worker가 죽어도 컨테이너 안의 타이머가 종료시킵니다. 출력 디렉터리가 예측 계약의 파일 크기 상한(`output.max_file_bytes`, 현재 10 MB)을 넘어도 종료합니다.

패키지 설치 컨테이너도 같은 제한으로 실행하며, 마운트는 그 제출의 패키지 볼륨(`admin-eval-env-<시각>-<제출>-<난수>`)뿐입니다. 제출 내용과 평가 입력은 보지 않고, worker가 `requirements.txt`를 해석해 다시 쓴 요구사항만 인자로 받습니다. 먼저 `--network none`으로 이미지 안의 wheel만 써서 설치하고, 실패할 때만 기본 bridge 네트워크로 다시 실행해 PyPI에서 받습니다(이때만 공유 캐시 볼륨 `admin-eval-pip-cache`도 붙음). wheel만 받으므로 네트워크가 열린 동안 실행되는 것은 pip뿐입니다. 받은 패키지의 코드는 네트워크 없는 추론 컨테이너에서만 실행됩니다. 패키지 볼륨은 채점이 끝나면 지우고, worker가 죽어 남은 볼륨은 다음 채점 때 정리합니다(`docker volume ls --filter name=admin-eval-env-`로 확인). 캐시가 커지면 대회 중이 아닐 때 `docker volume rm admin-eval-pip-cache`로 지웁니다.

**주의:** worker는 Docker 소켓을 쓰므로 호스트의 root와 같은 권한을 가집니다. worker 컨테이너에는 운영진 코드만 들어가며, 참가자 코드는 worker가 띄우는 별도 컨테이너에서만 실행됩니다. 채점 컴퓨터는 Linux를 권장합니다.

### 자원 정하기

동방 컴퓨터에서 베이스라인과 구조 기반 모델을 각각 같은 방식으로 실행해 시간과 메모리를 재고 `EVAL_CPUS`, `EVAL_MEMORY`를 정합니다. worker 하나는 한 번에 한 건만 채점합니다. 동시에 여러 건을 돌리려면 `docker compose ... up -d --scale worker=2`처럼 worker 수를 늘리되, `worker 수 × EVAL_MEMORY`와 웹·API·DB가 쓸 몫을 합쳐 실제 메모리 안에 들어와야 합니다. 대회 중에는 이 컴퓨터에서 다른 학습을 돌리지 않습니다.

## CI 자동 배포

`main`에 push(머지)되면 GitHub Actions [`deploy.yml`](../.github/workflows/deploy.yml)이 웹 서버에 배포합니다. Actions 화면에서 수동으로 실행할 수도 있습니다.

1. `api`, `worker`, `web` 이미지를 빌드해 `ghcr.io/2026-admin-ai-challenge/admin-2026-protein-structure-challenge/<이름>`에 `latest`와 커밋 SHA 태그로 올립니다. 서버(1 OCPU)에서는 빌드하지 않습니다.
2. 서버에 SSH로 접속해 `docker-compose.yml`, `docker-compose.ghcr.yml`, `deploy/nginx.conf`를 `~/admin-2026-protein-structure-challenge/`에 복사하고, 두 compose 파일로 `pull`과 `up -d`를 실행한 뒤 오래된 이미지를 지웁니다. 서버의 `.env`는 바꾸지 않습니다.
3. 저장소 secrets `DEPLOY_KEY`(SSH 개인 키)와 `DEPLOY_HOST`가 필요합니다. 레지스트리 로그인은 작업마다 발급되는 토큰으로 하고 끝나면 로그아웃합니다.

이 배포에는 `docker-compose.evaluator.yml`이 들어가지 않으므로 `EVALUATOR=mock`으로 실행됩니다. 실채점 장비는 이 경로로 배포하지 않습니다. 같은 서버에서 Docker 평가기를 켜 두면 다음 머지 때 api·worker가 mock 설정으로 다시 만들어집니다.

같은 이미지를 손으로 받으려면 처음 한 번 `docker login ghcr.io`(read:packages 토큰)를 한 뒤 다음을 실행합니다.

```bash
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml up -d
```

## 서버 `.env` 수정

운영 서버가 실제로 쓰는 `.env`는 서버 디스크의 `~/admin-2026-protein-structure-challenge/.env` 하나뿐입니다. 저장소의 `.env.example`은 템플릿이라 고쳐도 운영에 영향이 없고, 서버의 `.env`는 저장소에 올라가지 않습니다. CI 자동 배포는 compose 파일과 `deploy/nginx.conf`만 덮어쓰고 `.env`는 건드리지 않으므로, 한 번 고치면 다음 배포에도 유지됩니다. Compose는 compose 파일과 같은 디렉터리의 `.env`만 자동으로 읽습니다. 다른 이름으로 두면 읽지 않습니다.

아래에서 `$dc`는 이 명령입니다. **compose 파일 두 개를 항상 같이 지정합니다.** 하나만 쓰면 GHCR 이미지 대신 서버에서 빌드를 시작해 웹 이미지에 30분이 걸립니다.

```bash
cd ~/admin-2026-protein-structure-challenge
dc="docker compose -f docker-compose.yml -f docker-compose.ghcr.yml"
```

1. **현재 값 확인**. 비밀값을 화면에 남기지 않으려면 키 이름만 봅니다.
   ```bash
   cut -d= -f1 .env | grep -v '^#' | grep .
   ```
2. **백업**. `.env`가 깨지면 `api`와 `worker`가 뜨지 않습니다.
   ```bash
   cp .env .env.bak-$(date +%Y%m%d-%H%M)
   ```
3. **편집**(`nano .env`). `KEY=value` 형식이고 `=` 좌우에 공백을 넣지 않습니다. 따옴표는 붙이지 않고, 값 끝의 공백도 값에 포함됩니다. 줄 맨 앞 `#`은 주석이라 변수를 잠시 끌 때 씁니다. 값의 `$`는 변수로 해석되므로 비밀번호는 영숫자만 씁니다. 여러 줄 값은 지원하지 않습니다.
4. **적용 전 검증**. `config`는 아무것도 바꾸지 않고 해석된 최종 값을 보여줍니다. 오타로 변수가 읽히지 않았다면 compose의 기본값이 보입니다. 전체를 출력하면 `SECRET_KEY`와 DB 비밀번호까지 찍히므로 필요한 줄만 봅니다.
   ```bash
   $dc config | grep -i launch_at
   ```
5. **적용**. `up -d`는 설정이 바뀐 서비스만 다시 만듭니다. **`restart`로는 반영되지 않습니다**(환경변수는 컨테이너를 만들 때 주입됩니다).
   ```bash
   $dc up -d          # 또는 범위를 좁혀 $dc up -d web api
   ```
6. **확인**.
   ```bash
   $dc ps
   curl -s localhost:3000/api/health
   $dc logs --tail 50 api
   ```
7. **되돌리기**. 원인 파악보다 복구가 우선입니다.
   ```bash
   cp .env.bak-<시각> .env && $dc up -d
   ```

### 변수별 적용 범위

| 변수 | 읽는 서비스 | 적용 |
| --- | --- | --- |
| `LAUNCH_AT` | web, api | `up -d web api`. 둘의 판단이 어긋나지 않게 같이 올립니다 |
| `APPLY_URL` | web | `up -d web` |
| `APP_ORIGIN`, `COOKIE_SECURE` | api | `up -d api` |
| `MAX_ZIP_BYTES`, `MAX_UNZIPPED_BYTES`, `MAX_ZIP_ENTRIES`, `ZIP_REQUIRED`, `ZIP_RETENTION`, `INFERENCE_TIMEOUT_SECONDS`, `WORKER_STALE_SECONDS` | api, worker | `up -d api worker` |
| `MOCK_DELAY_SECONDS` | worker | `up -d worker` |
| `DATA_HOST_DIR` | api(마운트 경로) | `up -d api` |
| `SECRET_KEY` | api, worker | **대회 중 바꾸지 않습니다.** 세션 쿠키(JWT) 서명 키라서 전원이 로그아웃됩니다 |
| `POSTGRES_PASSWORD` | postgres, api, worker | **단독으로 바꾸지 않습니다.** Postgres는 DB를 처음 만들 때만 이 값을 쓰므로, `.env`만 고치면 접속 문자열만 바뀌어 인증에 실패합니다 |
| `TEAM_SUBMISSION_LIMIT` | api | 새 DB의 초기값입니다. 운영 중에는 효과가 없고 관리자 화면에서 바꿉니다 |
| `EVALUATOR` | — | compose가 정합니다. `.env`로 바꾸지 않습니다 |

각 변수의 기본값과 의미는 [용량·환경변수](#용량환경변수)에 있습니다. 일정, 팀당 제출 횟수, 실패 차감, 최종 순위 기준, 동결은 `.env`가 아니라 관리자 화면 "현황·설정"에서 바꿉니다.

### 잘못 적은 값

- **바로 멈추는 값**: `SECRET_KEY`가 32자 미만, 숫자 변수에 숫자가 아닌 값, `ZIP_RETENTION`이 `best_public`·`keep_all` 외의 값이면 `api`와 `worker`가 시작하면서 사유를 로그에 적고 죽습니다(`app/config.py`). `$dc ps`에서 재시작을 반복하고 `/api/health`가 응답하지 않습니다.
- **조용히 무시되는 값**: `LAUNCH_AT`의 형식이 틀리면 오류 없이 기본값(`2026-11-01T13:00:00+09:00`)으로 돌아갑니다. 오타로 주제가 미리 공개되지 않게 한 동작이라, "고쳤는데 그대로"일 때는 ISO 8601 형식을 확인합니다. `APPLY_URL`도 `https://`로 시작하지 않으면 버튼이 사라집니다.
- 설정되지 않은 변수 이름은 오류 없이 무시됩니다. 쓰이는 변수만 효과가 있습니다.

### 작업 시점

`api`를 다시 만드는 동안 몇 초간 API 요청이 끊기고, 업로드 중인 ZIP은 실패합니다. 채점 중에 `worker`를 다시 만들면 그 제출은 `running`으로 남고 `WORKER_STALE_SECONDS`(120초) 뒤에 `queued`로 돌아가 다시 채점됩니다. 같은 제출이 세 번 중단되면 `system_error`가 되므로, 제출이 몰리는 시간과 채점 진행 중은 피합니다. `.env`에는 비밀값이 있으니 권한은 `chmod 600`으로 둡니다.

## HTTPS 운영

- `.env`의 `SECRET_KEY`와 `POSTGRES_PASSWORD`를 새 난수로 바꿉니다. URL에 들어가는 비밀번호는 영숫자를 쓰거나 URL 인코딩합니다.
- TLS 리버스 프록시를 `gateway`의 3000 포트 앞에 두고 정확한 `APP_ORIGIN`, `COOKIE_SECURE=true`를 설정합니다. `gateway`는 기본으로 loopback에만 열려 있습니다.
- **앞단 프록시의 요청 본문 한도를 ZIP 상한(500 MB)보다 크게** 잡고, 업로드가 끝날 때까지 끊기지 않게 요청 시간 제한을 늘립니다. 한도가 작으면 큰 ZIP이 접수되지 않습니다. 대회 전에 실제 크기의 파일로 올려 봅니다.
- 앱은 전달된 `X-Forwarded-For`를 신뢰하지 않습니다. 로그인 시도 제한은 아이디별로 분당 10회입니다(관리자 계정은 제한 없음).
- Linux에서 데이터 디렉터리는 컨테이너 UID 10001이 읽을 수 있어야 합니다(실제 채점 모드의 worker는 root로 실행).

## 데이터 공개 정책

학습 데이터는 운영자가 데이터 버전을 승인하고, 시작·종료 시각을 설정해 대회를 연 뒤 `[start_time, end_time)` 동안만 내려받을 수 있습니다. 수동으로 닫거나 최종 순위를 공개하면 즉시 차단합니다. 평가 입력과 정답은 어떤 경로로도 내려받을 수 없습니다.

현재 두 GitHub 저장소는 운영진용 비공개입니다. 웹 저장소는 생성 데이터·제출 ZIP·계정 시트를 추적하지 않습니다. 데이터 저장소에는 생성 데이터와 운영진 전용 평가 정답·정책 파일이 있으므로 참가자에게 공유하거나 공개 전환하지 않습니다. 이미 내려받은 파일을 회수하는 기능은 없습니다.

## 용량·환경변수

| 변수 | 기본값 | 비고 |
| --- | --- | --- |
| `MAX_ZIP_BYTES` | 524288000 (500 MB) | 확정 |
| `INFERENCE_TIMEOUT_SECONDS` | 600 | 확정 |
| `TEAM_SUBMISSION_LIMIT` | 20 | 새 DB의 초기값. 이후 관리자 화면에서 변경 |
| `MAX_UNZIPPED_BYTES` | 2147483648 | **임시**. 운영진 결정 후 변경 |
| `MAX_ZIP_ENTRIES` | 2000 | **임시** |
| `ZIP_REQUIRED` | `inference.py,train.py,requirements.txt,model/` | **임시**. 데이터팀과 확정 |
| `EVAL_INSTALL_TIMEOUT_SECONDS` | 600 | 제출 패키지 설치 제한(오프라인·온라인 합계). 추론 시간과 따로 셈 |
| `EVAL_PIP_CACHE_VOLUME` | `admin-eval-pip-cache` | PyPI에서 받은 파일의 공유 캐시 볼륨. 빈 값이면 캐시 안 함 |
| `EVAL_MAX_OUTPUT_BYTES` | 예측 계약의 `output.max_file_bytes`(10 MB) | 추론 출력 디렉터리 상한. 비우면 계약 값을 따름 |
| `EVALUATOR` | `mock` | compose 파일이 정함. `.env`로 바꾸지 않음 |

`ZIP_RETENTION=keep_all`로 전부 보관할 때 ZIP 저장 공간 상한의 단순 추정은 `팀 수 × 20 × 압축 ZIP 한도`입니다. 현재 코드 한도 524,288,000 bytes와 30팀이면 약 314.6 GB(292.97 GiB)이며 DB·출력·패키지 볼륨·공유 pip 캐시·백업 공간은 별도입니다. 기본 `best_public`은 보존 대상 외 완료 ZIP을 정리하지만, 대기·실행·서버 오류·동결 리더보드 참조 ZIP이 추가로 남으므로 팀당 1개만 남는다고 용량을 잡지 않습니다.

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

대회 초기화는 제출 ZIP, 점수, 조작 기록을 따로 보관하지 않고 영구 삭제합니다. 남겨야 하면 초기화 전에 위 백업을 받습니다.

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
