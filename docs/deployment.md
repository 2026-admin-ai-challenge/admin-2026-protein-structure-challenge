# 배포와 서버 구성

## 구성

| 서비스 | 역할 | 접근하는 것 |
| --- | --- | --- |
| `gateway` | nginx. 유일한 입구(포트 3000). 화면은 `web`으로, `/api`는 `api`로 직접 전달 | — |
| `web` | Next.js 화면 | — |
| `api` | 인증, 접수, 조회, 관리자 API | DB, 참가자 공개 데이터(읽기 전용), 제출 ZIP 저장소(쓰기) |
| `worker` | 대기열 채점 | DB, 제출 ZIP 저장소(읽기·삭제: 보관 정책에 따른 정리). 실제 채점 시 숨긴 정답과 Docker 소켓(이 컴퓨터에서 채점) 또는 GPU 서버 SSH 키(원격 채점) |
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
- 서버가 비특권 user namespace는 허용하고 mount만 막는다면(예: seccomp만 푼 Docker 컨테이너, `unshare --user --net true`가 성공하는 서버) `.env`에 `EVAL_SANDBOX_NETNS=1`을 적고 `up -d worker`로 다시 시작합니다. 그러면 온라인 설치를 뺀 모든 단계(오프라인 설치, 추론, 점검)를 `unshare --user --net`으로 감싸 새 network namespace에서 실행합니다. 꺼진 loopback 하나만 보이므로 외부망과 DNS는 물론 같은 서버의 포트에도 닿지 않습니다. GPU, 평가 입력, 작업 폴더는 그대로 씁니다. 점검 프로그램이 네트워크가 막힌 것을 다시 확인하고, 관리자 화면 worker 설명에 "네트워크 차단(온라인 설치 제외)"이 보입니다. 서버가 user namespace를 막으면 단계가 시작하지 못해 점검에서 연결을 취소하므로, 네트워크가 열린 채 채점되지는 않습니다. 온라인 설치 단계는 여전히 네트워크와 서버의 파일에 접근할 수 있습니다.
- 접속 계정이 root면 제출 코드는 따로 만든 일반 uid(`EVAL_SANDBOX_RUN_UID`, 기본 64000)로 실행합니다. 그래서 채점 환경과 다른 제출의 폴더를 바꿀 수 없고, 프로세스 수는 `EVAL_PIDS`로 제한합니다. 단계가 끝나면 그 uid의 프로세스를 모두 종료하므로, worker 컨테이너를 더 띄우지 말고 아래 "여러 제출 동시 채점"처럼 `WORKER_SLOTS`로 늘립니다(슬롯마다 uid가 다릅니다). 이 uid가 채점 환경과 평가 입력을 읽어야 하므로 `--root`와 Python은 `/root` 밖(예: `/srv/admin-eval`)에 둡니다. `setup-server.sh`가 이를 확인합니다.
- 접속 계정이 root가 아니면 제출 코드는 접속 계정 권한으로 실행됩니다.
- 메모리·CPU 제한(cgroup)은 쓰지 않습니다. 시간·출력 크기·프로세스 수 제한과 컨테이너 전체의 메모리 제한만 남습니다. 점검은 bwrap·user namespace·cgroup 항목을 건너뛰고, 실제 점검 프로그램으로 평가 입력과 GPU만 확인합니다.
- 손으로 점검하려면 `python -m app.evaluators.sandbox --no-isolation`을 실행합니다.

