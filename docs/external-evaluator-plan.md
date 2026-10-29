# 외부 서버 채점 연결 계획

상태: 구현됨, 실제 GPU 서버에서는 아직 검증 전(8절 4단계). 작성일 2026-10-27.

구현 위치: `apps/api/app/evaluators/sandbox.py`(worker 쪽 점검과 실행), `sandbox_launch.py`(GPU 서버에서 샌드박스를 띄우는 런처), `apps/evaluator/setup-server.sh`(채점 환경 설치), `docker-compose.remote.yml`의 `EVAL_REMOTE_EVALUATOR=sandbox`. 운영 절차는 `docs/deployment.md`의 "Docker 없는 GPU 서버" 절에 있습니다.

실제 서버 점검 결과(2026-10-28): 받은 서버(168.188.128.36:20780)는 Docker 컨테이너이고, 기본 seccomp·AppArmor 설정이 user namespace를 막아 샌드박스를 쓸 수 없다. 서버 관리자에게 컨테이너를 `--security-opt seccomp=unconfined --security-opt apparmor=unconfined`로 다시 만들어 달라고 요청할 예정이고, 그 전까지는 격리를 끄고 진행한다.

계획과 달라진 점:
- user namespace가 막힌 서버용으로 "격리 끄기"를 만들었다(관리자 화면, 기본은 켜짐). 끄면 네트워크를 막지 못한다. 접속 계정이 root면 제출 코드는 별도 일반 uid로 실행해, 채점 환경과 다른 제출을 바꾸지 못하게 한다. 관리자가 컨테이너 설정을 바꿔 주면 다시 켜면 된다.
- 동시 실행(6절)은 GPU를 고정 배정하지 않고 채점마다 빈 GPU를 고른다(2026-10-29 결정). 서버가 공용이라 어느 GPU가 빌지 미리 알 수 없기 때문이다. `WORKER_SLOTS`만큼 worker 스레드를 돌리고(웹 VM 메모리가 1GB 미만이라 프로세스 대신 스레드), `EVAL_GPU_PICK=free`면 채점 직전에 사용량이 기준 미만이고 다른 슬롯이 쓰지 않는 GPU 1장을 준다. 실서버 다중 슬롯 검증은 하지 않았다(워커 2개 고정 배정 시험만 2026-10-29에 통과).
- `models/` 디렉터리는 두지 않는다(9절 결정).

## 1. 배경과 결정

채점용으로 대여할 서버 안에서는 Docker를 설치할 수 없을 가능성이 크다. 그래서 지금의 `docker` / `remote` 평가기가 쓰는 `docker run` 격리를 그대로 쓸 수 없다.

두 방식을 비교해 **서버 한 대에서 모든 제출을 채점하는 방식**으로 정했다.

| | 팀마다 포트 하나씩 대여 | 서버 한 대에서 처리 (채택) |
|---|---|---|
| 결과 신뢰 | 참가자가 서버를 제어하므로 코드가 실제로 실행됐는지 확인할 수 없다 | 우리가 실행하므로 확인할 수 있다 |
| 시간·외부 자원 제한 | 강제할 수 없다 | 강제할 수 있다 |
| 숨김 평가 입력 | 참가자 서버에 놓인다 (라벨은 웹 서버에만 있다) | 채점 서버에만 있다 |
| 운영 | 접속 정보, 환경, GPU 편차를 팀 수만큼 관리 | 서버 한 대 |

팀별 포트 방식은 사실상 "예측 결과 제출" 대회가 되므로, 호스트가 강제하지 않는 한 쓰지 않는다.

## 2. 바뀌는 것과 그대로인 것

- 그대로: 웹 VM이 라벨을 갖고 있고, 채점 서버에서는 `predictions.csv`만 가져온다. SSH 연결, 접속 점검(처음 연결할 때와 1분마다), 시간 제한 감시, 출력 크기 제한, 결과 회수, `mock`과 `docker` 평가기.
- 바뀜: `docker.py`의 `_isolated()`, `build_command()`, `install_command()`, `gpu_args()`, `ready()`가 하던 격리와 환경 제공을 서버 쪽 읽기 전용 환경과 샌드박스로 옮긴다.
- 새 평가기: `EVALUATOR=sandbox`. SSH 부분은 `remote.py`를 재사용하고, 컨테이너 대신 샌드박스를 실행한다.

