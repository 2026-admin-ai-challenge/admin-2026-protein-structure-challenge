"""Runs participant inference on a GPU machine reached over SSH, without Docker there.

The split is remote.py's: the worker unpacks and checks the ZIP, copies it over SSH, and
scores the predictions file it fetches back; the hidden labels never leave this machine.
Only the isolation on the GPU machine differs. Each step runs in a bubblewrap sandbox
started by sandbox_launch.py instead of `docker run` (that file says what a sandbox
sees). It needs no root and no daemon there, only bwrap, unprivileged user namespaces and
a scoring environment made once by apps/evaluator/setup-server.sh:

    <EVAL_SANDBOX_ROOT>/env/        a virtualenv with the base packages (the image's role)
                        eval/       install_packages.py
                        wheels/     the competition lock's wheels, for offline installs
                        pip-cache/  downloads kept between online installs
                        VERSION     installer=, lock=, torch_index=

Memory, CPU and process limits need `systemd-run --user` with the memory and pids cgroup
controllers delegated (EVAL_SANDBOX_LIMITS=cgroup, the default). EVAL_SANDBOX_LIMITS=none
runs without them and keeps only the time and output limits. EVAL_GPUS may be empty here:
the sandbox then runs on the CPU.

The checks are remote.py's, with bwrap, user namespaces, the cgroup limits and the scoring
environment in place of Docker, the toolkit and the image. The slow one runs a short
program in a real sandbox, which must find no network, no ~/.ssh and the evaluation input
and, when EVAL_GPUS is set, compute on the GPU; it takes the place of the GPU container.

Organizers can turn isolation off on the admin page (Settings.eval_isolation), for a
machine that forbids user namespaces, such as a Docker container with its default security
profiles. Steps then run directly on the machine, without bwrap or cgroup limits: they can
reach the network. When the SSH account is root, a step runs as EVAL_SANDBOX_RUN_UID, a user
of its own that cannot change the scoring environment or another run, and every process of
that user is killed after each step. Workers sharing a GPU machine therefore each need their
own uid: the slots of WORKER_SLOTS get EVAL_SANDBOX_RUN_UID + slot - 1 (app.worker). The checks skip
bwrap, user namespaces and the cgroup limits, and the probe proves only the input and the GPU.
EVAL_SANDBOX_NETNS=1 gives back the network part: every step but the online install then runs
in a network namespace of its own (`unshare --user --net`, see sandbox_launch.py), for a
container that allows user namespaces but not the mounts bwrap needs, and the probe must find
no network again.

    python -m app.evaluators.sandbox     # run the checks by hand and print the result
    python -m app.evaluators.sandbox --no-isolation
"""
import json
import os
import re
import shlex
import subprocess
import sys
import uuid
from pathlib import Path

from . import docker as local
from . import remote
from .remote import Check

# Paths ON THE GPU MACHINE, like EVAL_WORK_HOST_DIR and EVAL_INPUT_HOST_DIR.
ROOT = os.getenv("EVAL_SANDBOX_ROOT", "").strip().rstrip("/")
LIMITS = os.getenv("EVAL_SANDBOX_LIMITS", "cgroup").strip().lower()
# Without isolation, when the SSH account is root: the uid steps run as. No account needs it.
RUN_UID = int(os.getenv("EVAL_SANDBOX_RUN_UID", "64000"))
# Without isolation: steps (but the online install) in a network namespace of their own.
NETNS = os.getenv("EVAL_SANDBOX_NETNS", "").strip().lower() in ("1", "true", "yes", "on")
LAUNCHER = Path(__file__).with_name("sandbox_launch.py").read_text(encoding="utf-8")
MARKER = "admin-eval-sandbox"
FAULT = 125
OUTPUT_OVER = 124  # sandbox_launch.py's: the step's /output passed spec["max_output"]
PROBE_SECONDS = 60
SETUP = "apps/evaluator/setup-server.sh"

