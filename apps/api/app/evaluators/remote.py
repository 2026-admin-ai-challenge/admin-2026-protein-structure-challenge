"""Runs participant inference on a GPU machine reached over SSH.

Everything that decides the result stays here: the worker unpacks and checks the ZIP, the
hidden labels never leave this machine, and the score is computed by the worker from the
predictions file it fetches back. The GPU machine only runs the same locked-down containers
as docker.py (no network, read-only root, no capabilities), with `--gpus` added for
inference. It receives the submission's files and the evaluation INPUT (no labels).

Paths: EVAL_WORK_HOST_DIR and EVAL_INPUT_HOST_DIR are paths ON THE GPU MACHINE. A
submission is unpacked here, then copied to <EVAL_WORK_HOST_DIR>/submission-<id>-<random>/
over SSH as a tar stream, and removed again when the run ends.

Nothing is installed on the GPU machine for you. Before the first submission, and then
every minute, `examine` checks the settings here, then that the machine is Linux and has an
NVIDIA driver, Docker the SSH account may use, the NVIDIA Container Toolkit, the evaluation
image, the evaluation input and disk space, and that a container really sees the GPU. If
anything is missing the connection is cancelled: the worker takes no submissions and says
why, and how to fix it, on the admin page. The checks only read; they never change the machine.

A submission always runs on the machine that last passed every check, even if the settings
change during the run. When a run fails for a server reason (the link dropped, docker
failed), the verdict is dropped and everything is checked again before the next submission,
so an outage costs one submission at most, not the whole queue.

With EVAL_GPU_PICK=free a run gets ONE GPU of EVAL_GPUS: one that is nearly empty right before
the run (free_gpus) and that no other running submission holds. The worker hands it out
(app.worker.claim), so several worker slots can share a machine whose GPUs others use too.

    python -m app.evaluators.remote     # run the checks by hand and print the result
"""
import ipaddress
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from . import docker as local
from .base import Shared, failure

SSH_PORT = os.getenv("EVAL_SSH_PORT", "22")
# Only the private key's FILE is configured, never its content.
SSH_KEY = os.getenv("EVAL_SSH_KEY", "/run/secrets/eval_ssh_key")
# The GPU machine's host key, checked on every connection: an unknown or changed key is refused.
SSH_KNOWN_HOSTS = os.getenv("EVAL_SSH_KNOWN_HOSTS", "/run/secrets/eval_known_hosts")
# Optional allow-list of networks (comma separated CIDR). When set, only an IP address inside
# one of them may be used, so a changed setting cannot send submissions anywhere else.
SSH_ALLOWED = os.getenv("EVAL_SSH_ALLOWED", "")
UPLOAD_TIMEOUT_SECONDS = int(os.getenv("EVAL_UPLOAD_TIMEOUT_SECONDS", "900"))
MIN_FREE_GB = float(os.getenv("EVAL_MIN_FREE_GB", "10"))
CONNECT_SECONDS = 15
# The worker reports nothing while it checks, and the admin page calls it dead after
# WORKER_STALE_SECONDS (120): the three steps of a check stay well inside that together.
CHECK_SECONDS = 30
GPU_CONTAINER_SECONDS = 60
# A machine that passed keeps its verdict this long; a failed one is looked at again sooner.
OK_CACHE_SECONDS, FAILED_CACHE_SECONDS = 60, 15
# Starting a GPU container is the slow check: a machine that passed it is spared it this long.
GPU_CONTAINER_CACHE_SECONDS = 600
# Output size is polled over SSH, so less often than docker.py does on its own disk. Docker
# there only: the sandbox launcher watches it on the machine itself.
OUTPUT_CHECK_SECONDS = 3
FETCH_SECONDS = 60
# Leftovers of dead workers are looked for at most this often.
PRUNE_SECONDS = 600
# EVAL_GPU_PICK=free: a GPU is free while its memory in use and its utilization stay under
# these over a few seconds. On a shared machine, that is what another user's job shows as.
GPU_FREE_MEMORY_MIB = int(os.getenv("EVAL_GPU_FREE_MEMORY_MIB", "2048"))
GPU_FREE_UTILIZATION = int(os.getenv("EVAL_GPU_FREE_UTILIZATION", "10"))
# While no GPU is free, the machine is asked again at most this often.
GPU_RECHECK_SECONDS = 15

HOST = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
USER = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")

TOOLKIT_GUIDE = "https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html"
DOCKER_GUIDE = "https://docs.docker.com/engine/install/"
SETTINGS_FIX = "`.env`의 EVAL_SSH_* 값을 고친 뒤 worker를 다시 시작하세요."