## 3. 채점 서버 구성

```
/opt/admin-eval/
  env/        # 대회 락 89개 패키지 + CUDA torch가 든 공용 venv (root 소유, 읽기 전용)
  wheels/     # 오프라인 설치용 wheel 캐시
  input/      # 숨김 평가 입력 (읽기 전용)
  runs/<id>/  # 제출마다 생성: submission/, output/, deps/ (끝나면 삭제)
  VERSION     # env의 락 해시 (지금 이미지 라벨 admin-eval.installer를 대체)
```

- `env/`는 Docker 이미지가 하던 일을 한다. `apps/evaluator`의 CPU 전용 torch는 CUDA 빌드로 바꿔야 한다.
- 접속 점검(`ready()`)은 이미지 존재 대신 다음을 확인한다: `env/VERSION` 해시, 샌드박스 도구, 입력 디렉터리, `nvidia-smi`, 디스크, 샌드박스로 GPU를 쓰는 짧은 실행. 실패하면 연결을 취소하고 원인과 해결 방법을 각각 보여 준다 (기존 요구사항 유지).
- 점검은 서버에 아무것도 설치하지 않는다.

## 4. 실행 샌드박스 (bubblewrap 권장)

현재 컨테이너가 받는 제한을 다음처럼 옮긴다.

| 지금 (docker run) | 샌드박스 |
|---|---|
| `--network none` | `--unshare-all` (net, pid, ipc, uts) |
| `--read-only`, `-v ...:ro` | `env/`, `submission/`, `input/`를 읽기 전용 바인드 |
| `/output:rw` | `runs/<id>/output`만 쓰기 가능 바인드 |
| `--tmpfs /tmp` | tmpfs `/tmp` |
| `--cap-drop ALL`, `no-new-privileges`, 비root | 비특권 user namespace로 실행 |
| `--pids-limit`, `--cpus`, `--memory` | cgroup(`systemd-run --user`)이 되면 `TasksMax`, `CPUQuota`, `MemoryMax`. 안 되면 `RLIMIT_NPROC`, `RLIMIT_FSIZE` |
| `--gpus "device=N"` | `/dev/nvidia*`만 노출하고 실행마다 `CUDA_VISIBLE_DEVICES`를 하나로 지정 |
| `timeout --signal=KILL` | 그대로 사용 |

- `--die-with-parent`로 워커가 죽으면 샌드박스도 같이 종료한다.
- 주소 공간 제한(`RLIMIT_AS`)은 CUDA와 충돌하므로 쓰지 않는다.
- 평가 입력과 제출 코드는 읽기 전용이고, 라벨, 공개/비공개 구분, DB 정보는 채점 서버에 없다.

## 5. 패키지 설치 (requirements.txt)

지금과 같은 2단계를 유지한다.

1. `wheels/`에서 네트워크 없이 설치한다.
2. 부족하면 wheel만 허용하는 상태로 PyPI에서 받는다.

- 결과는 `runs/<id>/deps/`에 두고 추론 샌드박스에 `PYTHONPATH`로 읽기 전용 마운트한다. Docker 볼륨을 대체한다.
- 설치 샌드박스에는 제출 코드와 평가 입력을 마운트하지 않는다.
- 네트워크 오류 vs 팀의 실패 구분(`NETWORK_ERRORS`), 설치 시간 제한, 비정상 종료 코드 판정은 그대로 둔다.
- 남은 `runs/<id>/`는 기존 `prune_abandoned`와 같은 방식으로 정리한다.

## 6. 동시 실행

GPU 하나에 제출 하나를 배정한다. 워커 슬롯 수를 GPU 수에 맞춘다 (후보 서버가 P100 8장이면 최대 8개). GPU를 나눠 쓰다 생기는 메모리 부족과 시간 편차를 막는다.