# Starts the launcher with the scoring environment's Python. A missing one is the machine's fault.
START = 'p="$1"; shift; if [ ! -x "$p" ]; then echo "sandbox: $p is missing" >&2; exit 125; fi; exec "$p" -I -S -c "$@"'
# Kills the launchers named by these pid files, but only a process that is one: a pid left
# in a file after its launcher died may belong to something else by now.
STOP = (f'for f in "$@"; do [ -f "$f" ] || continue; p=$(cat "$f"); case "$p" in ""|*[!0-9]*) continue ;; esac; '
        f'if grep -aq {MARKER} "/proc/$p/cmdline" 2>/dev/null; then kill -KILL "$p"; fi; done; exit 0')

# Prints `key=value` lines and always exits 0. Only reads, except creating the work directory.
CHECK_SCRIPT = r"""
echo "os=$(uname -s 2>/dev/null)"
echo "uid=$(id -u)"
[ -f /.dockerenv ] && echo "container=docker"
if [ -n "$GPUS" ]; then
  if command -v nvidia-smi >/dev/null 2>&1; then
    if out=$(nvidia-smi --query-gpu=index,name,driver_version,memory.total --format=csv,noheader 2>&1); then
      echo "$out" | sed 's/^/gpu=/'
    else
      echo "nvidia_error=$(echo "$out" | head -n 1)"
    fi
  else
    echo "nvidia=missing"
  fi
fi
if command -v bwrap >/dev/null 2>&1; then
  echo "bwrap=$(bwrap --version 2>/dev/null | awk '{print $2}')"
  if out=$(bwrap --unshare-all --die-with-parent --ro-bind / / true 2>&1); then
    echo "userns=ok"
  else
    echo "userns_error=$(echo "$out" | head -n 1)"
  fi
else
  echo "bwrap=missing"
  # Without bwrap, still say whether user namespaces are allowed: installing it alone may not help.
  if command -v unshare >/dev/null 2>&1 && ! out=$(unshare -Ur true 2>&1); then
    echo "userns_error=$(echo "$out" | head -n 1)"
  fi
fi
if [ "$LIMITS" = cgroup ]; then
  if ! command -v systemd-run >/dev/null 2>&1; then
    echo "cgroup_error=systemd-run: command not found"
  elif out=$(systemd-run --user --scope --quiet -p MemoryMax=256M true 2>&1); then
    u=$(id -u)
    echo "cgroup=$(cat "/sys/fs/cgroup/user.slice/user-$u.slice/user@$u.service/cgroup.controllers" 2>/dev/null)"
  else
    echo "cgroup_error=$(echo "$out" | head -n 1)"
  fi
fi
if [ -f "$ROOT/VERSION" ]; then sed -n 's/^\([a-z_]*\)=/version_\1=/p' "$ROOT/VERSION"; else echo "version=missing"; fi
if [ -x "$ROOT/env/bin/python" ]; then
  echo "python=$("$ROOT/env/bin/python" -I -S -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>&1 | head -n 1)"
else
  echo "python=missing"
fi
[ -f "$ROOT/eval/install_packages.py" ] || echo "installer=missing"
[ -d "$ROOT/wheels" ] || echo "wheels=missing"
for f in test.csv test_features.csv test_structures.zip; do
  [ -s "$IN/$f" ] || echo "input_missing=$f"
done
if mkdir -p "$WORK" 2>/dev/null && [ -w "$WORK" ]; then echo "work=ok"; else echo "work=unwritable"; fi
df -Pk "$WORK" 2>/dev/null | awk 'NR==2 {print "free_kb=" $4}'
"""

# Runs in the probe sandbox. argv[1] is the evaluation input as a submission is given it (the
# launcher rewrites it without isolation), argv[2] the account's ~/.ssh, which must not be visible.
PROBE = r"""
import json, os, socket, sys
result = {"input": os.access(sys.argv[1], os.R_OK), "ssh_visible": os.path.exists(sys.argv[2]), "network": "blocked"}
# More than one address: a machine may refuse one of them and still let everything else out.
for address in (("1.1.1.1", 53), ("8.8.8.8", 443), ("9.9.9.9", 443)):
    try:
        socket.create_connection(address, timeout=3).close()
        result["network"] = "open"
        break
    except OSError:
        pass
try:
    import torch
    result["torch"] = torch.__version__
    result["cuda"] = torch.cuda.is_available()
    if result["cuda"]:
        result["gpus"] = torch.cuda.device_count()
        result["computed"] = float((torch.ones(4, device="cuda") * 2).sum().item()) == 8.0
except Exception as error:
    result["error"] = (type(error).__name__ + ": " + str(error))[:300]
print("probe=" + json.dumps(result))
"""
PROBE_COMMAND = ["python", "-I", "-c", PROBE, "/input/test_features.csv"]