class TargetInvalid(ValueError):
    """The SSH settings cannot be used. The message says what is wrong."""


@dataclass(frozen=True)
class Target:
    host: str
    port: int
    user: str
    key: str
    known_hosts: str

    @property
    def label(self):
        return f"{self.user}@{self.host}:{self.port}"


def load_target(env=os.environ):
    """The GPU machine to use. Everything that reaches the ssh command line is checked here:
    a value like `-oProxyCommand=...` must never be taken for an option."""
    host, user = env.get("EVAL_SSH_HOST", "").strip(), env.get("EVAL_SSH_USER", "").strip()
    if not host or not user:
        raise TargetInvalid("EVAL_SSH_HOST and EVAL_SSH_USER are not set")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
        if not HOST.match(host):
            raise TargetInvalid(f"EVAL_SSH_HOST is not a host name or IP address: {host!r}")
    if not USER.match(user):
        raise TargetInvalid(f"EVAL_SSH_USER is not a plain user name: {user!r}")
    try:
        port = int(env.get("EVAL_SSH_PORT", SSH_PORT))
        if not 0 < port < 65536:
            raise ValueError
    except ValueError:
        raise TargetInvalid(f"EVAL_SSH_PORT must be 1-65535, not {env.get('EVAL_SSH_PORT')!r}")
    allowed = env.get("EVAL_SSH_ALLOWED", SSH_ALLOWED).strip()
    if allowed:
        try:
            networks = [ipaddress.ip_network(item.strip()) for item in allowed.split(",") if item.strip()]
        except ValueError as error:
            raise TargetInvalid(f"EVAL_SSH_ALLOWED is not a list of CIDR networks: {error}")
        if address is None or not any(address in network for network in networks):
            raise TargetInvalid(f"{host} is outside EVAL_SSH_ALLOWED ({allowed}); use an IP address inside it")
    return Target(host, port, user, env.get("EVAL_SSH_KEY", SSH_KEY), env.get("EVAL_SSH_KNOWN_HOSTS", SSH_KNOWN_HOSTS))


def ssh_command(target, remote_command, stdin=False):
    """The ssh command line. The remote command is one string for the remote shell, and the
    host comes after `--`. No agent, no forwarding, no password prompt, no user config.
    Each call is its own connection: nothing shared can go stale between them."""
    return [
        "ssh", "-F", "/dev/null", "-T", *([] if stdin else ["-n"]),
        "-p", str(target.port), "-l", target.user, "-i", target.key,
        "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "PasswordAuthentication=no",
        "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={target.known_hosts}",
        "-o", "GlobalKnownHostsFile=/dev/null",
        "-o", f"ConnectTimeout={CONNECT_SECONDS}", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4",
        "-o", "ForwardAgent=no", "-o", "ForwardX11=no", "-o", "ClearAllForwardings=yes", "-o", "LogLevel=ERROR",
        "--", target.host, remote_command,
    ]


def remote_shell(command, guard=False):
    """A command (argument list, or a script) as one string run by `sh -c` on the GPU machine,
    whatever the account's login shell is. `guard` turns the exit status 255 into 1: ssh
    exits with 255 when the connection fails, and a submission that exits with 255 must not
    look like that."""
    text = shlex.join(command) if isinstance(command, (list, tuple)) else command
    if guard:
        text += '; c=$?; if [ "$c" -eq 255 ]; then exit 1; fi; exit "$c"'
    return f"sh -c {shlex.quote(text)}"


# --- the checks ------------------------------------------------------------------------

# Prints `key=value` lines and always exits 0. Only reads.
SYSTEM_SCRIPT = r"""
echo "os=$(uname -s 2>/dev/null)"
if command -v nvidia-smi >/dev/null 2>&1; then
  if out=$(nvidia-smi --query-gpu=index,name,driver_version,memory.total --format=csv,noheader 2>&1); then
    echo "$out" | sed 's/^/gpu=/'
  else
    echo "nvidia_error=$(echo "$out" | head -n 1)"
  fi
else
  echo "nvidia=missing"
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "docker=missing"
elif out=$(docker version --format '{{.Server.Version}}' 2>&1); then
  echo "docker=$out"
else
  case "$out" in
    *[Pp]ermission*denied*) echo "docker=denied" ;;
    *"Cannot connect"*|*"daemon running"*) echo "docker=down" ;;
    *) echo "docker=error:$(echo "$out" | head -n 1)" ;;
  esac
fi
if command -v nvidia-ctk >/dev/null 2>&1 || command -v nvidia-container-cli >/dev/null 2>&1; then
  echo "toolkit=ok"
else
  echo "toolkit=missing"
fi
"""

