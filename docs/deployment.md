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

참가자 컨테이너는 `--network none`, 읽기 전용 루트, 사용자 65534, 모든 capability 제거, `no-new-privileges`, 프로세스·CPU·메모리 제한, `/tmp`만 쓰기 가능으로 실행합니다. 마운트는 제출 내용(읽기 전용), 평가 입력(읽기 전용), 출력 디렉터리 하나, 그리고 `requirements.txt`가 패키지를 요구한 경우 패키지 볼륨(읽기 전용)뿐입니다. 10분을 넘으면 worker가 강제 종료하고, worker가 죽어도 컨테이너 안의 타이머가 종료시킵니다. 출력 디렉터리가 5 MB를 넘어도 종료합니다.

패키지 설치 컨테이너도 같은 제한으로 실행하며, 마운트는 그 제출의 패키지 볼륨(`admin-eval-env-<시각>-<제출>-<난수>`)뿐입니다. 제출 내용과 평가 입력은 보지 않고, worker가 `requirements.txt`를 해석해 다시 쓴 요구사항만 인자로 받습니다. 먼저 `--network none`으로 이미지 안의 wheel만 써서 설치하고, 실패할 때만 기본 bridge 네트워크로 다시 실행해 PyPI에서 받습니다(이때만 공유 캐시 볼륨 `admin-eval-pip-cache`도 붙음). wheel만 받으므로 네트워크가 열린 동안 실행되는 것은 pip뿐입니다. 받은 패키지의 코드는 네트워크 없는 추론 컨테이너에서만 실행됩니다. 패키지 볼륨은 채점이 끝나면 지우고, worker가 죽어 남은 볼륨은 다음 채점 때 정리합니다(`docker volume ls --filter name=admin-eval-env-`로 확인). 캐시가 커지면 대회 중이 아닐 때 `docker volume rm admin-eval-pip-cache`로 지웁니다.

**주의:** worker는 Docker 소켓을 쓰므로 호스트의 root와 같은 권한을 가집니다. worker 컨테이너에는 운영진 코드만 들어가며, 참가자 코드는 worker가 띄우는 별도 컨테이너에서만 실행됩니다. 채점 컴퓨터는 Linux를 권장합니다.

### 자원 정하기

동방 컴퓨터에서 베이스라인과 구조 기반 모델을 각각 같은 방식으로 실행해 시간과 메모리를 재고 `EVAL_CPUS`, `EVAL_MEMORY`를 정합니다. worker 하나는 한 번에 한 건만 채점합니다. 동시에 여러 건을 돌리려면 `docker compose ... up -d --scale worker=2`처럼 worker 수를 늘리되, `worker 수 × EVAL_MEMORY`와 웹·API·DB가 쓸 몫을 합쳐 실제 메모리 안에 들어와야 합니다. 대회 중에는 이 컴퓨터에서 다른 학습을 돌리지 않습니다.

## 원격 GPU 채점 (SSH)

평가기는 네 가지입니다. `docker compose up`만 하면 `mock`, `docker-compose.evaluator.yml`을 얹으면 이 컴퓨터의 Docker로 채점하는 `docker`, `docker-compose.remote.yml`을 얹으면 SSH로 연결한 GPU 서버에서 추론하는 `sandbox`(기본, GPU 서버에 Docker 없음) 또는 `remote`(GPU 서버에 Docker 있음)입니다. 원격 둘 중 무엇을 쓸지는 `.env`의 `EVAL_REMOTE_EVALUATOR`로 고릅니다. 두 compose 파일을 함께 얹지 않습니다.

SSH 키, 호스트 키, `.env`, 연결이 불안정할 때의 동작은 둘이 같습니다. GPU 서버에서 준비할 것과 점검 항목만 다릅니다. `sandbox`는 아래 "Docker 없는 GPU 서버" 절을 봅니다.

`remote`에서 worker는 ZIP을 여기서 풀어 검사한 뒤 GPU 서버의 작업 폴더로 복사하고, 그곳에서 `docker`와 같은 격리 컨테이너를 `--gpus`를 붙여 실행합니다. 예측 파일만 받아 와 여기서 숨긴 정답으로 점수를 냅니다. **정답·DB 정보는 GPU 서버로 가지 않고, 이 서버에는 Docker 소켓을 연결하지 않습니다.**