**여러 제출 동시 채점** (`remote`, `sandbox`): `.env`에 `WORKER_SLOTS=5`, `EVAL_GPU_PICK=free`, `EVAL_GPUS=all`(또는 후보 GPU 번호, 예: `0,3,4,6,7`)을 적고 `up -d worker`로 다시 시작합니다.
- worker 프로세스 하나가 슬롯마다 스레드를 하나씩 돌립니다. 관리자 화면의 worker 목록에 `<이름>-1`부터 `<이름>-5`까지 따로 보이고, 멈춘 슬롯은 몇 초 안에 다시 시작합니다.
- 프로세스가 아니라 스레드인 이유는 메모리입니다. 채점 라이브러리(pandas 등)를 불러온 worker 프로세스 하나가 약 185MB를 쓰는데, 웹 VM은 메모리가 1GB가 안 됩니다. 스레드는 이를 함께 쓰고, 채점의 무거운 부분은 GPU 서버에서 돌기 때문에 worker는 대부분 기다리기만 합니다.
- 슬롯들은 GPU 서버에 대해 알게 된 것을 함께 씁니다. 접속 점검은 슬롯 수와 관계없이 1분에 한 번, GPU 사용량은 15초에 한 번만 SSH로 묻습니다. 채점 중 출력 폴더 크기는 `sandbox` 런처가 GPU 서버에서 1초마다 직접 확인하고 한도를 넘으면 멈추므로, SSH로 묻지 않습니다(GPU 서버에서 Docker를 쓰는 `remote`는 3초마다 묻습니다). 서버가 바쁠 때 새 SSH 접속을 거부하는 일을 줄이기 위해서입니다.
- 접속 점검의 짧은 GPU 계산도 그 순간 가장 빈 GPU에서 합니다. GPU가 모두 보이면 CUDA가 GPU 0을 쓰는데, 다른 사용자가 GPU 0을 채우면 점검이 실패해 모든 슬롯이 멈추기 때문입니다.
- 채점을 시작하기 직전에 GPU 사용량을 3초 동안 읽습니다. 사용 메모리가 `EVAL_GPU_FREE_MEMORY_MIB`(기본 2048) 미만이고 사용률이 `EVAL_GPU_FREE_UTILIZATION`(기본 10)% 미만인 GPU 가운데, 다른 슬롯이 쓰지 않는 가장 빈 GPU 1장을 그 채점에 줍니다. 어느 GPU였는지는 제출의 운영진 로그 첫 줄에 남습니다.
- 빈 GPU가 없으면 제출은 대기열에 그대로 두고, worker 상태에 GPU별 사용량과 기다리는 이유를 보여 줍니다. 15초마다 다시 확인합니다.
- 시작할 때만 확인하므로, 채점 도중 다른 사용자가 같은 GPU에 작업을 올리는 것은 막지 못합니다. 공용 서버라면 대회 기간에 GPU를 비워 달라고 서버 관리자에게 요청하세요.
- 격리를 끈 `sandbox`에서 슬롯 n은 uid `EVAL_SANDBOX_RUN_UID + n - 1`(기본 64000부터)로 실행합니다.
- 메모리·CPU 제한이 없을 때(격리 끔, `EVAL_SANDBOX_LIMITS=none`)는 동시에 도는 제출이 서버의 CPU와 메모리를 나눠 씁니다.
- `EVAL_GPU_PICK=fixed`인데 `WORKER_SLOTS`가 2 이상이면 모든 슬롯이 같은 GPU를 쓰게 되므로, 점검에서 연결을 취소하고 이유를 보여 줍니다.

## CI 자동 배포

`main`에 push(머지)되면 GitHub Actions [`deploy.yml`](../.github/workflows/deploy.yml)이 웹 서버에 배포합니다. Actions 화면에서 수동으로 실행할 수도 있습니다.

1. `api`, `worker`, `web` 이미지를 빌드해 `ghcr.io/2026-admin-ai-challenge/admin-2026-protein-structure-challenge/<이름>`에 `latest`와 커밋 SHA 태그로 올립니다. 서버(1 OCPU)에서는 빌드하지 않습니다.
2. 서버에 SSH로 접속해 `docker-compose.yml`, `docker-compose.ghcr.yml`, `docker-compose.remote.yml`, `deploy/nginx.conf`를 `~/admin-2026-protein-structure-challenge/`에 복사하고, compose 파일로 `pull`과 `up -d`를 실행한 뒤 오래된 이미지를 지웁니다. 서버의 `.env`는 바꾸지 않습니다.
3. 저장소 secrets `DEPLOY_KEY`(SSH 개인 키)와 `DEPLOY_HOST`가 필요합니다. 레지스트리 로그인은 작업마다 발급되는 토큰으로 하고 끝나면 로그아웃합니다.