PROJECT_SCRIPT = r"""
if out=$(docker image inspect --format '{{index .Config.Labels "admin-eval.installer"}}' "$IMG" 2>/dev/null); then
  echo "image=$out"
else
  echo "image=missing"
fi
for f in test.csv test_features.csv test_structures.zip; do
  [ -s "$IN/$f" ] || echo "input_missing=$f"
done
if mkdir -p "$WORK" 2>/dev/null && [ -w "$WORK" ]; then echo "work=ok"; else echo "work=unwritable"; fi
df -Pk "$WORK" 2>/dev/null | awk 'NR==2 {print "free_kb=" $4}'
"""

# EVAL_GPU_PICK=free: prints `gpu=index, memory in use (MiB), utilization (%)` for every GPU,
# three rounds a second apart because utilization is a snapshot. Only reads.
LOAD_SCRIPT = r"""
for round in 1 2 3; do
  [ "$round" = 1 ] || sleep 1
  if ! out=$(nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader,nounits 2>&1); then
    echo "nvidia_error=$(echo "$out" | head -n 1)"
    exit 0
  fi
  echo "$out" | sed 's/^/gpu=/'
done
"""


@dataclass
class Check:
    name: str
    ok: bool
    reason: str = ""
    fix: str = ""


def _run(target, remote_command, timeout):
    """(exit code, stdout, stderr). Raises OSError or TimeoutExpired when ssh cannot even run."""
    done = subprocess.run(ssh_command(target, remote_command), capture_output=True, timeout=timeout)
    return done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")


def _pairs(text):
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            yield key.strip(), value.strip()


def _first_line(text):
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def _connection_failure(target, detail):
    lowered = detail.lower()
    if "host key verification failed" in lowered or "no matching host key" in lowered or "remote host identification has changed" in lowered:
        fix = (f"서버의 호스트 키가 {target.known_hosts}에 없거나 달라졌습니다. 서버 주인에게 지문을 확인한 뒤 "
               f"`ssh-keyscan -p {target.port} {target.host}` 결과를 그 파일에 넣으세요. 키가 바뀐 것이라면 바꾼 이유를 먼저 확인하세요.")
    elif "permission denied" in lowered:
        fix = "서버 계정의 ~/.ssh/authorized_keys에 채점기의 공개키가 등록돼 있는지 확인하세요(비밀번호 로그인은 쓰지 않습니다)."
    elif "filenotfounderror" in lowered and "ssh" in lowered:
        fix = "worker 이미지에 ssh 클라이언트가 없습니다. apps/api/Dockerfile의 worker 이미지를 다시 빌드하세요."
    else:
        fix = "주소와 포트, 서버가 켜져 있는지, 방화벽·Tailscale 연결을 확인하세요."
    return Check("ssh", False, f"SSH로 {target.label}에 접속하지 못했습니다: {detail or '응답 없음'}", fix)


def settings_checks(target, env=os.environ, gpu_required=True):
    """What can be judged here, without connecting. Reported before any SSH attempt."""
    checks = []
    problem = local.gpu_problem(required=gpu_required, pick=True)
    if problem:
        checks.append(Check("gpu_selection", False, problem, SETTINGS_FIX))
    if not local.INPUT_HOST_DIR:
        checks.append(Check("input", False, "EVAL_INPUT_HOST_DIR(GPU 서버 안의 평가 입력 폴더)가 설정되지 않았습니다.",
                            "`.env`의 EVAL_REMOTE_INPUT_DIR를 설정하세요."))
    if not env.get("EVAL_WORK_HOST_DIR"):
        checks.append(Check("work_dir", False, "EVAL_WORK_HOST_DIR(GPU 서버 안의 작업 폴더)가 설정되지 않았습니다.",
                            "`.env`의 EVAL_REMOTE_WORK_DIR를 설정하세요."))
    for name, label, path in (("ssh_key", "SSH 개인키 파일", target.key), ("known_hosts", "known_hosts 파일", target.known_hosts)):
        if not Path(path).is_file():
            checks.append(Check(name, False, f"{label}({path})이 worker 안에 없습니다.",
                                "`.env`의 EVAL_SSH_KEY_FILE·EVAL_SSH_KNOWN_HOSTS_FILE 경로와 docker-compose.remote.yml 연결을 확인하세요."))
    return checks