USERNS_FIX = ("서버 주인이 비특권 user namespace를 허용해야 합니다. Ubuntu 23.10 이후는 bwrap용 AppArmor 프로필(`userns,`)을 두거나 "
              "`sysctl kernel.apparmor_restrict_unprivileged_userns=0`, 그 밖의 Linux는 `sysctl kernel.unprivileged_userns_clone=1`과 "
              "`user.max_user_namespaces`가 0보다 큰지 확인합니다. 컨테이너 안의 계정이면 그 컨테이너가 user namespace를 허용해야 합니다.")
# Docker's default seccomp and AppArmor profiles forbid user namespaces and mounts to everyone
# inside, and root there lacks CAP_SYS_ADMIN, so bwrap cannot work in such a container.
CONTAINER_USERNS_FIX = ("이 서버는 Docker 컨테이너이고, 컨테이너의 기본 보안 설정(seccomp, AppArmor docker-default)이 user namespace를 막습니다. "
                        "서버 관리자가 이 컨테이너를 `--security-opt seccomp=unconfined --security-opt apparmor=unconfined`"
                        "(또는 user namespace와 mount를 허용하는 프로필)로 다시 만들어야 합니다. 접속 계정은 root가 아닌 일반 계정이어야 합니다.")
CONTAINER_LIMITS_FIX = ("이 서버는 systemd가 없는 Docker 컨테이너라 제출마다 cgroup 제한을 걸 수 없습니다. `.env`에 EVAL_SANDBOX_LIMITS=none을 "
                        "설정하세요(시간·출력 크기 제한과 컨테이너 전체의 메모리 제한만 남습니다).")
LIMITS_FIX = ("서버 주인이 `sudo loginctl enable-linger {user}`로 사용자 systemd를 켜고, cgroup v2에서 user@.service에 "
              "`Delegate=memory pids cpu`가 있는지 확인하게 하세요. 제한 없이 돌리려면 `.env`에 EVAL_SANDBOX_LIMITS=none을 설정합니다"
              "(시간·출력 크기 제한만 남습니다).")
# The checks only isolation needs: an admin may turn it off instead of waiting for the server's owner.
ISOLATION_CHECKS = {"bwrap", "userns", "limits", "sandbox_network", "sandbox_files"}
ISOLATION_OFF = ("격리 없이 채점하려면 관리자 페이지의 '채점 격리'에서 격리를 끄세요. 그러면 {numbers}번은 점검하지 않습니다. "
                 "대신 제출 코드가 네트워크와 GPU 서버의 파일에 접근할 수 있습니다.")


def systemd_size(value):
    """Docker's memory size ("8g", "512m") as systemd writes it ("8G", "512M")."""
    match = re.fullmatch(r"(\d+)([bkmg]?)", value.strip().lower())
    if not match:
        raise ValueError(f"EVAL_MEMORY must look like 8g or 512m, not {value!r}")
    return match.group(1) + {"": "", "b": "", "k": "K", "m": "M", "g": "G"}[match.group(2)]


def limits():
    """The cgroup limits of every step, or None for EVAL_SANDBOX_LIMITS=none."""
    if LIMITS != "cgroup":
        return None
    try:
        cpus, tasks = float(local.CPUS), int(local.PIDS)
        if cpus <= 0 or tasks <= 0:
            raise ValueError
    except ValueError:
        raise ValueError(f"EVAL_CPUS and EVAL_PIDS must be positive numbers, not {local.CPUS!r} and {local.PIDS!r}")
    return {"memory": systemd_size(local.MEMORY), "cpu_percent": round(cpus * 100), "tasks": tasks}


def tasks():
    """EVAL_PIDS, the process limit of a step without isolation (as a user of its own)."""
    try:
        value = int(local.PIDS)
        if value > 0:
            return value
    except ValueError:
        pass
    raise ValueError(f"EVAL_PIDS must be a positive number, not {local.PIDS!r}")