### GPU 서버에 미리 준비할 것 (서버 주인이 직접)

채점기는 아무것도 설치하지 않습니다. 대신 처음 접속할 때와 그 뒤 1분마다 아래를 확인하고, 하나라도 빠지면 **연결을 취소**합니다. 취소되면 제출을 받지 않고 대기열에 쌓아 두며, 관리자 화면 "채점 작업자" 칸에 빠진 항목과 해결 방법을 한 줄씩 보여 줍니다.

| 확인 | 빠졌을 때 |
| --- | --- |
| SSH 접속(키 인증, 호스트 키 일치) | 접속 실패 사유와 `ssh-keyscan`·`authorized_keys` 안내 |
| Linux | Windows는 WSL2 안의 Ubuntu로 접속하라는 안내 |
| NVIDIA 드라이버(`nvidia-smi`), `EVAL_GPUS`의 GPU 번호 | 드라이버 설치 안내, 서버의 실제 GPU 번호 |
| Docker Engine과 접속 계정의 사용 권한 | 미설치·권한 없음(docker 그룹)·데몬 꺼짐을 구분해 안내 |
| NVIDIA Container Toolkit | 설치와 `nvidia-ctk runtime configure` 안내 |
| 평가 이미지(설치기 라벨 포함) | `docker pull` 안내 |
| 평가 입력 3개 파일, 작업 폴더 쓰기, 디스크 여유(`EVAL_MIN_FREE_GB`, 기본 10 GB) | 빠진 파일 이름, 여유 용량 |
| 컨테이너에서 GPU가 실제로 보이는지(`docker run --gpus ... nvidia-smi -L`) | Docker 오류 첫 줄. 통과하면 10분 동안은 다시 띄우지 않음 |

손으로 확인하려면 `docker compose ... exec worker python -m app.evaluators.remote`를 실행합니다. 항목마다 `[OK]` 또는 `[취소 사유]`와 해결 방법을 출력합니다.

접속 계정은 채점 전용으로 만듭니다. docker 그룹은 그 서버의 root와 같은 권한입니다. 로그인 셸은 bash나 sh여야 합니다.

### 평가 이미지 (ghcr)

`apps/evaluator`가 main에서 바뀌면 GitHub Actions(`.github/workflows/evaluator-image.yml`)가 평가 이미지를 빌드합니다. 설치기 라벨과 기본 패키지 import를 네트워크 없이 확인한 뒤에만 `ghcr.io/2026-admin-ai-challenge/admin-2026-protein-structure-challenge/evaluator`에 `latest`와 커밋 태그로 올립니다. Actions 화면의 "Run workflow"로 직접 실행할 수도 있고, 실행 요약에 커밋 태그와 digest가 나옵니다.

GPU 서버에서는 접속 계정으로 한 번 로그인하고 이미지를 받습니다. 저장소가 비공개라 `read:packages` 권한만 있는 토큰(classic)이 필요합니다. 토큰은 그 서버에 남으므로 대회가 끝나면 폐기합니다.
```bash
docker login ghcr.io -u <GitHub 아이디>
docker pull ghcr.io/2026-admin-ai-challenge/admin-2026-protein-structure-challenge/evaluator:<커밋>
```
`docker login`은 비밀번호를 물으면 토큰을 붙여 넣습니다. 웹 서버 `.env`의 `EVAL_IMAGE`에는 `latest`가 아니라 **그 커밋 태그를 적습니다.** 대회 중 새 이미지가 올라와도 채점 환경이 바뀌지 않게 하기 위해서입니다. 채점기는 이미지를 직접 받지 않습니다. 서버에 이미지가 없으면 연결을 취소하고 `docker pull` 명령을 안내합니다.

현재 이미지는 CPU용 torch입니다. GPU 점검은 통과하지만, 참가자 코드가 GPU로 계산하려면 CUDA용 torch로 바꿔야 합니다.