def system_values(text):
    """The `key=value` lines of a check script, and its `gpu=` rows (index, name, driver, memory)."""
    values, gpus = {}, []
    for key, value in _pairs(text):
        if key == "gpu":
            row = [part.strip() for part in value.split(",")]
            if len(row) >= 4:
                gpus.append(row)
        else:
            values.setdefault(key, value)
    return values, gpus


def os_check(values):
    system = values.get("os", "")
    if system == "Linux":
        return Check("os", True)
    return Check("os", False, f"Linux 서버가 아닙니다({system or '알 수 없음'}).",
                 "Windows PC는 WSL2 안의 Ubuntu에 SSH를 열어 그쪽 주소로 접속해야 합니다.")


def gpu_checks(values, gpus):
    """The NVIDIA driver works and every GPU in EVAL_GPUS exists."""
    checks = []
    if gpus:
        checks.append(Check("nvidia_driver", True))
        wanted = local.GPUS
        have = [row[0] for row in gpus]
        missing = [] if wanted == "all" else [index for index in wanted.split(",") if index not in have]
        if missing:
            checks.append(Check("gpu_selection", False, f"EVAL_GPUS={wanted}인데 서버에 없는 GPU 번호가 있습니다({', '.join(missing)}). "
                                f"서버의 GPU 번호: {', '.join(have)}.", "EVAL_GPUS를 서버의 GPU 번호에 맞게 고치세요."))
        else:
            checks.append(Check("gpu_selection", True))
    elif "nvidia_error" in values:
        checks.append(Check("nvidia_driver", False, f"NVIDIA 드라이버가 동작하지 않습니다: {values['nvidia_error']}",
                            "드라이버와 커널 모듈이 맞는지 확인하고 서버를 재부팅하세요(서버 주인이 직접)."))
    else:
        checks.append(Check("nvidia_driver", False, "NVIDIA 드라이버(nvidia-smi)가 설치돼 있지 않습니다.",
                            "Ubuntu 서버: `sudo ubuntu-drivers install` 후 재부팅. WSL2: WSL 안이 아니라 Windows에 NVIDIA 드라이버를 설치합니다."))
    return checks


def _system_checks(target, text):
    values, gpus = system_values(text)
    checks = [os_check(values), *gpu_checks(values, gpus)]

    state = values.get("docker", "missing")
    if state[:1].isdigit():
        checks.append(Check("docker", True))
    elif state == "denied":
        checks.append(Check("docker", False, f"{target.user} 계정이 Docker를 쓸 권한이 없습니다(docker 그룹이 아님).",
                            f"서버 주인이 `sudo usermod -aG docker {target.user}` 후 다시 로그인하게 하세요. docker 그룹은 root와 같은 권한이므로 채점 전용 계정에만 주세요."))
    elif state == "down":
        checks.append(Check("docker", False, "Docker 데몬이 꺼져 있습니다.", "서버 주인이 `sudo systemctl start docker`로 켜게 하세요."))
    elif state.startswith("error:"):
        checks.append(Check("docker", False, f"Docker가 오류를 냈습니다: {state[6:]}", "서버에서 `docker version`을 직접 실행해 원인을 확인하세요."))
    else:
        checks.append(Check("docker", False, "Docker가 설치돼 있지 않습니다.",
                            f"서버 주인이 Docker Engine을 설치해야 합니다({DOCKER_GUIDE}). Docker Desktop이 아니라 Engine이어야 합니다."))

    if values.get("toolkit") == "ok":
        checks.append(Check("nvidia_toolkit", True))
    else:
        checks.append(Check("nvidia_toolkit", False, "NVIDIA Container Toolkit이 설치돼 있지 않아 컨테이너가 GPU를 쓸 수 없습니다.",
                            f"서버 주인이 설치({TOOLKIT_GUIDE})한 뒤 `sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker`를 실행해야 합니다."))
    return checks, gpus


def _work_dir():
    return str(local.WORK_HOST_DIR).replace("\\", "/")


def _project_script(image, input_dir, work_dir):
    return f"IMG={shlex.quote(image)}\nIN={shlex.quote(input_dir)}\nWORK={shlex.quote(work_dir)}\n{PROJECT_SCRIPT}"


def project_values(text):
    """The `key=value` lines of a check script, and the evaluation input files it found missing."""
    values, missing = {}, []
    for key, value in _pairs(text):
        if key == "input_missing":
            missing.append(value)
        else:
            values.setdefault(key, value)
    return values, missing