def spec(mode, run, seconds, pidfile=None, isolation=True, run_uid=None, **extra):
    """What sandbox_launch.py needs for one step. Every path is on the GPU machine. `run_uid`:
    the worker slot's own user (app.worker), RUN_UID when none is given."""
    step = {"mode": mode, "root": ROOT, "run": run, "input": local.INPUT_HOST_DIR, "gpus": local.GPUS,
            "seconds": int(seconds), "pidfile": pidfile, "isolation": isolation}
    if isolation:
        step["limits"] = limits()
    else:
        step.update(limits=None, run_uid=RUN_UID if run_uid is None else run_uid, tasks=tasks(), netns=NETNS)
    return {**step, **extra}


def launch_command(step):
    """The command that runs one step on the GPU machine."""
    return ["sh", "-c", START, "sh", f"{step['root']}/env/bin/python", LAUNCHER, json.dumps(step)]


# --- the checks ------------------------------------------------------------------------

def settings_checks(target, isolation=True, env=os.environ):
    checks = remote.settings_checks(target, env, gpu_required=False)
    if not ROOT.startswith("/"):
        checks.append(Check("sandbox_root", False, "EVAL_SANDBOX_ROOT(GPU 서버 안의 채점 환경 폴더)가 절대 경로로 설정되지 않았습니다.",
                            f"`.env`의 EVAL_SANDBOX_ROOT를 {SETUP}에 준 --root 경로로 설정하세요."))
    if isolation and LIMITS not in ("cgroup", "none"):
        checks.append(Check("limits", False, f"EVAL_SANDBOX_LIMITS는 cgroup 또는 none이어야 합니다(지금 값: {LIMITS!r}).", remote.SETTINGS_FIX))
    else:
        try:
            limits() if isolation else tasks()
        except ValueError as error:
            checks.append(Check("limits", False, str(error), remote.SETTINGS_FIX))
    return checks


def _check_script():
    values = {"GPUS": local.GPUS, "LIMITS": LIMITS, "ROOT": ROOT, "IN": local.INPUT_HOST_DIR, "WORK": remote._work_dir()}
    return "".join(f"{key}={shlex.quote(value)}\n" for key, value in values.items()) + CHECK_SCRIPT


def _checks(target, values, gpus, missing, isolation=True):
    checks = [remote.os_check(values)]
    if local.GPUS:
        checks += remote.gpu_checks(values, gpus)
    if isolation:
        checks += _isolation_checks(target, values)
    return checks + _environment_checks(values) + remote.place_checks(values, missing, local.INPUT_HOST_DIR, remote._work_dir())


def _isolation_checks(target, values):
    """bwrap, user namespaces and, with EVAL_SANDBOX_LIMITS=cgroup, the user's cgroup controllers."""
    checks = []
    container = values.get("container") == "docker"
    missing_bwrap = values.get("bwrap", "missing") == "missing"
    if missing_bwrap:
        checks.append(Check("bwrap", False, "bubblewrap(bwrap)이 설치돼 있지 않습니다.",
                            "서버 주인이 `sudo apt install bubblewrap`(또는 배포판의 같은 패키지)으로 설치하게 하세요."))
    if "userns_error" in values:
        tool = "user namespace를 만들 수 없습니다(unshare -Ur)" if missing_bwrap else "샌드박스를 만들 수 없습니다"
        checks.append(Check("userns", False, f"{tool}: {values['userns_error']}", CONTAINER_USERNS_FIX if container else USERNS_FIX))
    elif not missing_bwrap:
        checks.append(Check("bwrap", True))

    if LIMITS == "cgroup":
        controllers = values.get("cgroup", "").split()
        if "cgroup_error" in values:
            no_systemd = container and "not found" in values["cgroup_error"]
            checks.append(Check("limits", False, f"메모리·CPU 제한을 걸 수 없습니다(systemd-run --user 실패): {values['cgroup_error']}",
                                CONTAINER_LIMITS_FIX if no_systemd else LIMITS_FIX.format(user=target.user)))
        elif not {"memory", "pids"} <= set(controllers):
            checks.append(Check("limits", False, f"사용자 cgroup에 memory·pids 컨트롤러가 없습니다(있는 것: {' '.join(controllers) or '없음'}).",
                                LIMITS_FIX.format(user=target.user)))
        else:
            checks.append(Check("limits", True))
    return checks