구현(2026-10-29): `WORKER_SLOTS=N`이면 worker 프로세스 하나가 슬롯마다 스레드를 돌린다. 프로세스마다 채점 라이브러리가 약 185MB를 쓰는데 웹 VM은 954MB라서 프로세스로는 2개도 들어가지 않는다. 슬롯마다 이름과 실행 uid(`EVAL_SANDBOX_RUN_UID + 슬롯 - 1`)가 다르고, 접속 점검의 GPU 계산도 그 슬롯의 uid로, 그 순간 가장 빈 GPU에서 한다. `EVAL_GPU_PICK=free`면 슬롯이 제출을 가져가기 직전에 `nvidia-smi`로 3초 동안 사용량을 읽는다. 사용 메모리와 사용률이 기준 미만이고 실행 중인 다른 제출이 잡고 있지 않은 GPU 중 가장 빈 것을 준다. 배정은 DB(`submissions.gpu`)에 기록하고 설정 행 잠금 아래에서 하므로 두 슬롯이 같은 GPU를 받지 않는다. 빈 GPU가 없으면 제출은 대기열에 남는다. 채점 도중 다른 사용자가 같은 GPU를 쓰기 시작하는 것은 막지 못한다.

## 7. 서버 환경에 따른 분기 (확인 필요)

대여 서버에서 먼저 확인할 것:

```bash
unshare -Ur true && echo userns-ok; which bwrap nsjail firejail; nvidia-smi -L; id; cat /sys/fs/cgroup/cgroup.controllers
```

- user namespace 허용: 위 설계 그대로 진행한다.
- user namespace 불가: 네트워크 차단을 강제할 수 없다. 제출마다 전용 유저로 실행하고 `ulimit`을 건다. 라벨이 채점 서버에 없고 ZIP 검사를 이미 하므로, 최악의 노출은 평가 입력과 서버 부하로 제한된다. 이 경우 위험을 팀에 알리고 진행 여부를 정한다.
- root 권한 여부, 패키지 설치 가능 여부, 외부(PyPI) 접속 가능 여부도 같이 확인한다.

## 8. 작업 순서

1. 서버 환경 확인 (7절).
2. `env/` 구성 스크립트와 CUDA torch 락 정리. 서버에 설치하는 일은 사람이 실행한다. (스크립트 완료: `apps/evaluator/setup-server.sh`. 락은 그대로 두고 CUDA 빌드는 `--torch-index`로 고른다.)
3. 샌드박스 실행기와 `ready()` 점검 구현 (`EVALUATOR=sandbox`), 단위 테스트. (완료: `apps/api/tests/test_sandbox.py`)
4. 실제 서버에서 샘플 제출(`testmodel.zip`)로 통과, 시간 초과, 메모리 초과, 출력 이상, 네트워크 차단을 확인.
5. 관리자 페이지의 SSH 주소 입력(허용 목록, 호스트 키 확인, 감사 기록)과 `deploy.yml` 연결. 서버 `.env`에 `EVAL_SSH_HOST`가 있을 때만 새 구성을 추가하므로, 그전에는 병합해도 운영이 바뀌지 않는다.

## 9. 제출 규칙 결정 (2026-10-27)

- 외부 데이터와 외부 사전학습 가중치는 **전면 금지**한다. 허용 모델 목록과 서버 `models/` 디렉터리는 두지 않는다.
- 모델 파일 크기 상한은 **현행 유지**한다 (압축 해제 합계 `MAX_UNZIPPED_BYTES` 2GB, 파일 `MAX_ZIP_ENTRIES` 2000개).
- 파일 종류 제한은 **현행 유지**한다 (필수 파일만 검사하고 확장자는 제한하지 않는다).
- 코드 변경은 없다. `docs/competition.md` 규칙에 금지를 명시했다.
- 집행 한계: 추론 중 다운로드는 네트워크 차단으로 막지만(user namespace가 허용될 때), ZIP에 가중치나 데이터를 넣어 내는 것은 코드로 구분할 수 없다. 수상 후보의 학습 코드 재현 제출(`competition.md` 규칙)과 사후 검토로 확인한다.

## 10. 열린 질문

- 대여 서버 종류 (컨테이너 안의 SSH 계정인지, 일반 VM인지)와 root 권한.
- user namespace 허용 여부와 cgroup 위임 여부.
- GPU 종류와 개수, CUDA 드라이버 버전 (`env/`의 torch 빌드에 영향).
- 서버에서 PyPI에 접속할 수 있는지.
- 이전 계획(GHCR 이미지 배포, `evaluator-image.yml`)을 유지할지. 서버 한 대 방식에서는 `env/`가 이미지를 대체하므로 이미지 배포는 필요 없어질 수 있다.