def _project_checks(text, image, input_dir, work_dir):
    values, missing = project_values(text)
    checks = []
    label = values.get("image")
    if label == "missing":
        checks.append(Check("image", False, f"평가 이미지 {image}가 서버에 없습니다.",
                            f"서버에서 `docker pull {image}`(ghcr 로그인 필요) 또는 apps/evaluator에서 빌드해 두세요."))
    elif label != local.INSTALLER_VERSION:
        checks.append(Check("image", False, f"평가 이미지 {image}가 낡았습니다(패키지 설치기 {label!r}, 필요 {local.INSTALLER_VERSION!r}).",
                            "이미지를 새로 받거나 apps/evaluator에서 다시 빌드하세요."))
    else:
        checks.append(Check("image", True))
    return checks + place_checks(values, missing, input_dir, work_dir)


def place_checks(values, missing, input_dir, work_dir):
    """The evaluation input is complete, and the work directory is writable with room to spare."""
    checks = []
    if missing:
        checks.append(Check("input", False, f"평가 입력 파일이 없습니다: {', '.join(missing)} (폴더 {input_dir}).",
                            "정답이 없는 평가 입력 3개 파일(test.csv, test_features.csv, test_structures.zip)을 그 폴더에 복사하세요."))
    else:
        checks.append(Check("input", True))
    if values.get("work") != "ok":
        checks.append(Check("work_dir", False, f"작업 폴더 {work_dir}를 만들거나 쓸 수 없습니다.", f"{work_dir}를 만들고 접속 계정이 쓸 수 있게 하세요."))
        return checks
    checks.append(Check("work_dir", True))
    try:
        free_gb = int(values.get("free_kb", "")) / 1024 / 1024
    except ValueError:
        return checks
    if free_gb < MIN_FREE_GB:
        checks.append(Check("disk", False, f"작업 폴더의 디스크 여유가 {free_gb:.1f} GB뿐입니다(최소 {MIN_FREE_GB:g} GB).", "서버의 디스크를 정리하거나 다른 위치를 쓰세요."))
    else:
        checks.append(Check("disk", True))
    return checks