def _environment_checks(values):
    checks = []
    rebuild = f"GPU 서버에서 `sh {SETUP} --root {ROOT}`로 채점 환경을 만드세요."
    absent = [name for name, key in (("env/bin/python", "python"), ("eval/install_packages.py", "installer"), ("wheels/", "wheels"))
              if values.get(key) == "missing"]
    installer = values.get("version_installer")
    if values.get("version") == "missing":
        checks.append(Check("environment", False, f"채점 환경이 없습니다({ROOT}/VERSION이 없음).", rebuild))
    elif installer != local.INSTALLER_VERSION:
        checks.append(Check("environment", False, f"채점 환경이 낡았습니다(패키지 설치기 {installer!r}, 필요 {local.INSTALLER_VERSION!r}).",
                            f"채점 중이 아닐 때 env, eval, wheels를 지우고 {SETUP}를 다시 실행하세요."))
    elif absent:
        checks.append(Check("environment", False, f"채점 환경이 불완전합니다(없음: {', '.join(absent)}).", rebuild))
    elif not re.fullmatch(r"\d+\.\d+\.\d+", values.get("python", "")):
        checks.append(Check("environment", False, f"채점 환경의 Python이 실행되지 않습니다: {values.get('python')}", rebuild))
    else:
        checks.append(Check("environment", True))
    return checks


def probe_checks(code, out, err, isolation=True):
    """Judges the probe program's report: no network and no ~/.ssh (with isolation), the input,
    and the GPU when one is set."""
    report = next((line[len("probe="):] for line in out.splitlines() if line.startswith("probe=")), None)
    where = "샌드박스" if isolation else "채점 서버(격리 없음)"
    if code == FAULT:
        fix = (f"서버에서 bwrap 오류를 확인하세요. user namespace, AppArmor, systemd-run이 원인인 경우가 많습니다. {USERNS_FIX}" if isolation else
               f"오류 내용을 확인하세요. 접속 계정이 root면 채점 폴더와 평가 입력을 uid {RUN_UID}가 읽을 수 있어야 합니다({SETUP}가 그렇게 만듭니다).")
        if not isolation and NETNS:
            fix += (" EVAL_SANDBOX_NETNS=1이면 서버가 비특권 user namespace를 허용해야 합니다(`unshare --user --net true`로 확인). "
                    "허용하지 않는 서버라면 `.env`에서 EVAL_SANDBOX_NETNS를 지우세요. 그러면 제출 코드가 네트워크에 접근할 수 있습니다.")
        return [Check("sandbox", False, f"{where}에서 점검 프로그램을 시작하지 못했습니다: {remote._first_line(err) or '이유 없음'}", fix)]
    if code == 137:
        return [Check("sandbox", False, f"{where} 점검이 {PROBE_SECONDS}초 안에 끝나지 않았습니다.", "서버가 지나치게 바쁜지 확인하세요.")]
    try:
        result = json.loads(report) if code == 0 and report else None
    except ValueError:
        result = None
    if not isinstance(result, dict):
        detail = remote._first_line(err) or remote._first_line(out) or f"종료 코드 {code}"
        return [Check("sandbox", False, f"{where} 점검 프로그램이 실패했습니다: {detail}", "서버에서 `python -m app.evaluators.sandbox` 결과를 확인하세요.")]
    checks = []
    if isolation and result.get("network") != "blocked":
        checks.append(Check("sandbox_network", False, "샌드박스 안에서 네트워크가 열려 있습니다.", "bwrap이 0.4 이상인지, --unshare-net이 동작하는지 확인하세요."))
    elif not isolation and NETNS and result.get("network") != "blocked":
        checks.append(Check("sandbox_network", False, f"{where}에서 EVAL_SANDBOX_NETNS=1인데 네트워크가 열려 있습니다.",
                            "서버에서 `unshare --user --net`이 새 network namespace를 만드는지 확인하세요."))
    if isolation and result.get("ssh_visible"):
        checks.append(Check("sandbox_files", False, "샌드박스 안에서 접속 계정의 ~/.ssh가 보입니다.",
                            "채점 환경과 그 Python을 홈 폴더 자체가 아닌 하위 폴더(EVAL_SANDBOX_ROOT)에 두세요."))
    if not result.get("input"):
        checks.append(Check("sandbox_input", False, f"{where}에서 제출 코드가 평가 입력을 읽을 수 없습니다.",
                            f"평가 입력 폴더와 파일을 제출 코드를 실행하는 계정(접속 계정이 root면 uid {RUN_UID})이 읽을 수 있게 하세요."))
    if result.get("error") or (local.GPUS and not (result.get("cuda") and result.get("computed"))):
        problem = result.get("error") or f"torch {result.get('torch', '?')}에서 CUDA를 쓸 수 없음"
        checks.append(Check("sandbox_gpu" if local.GPUS else "sandbox_env", False, f"{where}에서 채점 환경을 쓸 수 없습니다: {problem}",
                            "채점 환경의 torch가 이 서버의 드라이버와 GPU를 지원하는 CUDA 빌드인지 확인하세요"
                            f"({SETUP} --torch-index). 오래된 GPU(P100 등)는 그 GPU를 지원하는 빌드가 필요합니다."))
    return checks or [Check("sandbox", True)]