이 배포에는 `docker-compose.evaluator.yml`이 들어가지 않습니다. 서버 `.env`에 `EVAL_SSH_HOST`가 있으면 `docker-compose.remote.yml`을 얹어 원격 GPU 채점으로 실행하고([원격 GPU 채점](#원격-gpu-채점-ssh)), 없으면 `EVALUATOR=mock`으로 실행합니다. 배포 로그의 `scoring: remote GPU` 또는 `scoring: mock` 줄로 어느 쪽인지 확인합니다. 원격 설정이 반쯤만 있으면 컨테이너를 다시 만들기 전에 빠진 값의 이름을 남기고 멈춥니다. 같은 서버에서 Docker 평가기를 켜 두면 다음 머지 때 api·worker가 mock 설정으로 다시 만들어집니다.

같은 이미지를 손으로 받으려면 처음 한 번 `docker login ghcr.io`(read:packages 토큰)를 한 뒤 다음을 실행합니다.

```bash
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml up -d
```

## 서버 `.env` 수정

운영 서버가 실제로 쓰는 `.env`는 서버 디스크의 `~/admin-2026-protein-structure-challenge/.env` 하나뿐입니다. 저장소의 `.env.example`은 템플릿이라 고쳐도 운영에 영향이 없고, 서버의 `.env`는 저장소에 올라가지 않습니다. CI 자동 배포는 compose 파일과 `deploy/nginx.conf`만 덮어쓰고 `.env`는 건드리지 않으므로, 한 번 고치면 다음 배포에도 유지됩니다. Compose는 compose 파일과 같은 디렉터리의 `.env`만 자동으로 읽습니다. 다른 이름으로 두면 읽지 않습니다.

아래는 **웹 서버**(CI가 배포하는 그 서버) 기준입니다. `$dc`는 이 명령이고, **compose 파일 두 개를 항상 같이 지정합니다.** 하나만 쓰면 GHCR 이미지 대신 빌드를 시도합니다. 웹 서버에는 저장소가 없어 바로 실패하고, 저장소가 있는 장비에서는 1 OCPU 기준 30분이 걸리는 빌드가 시작됩니다.

실채점 장비는 compose 조합이 다릅니다(`docker-compose.yml` + `docker-compose.evaluator.yml`). 그 장비에서 아래 `$dc`를 쓰면 `api`와 `worker`가 `EVALUATOR=mock`으로 다시 만들어져 가짜 점수로 채점합니다. 실채점 장비에서는 `-f docker-compose.evaluator.yml`을 얹은 조합을 그대로 씁니다.

웹 서버가 원격 GPU로 채점 중이면(`.env`에 `EVAL_SSH_HOST`가 있으면) **`-f docker-compose.remote.yml`도 붙입니다.** 빼면 같은 이유로 mock으로 바뀝니다. 아래 두 번째 줄이 CI와 같은 기준으로 붙여 줍니다.

```bash
cd ~/admin-2026-protein-structure-challenge
dc="docker compose -f docker-compose.yml -f docker-compose.ghcr.yml"
grep -Eq '^EVAL_SSH_HOST=[^[:space:]]' .env && dc="$dc -f docker-compose.remote.yml"
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
| `DATA_HOST_DIR` | api(마운트 경로). 실채점 장비에서는 worker에도 `public`·`private`로 마운트됩니다 | `up -d api worker` |
| `SECRET_KEY` | api, worker | **대회 중 바꾸지 않습니다.** 세션 쿠키(JWT) 서명 키라서 전원이 로그아웃됩니다 |
| `POSTGRES_PASSWORD` | postgres, api, worker | **단독으로 바꾸지 않습니다.** Postgres는 DB를 처음 만들 때만 이 값을 쓰므로, `.env`만 고치면 접속 문자열만 바뀌어 인증에 실패합니다 |
| `TEAM_SUBMISSION_LIMIT` | api | 새 DB의 초기값입니다. 운영 중에는 효과가 없고 관리자 화면에서 바꿉니다 |
| `EVALUATOR` | — | compose가 정합니다. `.env`로 바꾸지 않습니다 |
| `EVAL_REMOTE_EVALUATOR` | api, worker | `up -d api worker`. 대회 중에는 바꾸지 않습니다(순위표는 현재 평가기의 점수만 보여 줍니다) |
| `EVAL_SSH_*`, `EVAL_REMOTE_*`, `EVAL_SANDBOX_*`, `EVAL_GPU*`, `WORKER_SLOTS`, `EVAL_IMAGE` 등 원격 채점 값 | worker | `up -d worker`. `EVAL_SSH_HOST`를 처음 넣거나 지울 때는 `$dc`를 다시 정한 뒤 `up -d api worker` |

각 변수의 기본값과 의미는 [용량·환경변수](#용량환경변수)에 있습니다. 일정, 팀당 제출 횟수, 실패 차감, 최종 순위 기준, 동결은 `.env`가 아니라 관리자 화면 "현황·설정"에서 바꿉니다.

### 잘못 적은 값

- **바로 멈추는 값**: `SECRET_KEY`가 32자 미만, 숫자 변수에 숫자가 아닌 값, `ZIP_RETENTION`이 `best_public`·`keep_all` 외의 값이면 `api`와 `worker`가 시작하면서 사유를 로그에 적고 죽습니다(`app/config.py`). `$dc ps`에서 재시작을 반복하고 `/api/health`가 응답하지 않습니다.
- **조용히 무시되는 값**: `LAUNCH_AT`의 형식이 틀리면 오류 없이 기본값(`2026-11-01T13:00:00+09:00`)으로 돌아갑니다. 오타로 주제가 미리 공개되지 않게 한 동작이라, "고쳤는데 그대로"일 때는 형식을 확인합니다.
- **`LAUNCH_AT`은 반드시 정확한 ISO 8601로 적습니다**(예: `2026-11-01T13:00:00+09:00`). API는 `datetime.fromisoformat`만 받아들여 틀리면 기본값으로 돌아가지만, 웹은 더 관대한 `Date.parse`를 써서 `2026/11/15 13:00:00` 같은 값도 해석합니다. 두 값이 어긋나면 화면은 카운트다운인데 API는 열려 있어, `/api`로 직접 요청하면 주제를 알 수 있습니다(`gateway`는 `/api`를 Next.js를 거치지 않고 보냅니다). 바꾼 뒤에는 화면과 `/api`를 함께 확인합니다.
- **`APPLY_URL`은 비워도 버튼이 사라지지 않습니다.** 빈 값이면 코드에 있는 기본 신청 주소로 돌아갑니다. 버튼을 없애려면 `https://`로 시작하지 않는 값을 넣어야 합니다(`app/launch.ts`).
- 설정되지 않은 변수 이름은 오류 없이 무시됩니다. 쓰이는 변수만 효과가 있습니다.

### 작업 시점

`api`를 다시 만드는 동안 몇 초간 API 요청이 끊기고, 업로드 중인 ZIP은 실패합니다. 채점 중에 `worker`를 다시 만들면 그 제출은 `running`으로 남고 `WORKER_STALE_SECONDS`(120초) 뒤에 `queued`로 돌아가 다시 채점됩니다. 같은 제출이 세 번 중단되면 `system_error`가 되므로, 제출이 몰리는 시간과 채점 진행 중은 피합니다. `.env`에는 비밀값이 있으니 권한은 `chmod 600`으로 둡니다.

## HTTPS 운영

- `.env`의 `SECRET_KEY`와 `POSTGRES_PASSWORD`를 새 난수로 바꿉니다. URL에 들어가는 비밀번호는 영숫자를 쓰거나 URL 인코딩합니다.
- TLS 리버스 프록시를 `gateway`의 3000 포트 앞에 두고 정확한 `APP_ORIGIN`, `COOKIE_SECURE=true`를 설정합니다. `gateway`는 기본으로 loopback에만 열려 있습니다.
- **앞단 프록시의 요청 본문 한도를 ZIP 상한(500 MB)보다 크게** 잡고, 업로드가 끝날 때까지 끊기지 않게 요청 시간 제한을 늘립니다. 한도가 작으면 큰 ZIP이 접수되지 않습니다. 대회 전에 실제 크기의 파일로 올려 봅니다.
- 앱은 전달된 `X-Forwarded-For`를 신뢰하지 않으므로 API에는 모든 요청이 `gateway` 주소 하나에서 온 것으로 보입니다. 그래서 로그인 시도 제한 분당 120회는 사이트 전체가 함께 씁니다(대회 시작 때 약 20팀 × 3~4명이 한꺼번에 로그인하는 양). 틀린 비밀번호는 입력한 팀 이름별로 분당 10회까지입니다. 관리자 아이디로 로그인하면 두 제한 모두 걸리지 않습니다.
- Linux에서 데이터 디렉터리는 컨테이너 UID 10001이 읽을 수 있어야 합니다(실제 채점 모드의 worker는 root로 실행).

## 데이터 공개 정책

웹 데이터 탭은 운영자가 데이터 버전을 승인하고, 시작·종료 시각을 설정해 대회를 연 뒤 `[start_time, end_time)` 동안만 다운로드 버튼을 보여 줍니다. 파일 주소(`/api/datasets/{kind}`) 자체는 승인·일정과 관계없이 **누구나 언제든** 받을 수 있습니다. 요청마다 DB에서 공개 여부를 확인하면 그 연결이 파일 전송이 끝날 때까지 묶이는데, 10-31 부하테스트에서 느린 다운로드 몇 건이 연결 풀을 모두 잡아 사이트 전체가 멈췄기 때문입니다. 평가 입력과 정답은 어떤 경로로도 내려받을 수 없습니다.

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