def preflight(target, gpu_container=True):
    """Looks at the GPU machine without changing it. Returns (checks, gpus) where each failed
    check says what is wrong and how to fix it. `gpu_container` also starts a short-lived
    container to prove that Docker really gives it the GPU; it runs only when everything it
    depends on passed, so it never repeats a failure already reported."""
    try:
        code, out, err = _run(target, remote_shell(SYSTEM_SCRIPT), CHECK_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as error:
        return [_connection_failure(target, f"{type(error).__name__}: {error}")], []
    if code != 0:
        return [_connection_failure(target, _first_line(err) or f"종료 코드 {code}")], []
    checks, gpus = _system_checks(target, out)
    passed = {check.name for check in checks if check.ok}
    if "docker" not in passed:
        return checks, gpus

    work_dir = _work_dir()
    try:
        code, out, err = _run(target, remote_shell(_project_script(local.IMAGE, local.INPUT_HOST_DIR, work_dir)), CHECK_SECONDS)
        detail = _first_line(err) if code != 0 else ""
    except (OSError, subprocess.TimeoutExpired) as error:
        code, detail = -1, str(error)
    if code != 0:
        return checks + [Check("project", False, f"서버 상태를 읽지 못했습니다: {detail}", "잠시 뒤 다시 확인하세요. 계속되면 서버에서 직접 확인하세요.")], gpus
    checks += _project_checks(out, local.IMAGE, local.INPUT_HOST_DIR, work_dir)
    passed = {check.name for check in checks if check.ok}

    if gpu_container and {"nvidia_driver", "gpu_selection", "nvidia_toolkit", "image"} <= passed:
        command = ["docker", "run", "--rm", "--network", "none", *local.gpu_args(), local.IMAGE, "nvidia-smi", "-L"]
        try:
            code, out, err = _run(target, remote_shell(command), GPU_CONTAINER_SECONDS)
        except (OSError, subprocess.TimeoutExpired) as error:
            code, out, err = -1, "", f"{type(error).__name__}: {error}"
        if code == 0 and "GPU" in out:
            checks.append(Check("gpu_container", True))
        else:
            checks.append(Check("gpu_container", False, f"컨테이너 안에서 GPU를 쓸 수 없습니다: {_first_line(err) or _first_line(out) or f'종료 코드 {code}'}",
                                "`sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker`를 서버 주인이 실행했는지, "
                                "드라이버가 컨테이너의 CUDA를 지원하는지 확인하세요."))
    return checks, gpus


def examine(target, gpu_container=True):
    """Every check, in order: settings here first (no connection is made while one fails),
    then the machine itself. Returns (checks, gpus)."""
    problems = settings_checks(target)
    if problems:
        return problems, []
    return preflight(target, gpu_container)


def settings_failure(error):
    return Check("settings", False, f"SSH 설정 오류: {error}", SETTINGS_FIX)


def chosen_gpus(gpus):
    """The rows of the GPUs EVAL_GPUS names."""
    return [row for row in gpus if local.GPUS == "all" or row[0] in local.GPUS.split(",")]


def gpu_summary(gpus):
    """The GPUs runs may use, as the admin page shows them."""
    names = ", ".join(f"GPU {row[0]} {row[1]} (드라이버 {row[2]})" for row in chosen_gpus(gpus))
    return f"{names} 중 채점마다 빈 GPU 1장" if local.GPU_PICK == "free" else names


def gpu_load(text):
    """{index: (most memory in use in MiB, highest utilization in %)} over the rounds of
    LOAD_SCRIPT, for the GPUs EVAL_GPUS names. A value nvidia-smi cannot read ([N/A]) is busy."""
    load = {}
    for key, value in _pairs(text):
        row = [part.strip() for part in value.split(",")]
        if key != "gpu" or len(row) < 3 or not (local.GPUS == "all" or row[0] in local.GPUS.split(",")):
            continue
        try:
            sample = (float(row[1]), float(row[2]))
        except ValueError:
            sample = (float("inf"), float("inf"))
        memory, utilization = load.get(row[0], (0.0, 0.0))
        load[row[0]] = (max(memory, sample[0]), max(utilization, sample[1]))
    return load


def emptiest_first(load, indexes=None):
    """The GPUs of `load` (or only `indexes`), by memory in use, then utilization."""
    return sorted(load if indexes is None else indexes, key=lambda index: (*load[index], len(index), index))


def usable_gpus(load, held=()):
    """The GPUs under both limits that no run of ours holds, emptiest first."""
    free = [index for index, (memory, utilization) in load.items()
            if index not in held and memory < GPU_FREE_MEMORY_MIB and utilization < GPU_FREE_UTILIZATION]
    return emptiest_first(load, free)


def busy_note(load, held=(), problem=None):
    """Why the queue waits for a GPU, for the admin page."""
    if problem:
        return f"GPU 사용량을 읽지 못해 채점을 기다립니다: {problem}"
    states = []
    for index in sorted(load, key=lambda index: (len(index), index)):
        memory, utilization = load[index]
        if index in held:
            states.append(f"GPU {index} 다른 슬롯이 채점 중")
        elif memory == float("inf"):
            states.append(f"GPU {index} 사용량 알 수 없음")
        else:
            states.append(f"GPU {index} {memory:.0f} MiB·{utilization:.0f}%")
    return (f"비어 있는 GPU가 없어 채점을 기다립니다(기준 {GPU_FREE_MEMORY_MIB} MiB·{GPU_FREE_UTILIZATION}% 미만, "
            f"{GPU_RECHECK_SECONDS}초마다 다시 확인): {', '.join(states) or 'EVAL_GPUS의 GPU가 서버에 없음'}")


def describe(target, checks):
    failed = [check for check in checks if not check.ok]
    where = f"원격 채점 서버 {target.label}" if target else "원격 채점 서버"
    if not failed:
        return where
    lines = [f"{where} 연결을 취소했습니다. 사유:"]
    for number, check in enumerate(failed, 1):
        lines.append(f"{number}) {check.reason} → {check.fix}" if check.fix else f"{number}) {check.reason}")
    return "\n".join(lines)


# --- the evaluator -----------------------------------------------------------------------

class RemoteEvaluator(local.DockerEvaluator):
    name = "remote"
    FAULT_CODES = (255,)

    def __init__(self):
        self.shared = Shared()           # checks and GPU readings; app.worker's slots share one
        self._verified = None            # the target that last passed every check
        self._active = None              # the target the running submission is bound to
        self._containers = []            # container names started by the running submission
        self._gpu = None                 # EVAL_GPU_PICK=free: the GPU the running submission was handed
        self._pruned_at = float("-inf")
        self._size = (0.0, 0)

    @property
    def picks_gpus(self):
        return local.GPU_PICK == "free"

    # -- readiness --

    def _forget(self):
        self._verified = None
        self.shared.forget()

    def _check_key(self, target):
        """What a check result is for: another key is checked anew."""
        return target

    def _examine(self, target, prove):
        """(checks, facts): `facts` is what _summary needs once every check passed."""
        return examine(target, gpu_container=prove)

    def _summary(self, target, gpus):
        return f"remote evaluator: {target.label}, {gpu_summary(gpus)}, image {local.IMAGE}, {local.CPUS} cpus, {local.MEMORY} memory"

    def _describe(self, target, checks):
        """The not-ready message the admin page shows."""
        return describe(target, checks)

    def ready(self):
        try:
            target = load_target()
        except TargetInvalid as error:
            self._forget()
            return False, describe(None, [settings_failure(error)])
        checks, facts = self._checked(target)
        if all(check.ok for check in checks):
            self._verified = target
            return True, self._summary(target, facts)
        self._verified = None
        return False, self._describe(target, checks)

    def _checked(self, target):
        """(checks, facts) of the last check, made again once it is too old. One slot checks at
        a time, and the others take its result instead of asking the machine themselves."""
        key, shared = self._check_key(target), self.shared
        with shared.checking:
            until, checks, facts = shared.verdicts.get(key, (0.0, None, None))
            if time.monotonic() < until:
                return checks, facts
            prove = time.monotonic() >= shared.proved.get(key, 0.0)
            checks, facts = self._examine(target, prove)
            ok = all(check.ok for check in checks)
            if ok and prove:
                shared.proved[key] = time.monotonic() + GPU_CONTAINER_CACHE_SECONDS
            elif not ok:
                shared.proved.pop(key, None)
            shared.verdicts[key] = (time.monotonic() + (OK_CACHE_SECONDS if ok else FAILED_CACHE_SECONDS), checks, facts)
            return checks, facts

    def free_gpus(self, held=()):
        """EVAL_GPU_PICK=free: the GPUs of EVAL_GPUS that are nearly empty and not `held`,
        emptiest first, by a reading at most GPU_RECHECK_SECONDS old that every slot shares.
        While there is none, gpu_note says why."""
        load, problem = self._gpu_load()
        free = [] if problem else usable_gpus(load, held)
        self.gpu_note = None if free else busy_note(load, held, problem)
        return free

    def _gpu_load(self):
        """(load, problem): the machine's GPU load, read again once the last reading is
        GPU_RECHECK_SECONDS old. Our own runs need no fresher one: the worker leaves out the
        GPUs they hold, by the database."""
        target, shared = self._target(), self.shared
        with shared.reading:
            if shared.load and shared.load[0] == target and time.monotonic() - shared.load[1] < GPU_RECHECK_SECONDS:
                return shared.load[2:]
            try:
                code, out, err = _run(target, remote_shell(LOAD_SCRIPT), CHECK_SECONDS)
            except (OSError, subprocess.TimeoutExpired) as error:
                code, out, err = -1, "", f"{type(error).__name__}: {error}"
            problem = dict(_pairs(out)).get("nvidia_error") if code == 0 else (_first_line(err) or f"종료 코드 {code}")
            load = {} if problem else gpu_load(out)
            shared.load = (target, time.monotonic(), load, problem)
            return load, problem

    # -- one run --

    def run(self, submission, zip_path, tick):
        if self._verified is None:
            return failure("system_error", log="no GPU machine has passed its checks")
        gpu = getattr(submission, "gpu", None) if self.picks_gpus else None
        if self.picks_gpus and not gpu:
            return failure("system_error", log="EVAL_GPU_PICK=free, but the worker handed this run no GPU")
        # Bound for the whole run: kill, fetch and cleanup go where the containers are.
        self._active, self._containers, self._gpu = self._verified, [], gpu
        try:
            outcome = super().run(submission, zip_path, tick)
        finally:
            self._active = self._gpu = None
        if gpu:
            outcome.log = f"ran on GPU {gpu} (EVAL_GPU_PICK=free)\n{outcome.log or ''}"
        if outcome.failure_code == "system_error":
            # The machine or the link to it may be gone: check everything again first.
            self._forget()
        return outcome

    def _target(self):
        target = self._active or self._verified
        if target is None:
            raise OSError("no GPU machine has passed its checks")
        return target

    def _remote(self, script, timeout=60):
        return subprocess.run(ssh_command(self._target(), remote_shell(script)), capture_output=True, timeout=timeout)

    # -- hooks used by DockerEvaluator --

    def _wrap(self, command, guard=False):
        return ssh_command(self._target(), remote_shell(command, guard))

    def _gpus(self):
        return self._gpu or local.GPUS

    def _watch(self, name, command, limit, tick, output_dir=None):
        self._containers.append(name)
        return super()._watch(name, command, limit, tick, output_dir)

    def _prune(self):
        if time.monotonic() - self._pruned_at < PRUNE_SECONDS:
            return
        self._pruned_at = time.monotonic()
        super()._prune()  # work directories here, package volumes there
        cutoff_minutes = (2 * (local.INSTALL_TIMEOUT_SECONDS + local.INFERENCE_TIMEOUT_SECONDS) + 600) // 60
        try:
            self._remote(f"find {shlex.quote(_work_dir())} -maxdepth 1 -name 'submission-*' -mmin +{cutoff_minutes} "
                         f"-exec rm -rf {{}} +", 30)
        except (OSError, subprocess.TimeoutExpired):
            pass  # looked at again later

    def _stage(self, work, code_dir, output_dir, tick):
        target = self._target()
        remote_work, remote_code, remote_out = (shlex.quote(local._host_path(path)) for path in (work, code_dir, output_dir))
        script = (f"mkdir -p {remote_code} {remote_out} && chmod 777 {remote_out} && "
                  f"tar -C {remote_code} -xf - --no-same-owner && chmod -R a+rX {remote_work}")
        self._size = (time.monotonic(), 0)
        with tempfile.TemporaryFile() as errors:
            packer = subprocess.Popen(["tar", "-C", str(code_dir), "-cf", "-", "."], stdout=subprocess.PIPE, stderr=errors)
            try:
                sender = subprocess.Popen(ssh_command(target, remote_shell(script), stdin=True),
                                          stdin=packer.stdout, stdout=errors, stderr=errors)
            except OSError:
                packer.kill()
                packer.wait()
                raise
            packer.stdout.close()  # only ssh reads it now, so tar sees a broken pipe if ssh dies
            started, finished = time.monotonic(), True
            while sender.poll() is None:
                if time.monotonic() - started > UPLOAD_TIMEOUT_SECONDS:
                    finished = False
                    sender.kill()
                    break
                tick()
                time.sleep(0.5)
            for process in (sender, packer):
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            errors.seek(0)
            detail = errors.read().decode("utf-8", "replace")[-2000:]
        if not finished:
            return failure("system_error", log=f"upload to {target.label} did not finish in {UPLOAD_TIMEOUT_SECONDS} s\n{detail}")
        if sender.returncode != 0 or packer.returncode != 0:
            return failure("system_error", log=f"upload to {target.label} failed (ssh {sender.returncode}, tar {packer.returncode}): {detail}")
        return None

    def _unstage(self, work):
        """One connection: containers of this run that may outlive a dropped link (killing
        ssh does not stop `docker run`), then the copy of the submission."""
        names = " ".join(shlex.quote(name) for name in self._containers)
        script = (f"docker rm -f {names} >/dev/null 2>&1; " if names else "") + f"rm -rf {shlex.quote(local._host_path(work))}"
        try:
            self._remote(script)
        except (OSError, subprocess.TimeoutExpired):
            pass  # containers stop on their own timer; the directory is left for _prune

    def _output_size(self, output_dir):
        """Bytes in the output directory on the GPU machine, asked at most every few seconds.
        A failed question keeps the last answer: a flaky link must not kill a good run."""
        checked, size = self._size
        if time.monotonic() - checked < OUTPUT_CHECK_SECONDS:
            return size
        try:
            done = self._remote(f"du -sb {shlex.quote(local._host_path(output_dir))}", 30)
            size = int(done.stdout.split()[0]) if done.returncode == 0 else size
        except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
            pass
        self._size = (time.monotonic(), size)
        return size

    def _fetch_output(self, output_dir):
        path = shlex.quote(f"{local._host_path(output_dir)}/{local.OUTPUT_NAME}")
        # Never follow a link the container may have planted there; read at most one byte past the limit.
        script = f'f={path}; if [ -L "$f" ] || [ ! -f "$f" ]; then exit 3; fi; head -c {local.MAX_OUTPUT_BYTES + 1} "$f"'
        try:
            done = self._remote(script, FETCH_SECONDS)
        except subprocess.TimeoutExpired as error:
            raise OSError(f"fetching the output timed out: {error}")
        if done.returncode == 3:
            return "missing", None
        if done.returncode != 0:
            detail = done.stderr.decode("utf-8", "replace")[-500:]
            raise OSError(f"could not fetch the output (exit code {done.returncode}): {detail}")
        if len(done.stdout) > local.MAX_OUTPUT_BYTES:
            return "too_big", None
        return "ok", done.stdout


def main(examine=examine):
    try:
        target = load_target()
        checks, _ = examine(target)
    except TargetInvalid as error:
        target, checks = None, [settings_failure(error)]
    for check in checks:
        if check.ok:
            print(f"[OK] {check.name}")
        else:
            print(f"[취소 사유] {check.name}: {check.reason}\n        해결: {check.fix}")
    print(describe(target, checks))
    return 0 if all(check.ok for check in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