def probe_gpus(target):
    """The GPUs the probe computes on. EVAL_GPU_PICK=free: the one of EVAL_GPUS with the least
    in use right now. With all of them visible CUDA would take GPU 0, and another user filling
    that one would cancel the connection while the rest stand empty."""
    if local.GPU_PICK != "free" or not local.GPUS:
        return local.GPUS
    try:
        code, out, _ = remote._run(target, remote.remote_shell(remote.LOAD_SCRIPT), remote.CHECK_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        code, out = -1, ""
    emptiest = remote.emptiest_first(remote.gpu_load(out)) if code == 0 else []
    return emptiest[0] if emptiest else local.GPUS


def _probe(target, isolation=True, run_uid=None):
    run = f"{remote._work_dir()}/submission-probe-{uuid.uuid4().hex[:8]}"
    step = spec("probe", run, PROBE_SECONDS, isolation=isolation, run_uid=run_uid, command=PROBE_COMMAND, gpus=probe_gpus(target))
    quoted = shlex.quote(run)
    script = (f"mkdir -p {quoted}/submission {quoted}/output && {shlex.join(launch_command(step))}; "
              f"c=$?; rm -rf {quoted}; exit $c")
    try:
        code, out, err = remote._run(target, remote.remote_shell(script), PROBE_SECONDS + 15)
    except (OSError, subprocess.TimeoutExpired) as error:
        code, out, err = -1, "", f"{type(error).__name__}: {error}"
    return probe_checks(code, out, err, isolation)


def describe(target, checks, isolation=True):
    """remote.describe, and with isolation on, which of the reasons turning it off would skip."""
    text = remote.describe(target, checks)
    failed = [check for check in checks if not check.ok]
    numbers = [str(number) for number, check in enumerate(failed, 1) if check.name in ISOLATION_CHECKS]
    if isolation and numbers:
        text += "\n" + ISOLATION_OFF.format(numbers=", ".join(numbers))
    return text


def examine(target, probe=True, isolation=True, run_uid=None):
    """Every check, in order: settings here (no connection while one fails), the machine,
    then, only when all of that passed and `probe` is set, a real step (as `run_uid`, see
    spec). Returns (checks, facts)."""
    problems = settings_checks(target, isolation)
    if problems:
        return problems, {}
    try:
        code, out, err = remote._run(target, remote.remote_shell(_check_script()), remote.CHECK_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as error:
        return [remote._connection_failure(target, f"{type(error).__name__}: {error}")], {}
    if code != 0:
        return [remote._connection_failure(target, remote._first_line(err) or f"종료 코드 {code}")], {}
    values, gpus = remote.system_values(out)
    _, missing = remote.project_values(out)
    checks = _checks(target, values, gpus, missing, isolation)
    facts = {"gpus": gpus, "python": values.get("python", "?"), "lock": values.get("version_lock", "?"),
             "root": values.get("uid") == "0"}
    if probe and all(check.ok for check in checks):
        checks += _probe(target, isolation, run_uid)
    return checks, facts


# --- the evaluator -----------------------------------------------------------------------

class SandboxEvaluator(remote.RemoteEvaluator):
    name = "sandbox"
    VOLUMES = False

    def __init__(self):
        super().__init__()
        self._run_dir = None  # the running submission's directory on the GPU machine
        self._isolation = True
        self.run_uid = RUN_UID  # without isolation as root; each worker slot sets its own

    def configure(self, settings):
        """Takes Settings.eval_isolation. Checks are kept for each way (_check_key), so after a
        change the next submission waits until the machine passed the checks of the new way."""
        isolation = True if settings is None else bool(settings.eval_isolation)
        if isolation != self._isolation:
            self._isolation, self._verified = isolation, None

    def _check_key(self, target):
        return target, self._isolation

    def _examine(self, target, prove):
        return examine(target, probe=prove, isolation=self._isolation, run_uid=self.run_uid)

    def _summary(self, target, facts):
        names = remote.gpu_summary(facts["gpus"]) if local.GPUS else ""
        if not self._isolation:
            runner = f"uid {self.run_uid}로 실행" if facts["root"] else "접속 계정으로 실행"
            access = "네트워크 차단(온라인 설치 제외), 파일 접근 제한 없음" if NETNS else "네트워크·파일 접근 제한 없음"
            bounds = f"격리 꺼짐({access}, {runner}, {local.PIDS} pids)"
        elif LIMITS == "cgroup":
            bounds = f"{local.CPUS} cpus, {local.MEMORY} memory, {local.PIDS} pids"
        else:
            bounds = "자원 제한 없음(EVAL_SANDBOX_LIMITS=none)"
        return (f"sandbox evaluator: {target.label}, {names or 'GPU 없음(CPU만)'}, "
                f"env {ROOT} (Python {facts['python']}, lock {facts['lock'][:12]}), {bounds}")

    def _describe(self, target, checks):
        return describe(target, checks, self._isolation)

    # -- the commands of one run (see DockerEvaluator) --

    def _pidfile(self, name):
        return f"{self._run_dir}/{name}.pid"

    def _install_command(self, name, volume, requirements, online, seconds):
        step = spec("install-online" if online else "install-offline", self._run_dir, int(seconds) + local.KILL_GRACE_SECONDS,
                    self._pidfile(name), self._isolation, self.run_uid, requirements=list(requirements))
        return launch_command(step)

    def _inference_command(self, name, code_dir, output_dir, volume):
        step = spec("infer", self._run_dir, local.INFERENCE_TIMEOUT_SECONDS + local.KILL_GRACE_SECONDS, self._pidfile(name),
                    self._isolation, self.run_uid, command=shlex.split(local.COMMAND), deps=volume is not None, gpus=self._gpus(),
                    max_output=local.MAX_OUTPUT_BYTES)
        return launch_command(step)

    def _watch(self, name, command, limit, tick, output_dir=None):
        """The launcher watches the output directory itself (spec max_output) and exits with
        OUTPUT_OVER, so its size is not asked over SSH every few seconds during a run."""
        code, log, stopped_for, elapsed = super()._watch(name, command, limit, tick)
        if code == OUTPUT_OVER and stopped_for is None:
            stopped_for = "output_invalid"
        return code, log, stopped_for, elapsed

    def _kill_command(self, name):
        return ["sh", "-c", STOP, "sh", self._pidfile(name)]

    def _drop_volume(self, volume):
        """The packages are in the run directory, which _unstage removes."""

    def _stage(self, work, code_dir, output_dir, tick):
        self._run_dir = local._host_path(work)
        return super()._stage(work, code_dir, output_dir, tick)

    def _unstage(self, work):
        """One connection: launchers of this run that may outlive a dropped link, then, without
        isolation as root, every process its own user left behind, then its directory."""
        run = shlex.quote(local._host_path(work))
        leftovers = "" if self._isolation else f'if [ "$(id -u)" = 0 ]; then pkill -KILL -U {self.run_uid} 2>/dev/null; fi; '
        try:
            self._remote(f"{shlex.join(['sh', '-c', STOP, 'sh'])} {run}/*.pid; {leftovers}rm -rf {run}")
        except (OSError, subprocess.TimeoutExpired):
            pass  # launchers stop on their own timer; the directory is left for _prune


def main():
    isolation = "--no-isolation" not in sys.argv[1:]
    return remote.main(lambda target: examine(target, isolation=isolation))


if __name__ == "__main__":
    sys.exit(main())