### 설정

1. 채점기 전용 키를 만들고 공개키를 GPU 서버 계정의 `~/.ssh/authorized_keys`에 넣습니다. 개인키는 worker(uid 10001)만 읽을 수 있게 합니다.
   ```bash
   ssh-keygen -t ed25519 -N "" -f secrets/eval_ssh_key
   sudo chown 10001:10001 secrets/eval_ssh_key && sudo chmod 600 secrets/eval_ssh_key
   ```
2. GPU 서버의 호스트 키를 받아 두고, **서버 주인에게 지문을 확인합니다.** 이후 키가 달라지면 접속을 거부합니다.
   ```bash
   ssh-keyscan -p 22 100.64.0.10 > secrets/eval_known_hosts
   ssh-keygen -lf secrets/eval_known_hosts
   ```
3. `.env`에 적습니다(`.env.example` 참고). `EVAL_REMOTE_WORK_DIR`, `EVAL_REMOTE_INPUT_DIR`는 GPU 서버 안의 경로입니다. `EVAL_SSH_ALLOWED`에 허용 대역(예: Tailscale `100.64.0.0/10`)을 적으면 그 밖의 주소로는 연결하지 않습니다.
4. 실행합니다.
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.ghcr.yml -f docker-compose.remote.yml up -d
   ```
   main에 합쳐질 때 자동 배포(`.github/workflows/deploy.yml`)는 서버 `.env`에 `EVAL_SSH_HOST`가 있으면 이 파일을 얹고, 없으면 지금처럼 mock으로 띄웁니다. `EVAL_SSH_KEY_FILE`·`EVAL_SSH_KNOWN_HOSTS_FILE`이 가리키는 파일이 없거나 다른 원격 설정이 빠졌으면, 컨테이너를 다시 띄우기 전에 배포가 멈추고 빠진 항목을 로그에 남깁니다. 돌고 있던 서비스는 그대로입니다.

### 연결이 불안정할 때

- 한 제출은 처음부터 끝까지 **마지막으로 점검을 통과한 서버**에서만 실행합니다. 채점 중에 설정이 바뀌어도 그 제출의 종료·결과 회수·정리는 원래 서버로 갑니다.
- 채점 중 연결이 끊기거나 Docker가 실패하면 그 제출은 `system_error`(횟수 미차감)로 끝나고, worker는 다음 제출 전에 모든 항목을 다시 점검합니다. 서버가 돌아올 때까지 나머지 제출은 대기열에서 기다립니다. 실패한 제출은 원인을 확인한 뒤 "다시 채점"합니다.
- 연결이 끊겨도 GPU 서버의 컨테이너는 스스로 멈추지 않으므로, 실행 끝에 그 제출의 컨테이너를 지웁니다. 그때도 연결이 안 되면 컨테이너 안의 타이머(추론 제한 + 15초)가 멈춥니다.
- 출력 크기는 SSH로 3초마다 확인합니다(이 컴퓨터의 Docker는 1초).
- GPU를 다른 사용자와 같이 쓰면 다른 사람의 사용량 때문에 GPU 메모리 부족이 날 수 있고, 이 오류는 참가자 실패(`runtime_error`)로 기록됩니다. 대회용 GPU를 따로 배정받으세요.
- 평가기를 바꾸면(`docker` ↔ `remote` ↔ `sandbox`) 순위표는 현재 평가기의 점수만 보여 줍니다. 대회 중에는 평가기를 바꾸지 않습니다.

### Docker 없는 GPU 서버 (`EVALUATOR=sandbox`)

GPU 서버에 Docker를 설치할 수 없을 때 씁니다. 컨테이너 대신 단계마다 bubblewrap 샌드박스를 띄웁니다. 샌드박스는 `/usr`, `/etc`의 일부 파일, 채점 환경만 읽기 전용으로 봅니다. 그 밖에는 그 단계의 폴더만 봅니다(추론: 제출 코드와 평가 입력은 읽기 전용, `/output`만 쓰기 가능). 네트워크·권한·환경 변수도 없습니다. 패키지 설치 단계는 제출 코드와 평가 입력을 보지 않고, PyPI에서 받는 두 번째 설치 단계만 네트워크를 씁니다. 자세한 것은 `apps/api/app/evaluators/sandbox_launch.py` 맨 위에 있습니다.

**서버 주인에게 요청할 것** (root 필요):
- `bubblewrap` 설치(`sudo apt install bubblewrap`)
- 비특권 user namespace 허용. Ubuntu 23.10 이후는 AppArmor가 막으므로 bwrap용 프로필을 두거나 `kernel.apparmor_restrict_unprivileged_userns=0`을 설정합니다.
- 메모리·CPU·프로세스 제한을 쓰려면(기본) 접속 계정의 사용자 systemd(`sudo loginctl enable-linger <계정>`)와 cgroup v2의 memory·pids 위임이 필요합니다. 안 되면 `.env`에 `EVAL_SANDBOX_LIMITS=none`을 적습니다. 이때는 시간·출력 크기 제한만 남고, 메모리를 많이 쓰는 제출이 서버 전체 메모리를 쓸 수 있습니다.

**접속 계정으로 한 번 할 것** (root 불필요): 이 저장소의 `apps/evaluator` 폴더를 GPU 서버에 복사하고 채점 환경을 만듭니다. 기본 패키지와 대회 lock의 wheel을 내려받아 `--root` 아래에만 설치합니다. CUDA용 torch 때문에 몇 GB가 듭니다.
```bash
scp -r apps/evaluator evaluator@<GPU 서버>:admin-eval-setup
ssh evaluator@<GPU 서버> 'sh admin-eval-setup/setup-server.sh --root "$HOME/admin-eval" --python /usr/bin/python3.12 --torch-index https://download.pytorch.org/whl/cu126'
```
`--torch-index`는 서버의 드라이버와 GPU를 지원하는 torch 빌드를 고릅니다. P100처럼 오래된 GPU는 그 GPU(sm_60)를 아직 포함한 빌드여야 합니다. 맞는지는 아래 점검이 샌드박스 안에서 GPU로 계산해 보고 알려 줍니다. Python 3.12가 없고 root도 없으면 `uv python install 3.12`로 받은 Python을 `--python`에 줍니다. 끝나면 평가 입력 3개 파일을 `<root>/input`에 복사합니다.

**웹 서버 `.env`**: `EVAL_REMOTE_EVALUATOR=sandbox`, `EVAL_SANDBOX_ROOT=<root>`, `EVAL_REMOTE_WORK_DIR=<root>/work`, `EVAL_REMOTE_INPUT_DIR=<root>/input`, `EVAL_GPUS`(비우면 CPU만). SSH 키와 호스트 키는 위 "설정"과 같습니다.

**점검**: 처음 접속할 때와 그 뒤 1분마다 아래를 확인하고, 하나라도 빠지면 연결을 취소합니다. 손으로는 `docker compose ... exec worker python -m app.evaluators.sandbox`로 확인합니다.

| 확인 | 빠졌을 때 |
| --- | --- |
| SSH 접속, Linux, (`EVAL_GPUS`가 있으면) NVIDIA 드라이버와 GPU 번호 | `remote`와 같은 안내 |
| bwrap 설치, user namespace로 샌드박스를 만들 수 있는지 | 설치 안내, bwrap 오류 첫 줄과 AppArmor·sysctl 안내 |
| (`EVAL_SANDBOX_LIMITS=cgroup`) `systemd-run --user`와 memory·pids 컨트롤러 | `enable-linger`·위임 안내, 또는 `none`으로 끄는 방법 |
| 채점 환경(`VERSION`의 설치기 버전, `env/bin/python`, 설치기, wheels) | `setup-server.sh` 실행 안내 |
| 평가 입력 3개 파일, 작업 폴더 쓰기, 디스크 여유 | `remote`와 같은 안내 |
| 실제 샌드박스에서 짧은 프로그램 실행: 네트워크 차단, `~/.ssh`가 안 보임, 평가 입력이 보임, GPU 계산 | 실패한 항목과 원인. 통과하면 10분 동안은 다시 띄우지 않음 |

`remote`와 다른 점:
- 한 단계가 끝나면 그 단계의 런처를 pid 파일로 찾아 종료하고, 런처가 죽으면 샌드박스도 함께 죽습니다. 연결이 끊겨도 런처의 타이머(제한 + 15초)가 샌드박스를 멈춥니다.
- `EVAL_GPUS`의 GPU는 `CUDA_VISIBLE_DEVICES`로 고릅니다. 샌드박스에는 NVIDIA 장치가 모두 보이므로, 참가자 코드가 이 변수를 지우면 다른 GPU도 쓸 수 있습니다. 대회용 GPU만 보이는 서버(또는 컨테이너)를 받는 것이 가장 안전합니다.
- 서버 주인이 user namespace를 허용하지 않으면 샌드박스는 쓸 수 없습니다. 이때는 아래처럼 격리를 끄고 채점합니다.

**격리 끄기** (관리자 화면 → 설정 → "채점 격리"): Docker 기본 보안 설정의 컨테이너처럼 user namespace가 막힌 서버용입니다. 기본값은 켜짐이고, 끄면 조작 기록에 남습니다. 바꾸면 다음 채점 전에 서버를 다시 점검합니다.
- 끄면 단계마다 bwrap 없이 서버에서 바로 실행합니다. 명령의 `/submission`, `/input`, `/output`, `/deps`는 그 제출의 실제 폴더로 바꿔 넘깁니다. 참가자 코드가 이 경로를 인자로 받지 않고 코드에 직접 적었다면 동작하지 않습니다.
- **네트워크를 막지 못합니다.** 참가자 코드가 외부 모델·데이터를 내려받을 수 있고, 서버에서 읽을 수 있는 파일은 읽을 수 있습니다. 정답은 서버에 없습니다.
- 접속 계정이 root면 제출 코드는 따로 만든 일반 uid(`EVAL_SANDBOX_RUN_UID`, 기본 64000)로 실행합니다. 그래서 채점 환경과 다른 제출의 폴더를 바꿀 수 없고, 프로세스 수는 `EVAL_PIDS`로 제한합니다. 단계가 끝나면 그 uid의 프로세스를 모두 종료하므로 GPU 서버 하나에 worker는 하나만 둡니다. 이 uid가 채점 환경과 평가 입력을 읽어야 하므로 `--root`와 Python은 `/root` 밖(예: `/srv/admin-eval`)에 둡니다. `setup-server.sh`가 이를 확인합니다.
- 접속 계정이 root가 아니면 제출 코드는 접속 계정 권한으로 실행됩니다.
- 메모리·CPU 제한(cgroup)은 쓰지 않습니다. 시간·출력 크기·프로세스 수 제한과 컨테이너 전체의 메모리 제한만 남습니다. 점검은 bwrap·user namespace·cgroup 항목을 건너뛰고, 실제 점검 프로그램으로 평가 입력과 GPU만 확인합니다.
- 손으로 점검하려면 `python -m app.evaluators.sandbox --no-isolation`을 실행합니다.

## HTTPS 운영

- `.env`의 `SECRET_KEY`와 `POSTGRES_PASSWORD`를 새 난수로 바꿉니다. URL에 들어가는 비밀번호는 영숫자를 쓰거나 URL 인코딩합니다.
- TLS 리버스 프록시를 `gateway`의 3000 포트 앞에 두고 정확한 `APP_ORIGIN`, `COOKIE_SECURE=true`를 설정합니다. `gateway`는 기본으로 loopback에만 열려 있습니다.
- **앞단 프록시의 요청 본문 한도를 ZIP 상한(500 MB)보다 크게** 잡고, 업로드가 끝날 때까지 끊기지 않게 요청 시간 제한을 늘립니다. 한도가 작으면 큰 ZIP이 접수되지 않습니다. 대회 전에 실제 크기의 파일로 올려 봅니다.
- 앱은 전달된 `X-Forwarded-For`를 신뢰하지 않습니다. 로그인 시도 제한은 아이디별로 분당 10회입니다.
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
