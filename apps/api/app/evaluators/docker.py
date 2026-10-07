"""Runs participant inference in a locked-down container.

The container gets the unpacked submission and the hidden evaluation INPUT, both read
only, plus one writable output directory. It never receives labels, the Public/Private
split, database credentials or the Docker socket, and it has no network.

The image holds only base packages, plus wheels of the 89-package competition lock. When
the submission's requirements.txt names packages, an install container first puts them
into a fresh Docker volume: from those wheels without network, and only if something is
missing there, again with network so pip can download it from PyPI. The install
container sees neither the submission nor the evaluation input, and accepts only wheels,
so no participant-chosen code runs while it has network. Inference then runs, still
without network, with that volume read only at /deps and its environment first on PATH.
The volume is removed after the run.

PROVISIONAL contract (to be fixed with the data team, Q2):
    working directory /submission,
    command `python inference.py --input /input/test_features.csv --output /output/predictions.csv`
    /input also holds test.csv (id,sequence) and test_structures.zip, like the starter kit.
    output: UTF-8 CSV with header `id,label`, one row per evaluation ID.
"""
import collections
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from ..config import INFERENCE_TIMEOUT_SECONDS, REPO_ROOT
from ..errors import FAILURES
from ..zipcheck import ZipRejected, inspect, safe_extract
from .base import Evaluator, Outcome, failure

IMAGE = os.getenv("EVAL_IMAGE", "admin-evaluator:latest")
COMMAND = os.getenv("EVAL_COMMAND", "python inference.py --input /input/test_features.csv --output /output/predictions.csv")
CPUS = os.getenv("EVAL_CPUS", "4")
MEMORY = os.getenv("EVAL_MEMORY", "8g")
PIDS = os.getenv("EVAL_PIDS", "256")
TMPFS_SIZE = os.getenv("EVAL_TMPFS_SIZE", "1g")
# Installing a submission's packages, both passes together. Not counted in the inference limit.
INSTALL_TIMEOUT_SECONDS = int(os.getenv("EVAL_INSTALL_TIMEOUT_SECONDS", "600"))
# Docker volume keeping pip's downloads between online installs. Empty: no cache.
PIP_CACHE_VOLUME = os.getenv("EVAL_PIP_CACHE_VOLUME", "admin-eval-pip-cache")
# Where the worker unpacks submissions, and the same directory as the Docker HOST sees it.
# They differ when the worker itself runs in a container and talks to the host daemon.
WORK_DIR = Path(os.getenv("EVAL_WORK_DIR", str(REPO_ROOT / "var" / "eval-work")))
WORK_HOST_DIR = Path(os.getenv("EVAL_WORK_HOST_DIR", str(WORK_DIR)))
# Host path of the hidden evaluation input mounted read-only at /input.
INPUT_HOST_DIR = os.getenv("EVAL_INPUT_HOST_DIR", "")
MAX_OUTPUT_BYTES = int(os.getenv("EVAL_MAX_OUTPUT_BYTES", str(5 * 1024 * 1024)))
LOG_TAIL_BYTES = 16 * 1024
KILL_GRACE_SECONDS = 15
OUTPUT_NAME = "predictions.csv"
# Paths inside the evaluation image (apps/evaluator/Dockerfile). An image built before the
# installer existed would fail every install as the team's fault, so its label is checked.
INSTALLER = "/opt/eval/install_packages.py"
INSTALLER_LABEL = '{{index .Config.Labels "admin-eval.installer"}}'
INSTALLER_VERSION = "1"
DEPS, VENV, PIP_CACHE = "/deps", "/deps/venv", "/pip-cache"
BASE_PATH = "/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin"
# admin-eval-env-<unix time>-<submission>-<random>: the time lets abandoned volumes be found.
VOLUME_PREFIX = "admin-eval-env-"
VOLUME_TIME = re.compile(rf"^{VOLUME_PREFIX}(\d+)-")
# pip output meaning PyPI could not be reached: the server's fault, not the team's.
NETWORK_ERRORS = re.compile(r"NewConnectionError|Temporary failure in name resolution|Name or service not known"
                            r"|Max retries exceeded|ConnectTimeoutError|ReadTimeoutError|SSLError|ProxyError")
# pip's own error lines are shown to the team: the install container holds nothing secret.
PIP_ERROR_CHARS = 600


def _host_path(path: Path):
    return str(WORK_HOST_DIR / path.relative_to(WORK_DIR)).replace("\\", "/")


def _directory_size(path: Path):
    total = 0
    for entry in path.rglob("*"):
        try:
            if entry.is_file() and not entry.is_symlink():
                total += entry.stat().st_size
        except OSError:
            pass
    return total


def _isolated(name, network="none"):
    """`docker run` with the restrictions every container of a submission gets."""
    return [
        "docker", "run", "--rm", "--name", name,
        "--network", network,
        "--read-only",
        "--user", "65534:65534",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", PIDS,
        "--cpus", CPUS,
        "--memory", MEMORY, "--memory-swap", MEMORY,
        "--tmpfs", f"/tmp:rw,nosuid,nodev,size={TMPFS_SIZE}",
        "-e", "HOME=/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "PYTHONUNBUFFERED=1",
    ]


def build_command(name, code_dir: Path, output_dir: Path, volume=None):
    command = [
        *_isolated(name),
        "-v", f"{_host_path(code_dir)}:/submission:ro",
        "-v", f"{INPUT_HOST_DIR}:/input:ro",
        "-v", f"{_host_path(output_dir)}:/output:rw",
    ]
    if volume:
        # The submission's packages, read only. `python` resolves to their environment.
        command += ["-v", f"{volume}:{DEPS}:ro", "-e", f"PATH={VENV}/bin:{BASE_PATH}", "-e", f"VIRTUAL_ENV={VENV}"]
    return [
        *command,
        "-w", "/submission",
        IMAGE,
        # Second timer inside the container: it still stops if the worker dies mid-run.
        "timeout", "--signal=KILL", str(INFERENCE_TIMEOUT_SECONDS + KILL_GRACE_SECONDS),
        *shlex.split(COMMAND),
    ]


def install_command(name, volume, requirements, online=False, seconds=INSTALL_TIMEOUT_SECONDS):
    """`requirements` were re-written by app.packages, never raw text from the ZIP. Only the
    online pass gets network, and the shared pip cache with it."""
    command = [*_isolated(name, "bridge" if online else "none"), "-v", f"{volume}:{DEPS}:rw"]
    if online and PIP_CACHE_VOLUME:
        command += ["-v", f"{PIP_CACHE_VOLUME}:{PIP_CACHE}:rw", "-e", f"PIP_CACHE_DIR={PIP_CACHE}"]
    elif online:
        command += ["-e", "PIP_NO_CACHE_DIR=1"]
    return [
        *command,
        IMAGE,
        "timeout", "--signal=KILL", str(int(seconds) + KILL_GRACE_SECONDS),
        "python", INSTALLER, "online" if online else "offline", VENV, *requirements,
    ]


def _remove_volume(volume):
    try:
        subprocess.run(["docker", "volume", "rm", "-f", volume], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        pass  # left for prune_abandoned


def prune_abandoned():
    """Removes work directories and package volumes left behind by a worker that died
    mid-run. Only ones old enough that no live run can still own them are touched."""
    cutoff = time.time() - (2 * (INSTALL_TIMEOUT_SECONDS + INFERENCE_TIMEOUT_SECONDS) + 600)
    for directory in WORK_DIR.glob("submission-*"):
        try:
            if directory.stat().st_mtime < cutoff:
                shutil.rmtree(directory, ignore_errors=True)
        except OSError:
            pass
    try:
        listed = subprocess.run(["docker", "volume", "ls", "-q", "--filter", f"name={VOLUME_PREFIX}"],
                                capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return
    for volume in listed.stdout.decode("utf-8", "replace").split():
        created = VOLUME_TIME.match(volume)
        if created and int(created.group(1)) < cutoff:
            _remove_volume(volume)


class DockerEvaluator(Evaluator):
    name = "docker"

    def ready(self):
        if not INPUT_HOST_DIR:
            return False, "EVAL_INPUT_HOST_DIR is not set"
        try:
            probe = subprocess.run(["docker", "image", "inspect", "--format", INSTALLER_LABEL, IMAGE], capture_output=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired) as error:
            return False, f"docker is not reachable: {error}"
        if probe.returncode != 0:
            return False, f"evaluation image not found: {IMAGE}"
        if probe.stdout.decode("utf-8", "replace").strip() != INSTALLER_VERSION:
            return False, f"{IMAGE} has no package installer {INSTALLER_VERSION}: rebuild it from apps/evaluator"
        return True, f"docker evaluator: image {IMAGE}, {CPUS} cpus, {MEMORY} memory"

    def run(self, submission, zip_path, tick):
        work = WORK_DIR / f"submission-{submission.id}-{uuid.uuid4().hex[:8]}"
        code_dir, output_dir = work / "submission", work / "output"
        name, volume = f"admin-eval-{submission.id}-{work.name[-8:]}", None
        prune_abandoned()
        try:
            try:
                requirements = inspect(zip_path)["packages"]
                safe_extract(zip_path, code_dir)
            except ZipRejected as error:
                return failure("zip_invalid", str(error))
            output_dir.mkdir(parents=True)
            os.chmod(output_dir, 0o777)
            if requirements:
                volume = f"{VOLUME_PREFIX}{int(time.time())}-{submission.id}-{work.name[-8:]}"
                problem, source = self._install(f"{name}-install", volume, requirements, tick)
                if problem:
                    return problem
            outcome = self._execute(name, code_dir, output_dir, volume, tick)
            if requirements:
                outcome.log = f"installed from requirements.txt ({source}): {' '.join(requirements)}\n{outcome.log or ''}"
            return outcome
        except OSError as error:
            return failure("system_error", log=f"worker I/O error: {error}")
        finally:
            shutil.rmtree(work, ignore_errors=True)
            if volume:
                _remove_volume(volume)

    def _install(self, name, volume, requirements, tick):
        """(failure to report or None, where the packages came from). The image's wheels are
        tried first without network; PyPI only when something is missing there. A package
        that cannot be installed is the team's failure; an unreachable PyPI, a timeout or a
        docker error is the server's."""
        started, logs = time.monotonic(), []
        for online in (False, True):
            source = "PyPI" if online else "image wheels"
            seconds = INSTALL_TIMEOUT_SECONDS - (time.monotonic() - started)
            pass_name = f"{name}-{'online' if online else 'offline'}"
            try:
                code, log, stopped_for, _ = self._watch(
                    pass_name, install_command(pass_name, volume, requirements, online, seconds), seconds, tick)
            except OSError as error:
                return failure("system_error", log=f"could not start docker: {error}"), source
            logs.append(f"--- install from {source}: exit code {code} ---\n{log}")
            if code == 0:
                return None, source
            if stopped_for or code in (124, 125, 137) or (online and NETWORK_ERRORS.search(log)):
                # 124/137: the container's own timer or the OOM killer, 125: docker itself failed.
                reason = f"timed out after {INSTALL_TIMEOUT_SECONDS} s" if stopped_for else f"exit code {code}"
                return failure("system_error", log=f"package install failed ({reason})\n" + "\n".join(logs)), source
        errors = " ".join(line.strip() for line in log.splitlines() if line.startswith("ERROR:"))
        message = f"{FAILURES['install_failed']} {errors[:PIP_ERROR_CHARS]}".strip()
        return failure("install_failed", message, "\n".join(logs)), source

    def _watch(self, name, command, limit, tick, output_dir=None):
        """Runs a container while reporting liveness. Returns (exit code, log tail, why it was
        stopped or None, seconds elapsed). It is killed after `limit` seconds, or once
        `output_dir` grows past MAX_OUTPUT_BYTES."""
        tail = collections.deque()
        kept = 0

        def drain(stream):
            # Keep only the end of the output so a chatty container cannot fill the disk.
            nonlocal kept
            for chunk in iter(lambda: stream.read(4096), b""):
                tail.append(chunk)
                kept += len(chunk)
                while kept > LOG_TAIL_BYTES and len(tail) > 1:
                    kept -= len(tail.popleft())

        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        reader = threading.Thread(target=drain, args=(process.stdout,), daemon=True)
        reader.start()
        started = time.monotonic()
        stopped_for = None
        while process.poll() is None:
            if time.monotonic() - started > limit:
                stopped_for = "timeout"
            elif output_dir is not None and _directory_size(output_dir) > MAX_OUTPUT_BYTES:
                stopped_for = "output_invalid"
            if stopped_for:
                subprocess.run(["docker", "kill", name], capture_output=True, timeout=30)
                break
            tick()
            time.sleep(1)
        try:
            process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            process.kill()
        reader.join(timeout=5)
        log = b"".join(tail).decode("utf-8", "replace")[-LOG_TAIL_BYTES:]
        return process.returncode, log, stopped_for, time.monotonic() - started

    def _execute(self, name, code_dir, output_dir, volume, tick):
        try:
            code, log, stopped_for, elapsed = self._watch(
                name, build_command(name, code_dir, output_dir, volume), INFERENCE_TIMEOUT_SECONDS, tick, output_dir)
        except OSError as error:
            return failure("system_error", log=f"could not start docker: {error}")

        if stopped_for == "timeout" or (code == 137 and elapsed >= INFERENCE_TIMEOUT_SECONDS):
            return failure("timeout", log=log)
        if stopped_for == "output_invalid":
            return failure("output_invalid", "출력 파일이 허용 크기를 넘었습니다.", log)
        if code == 125:
            return failure("system_error", log=log)  # docker itself failed (image, daemon, mounts)
        if code == 137:
            return failure("out_of_memory", log=log)
        if code != 0:
            # Only the exit status reaches the team, never container output.
            return failure("runtime_error", f"{FAILURES['runtime_error']} (종료 코드 {code})", f"exit code {code}\n{log}")

        result = output_dir / OUTPUT_NAME
        # The container owns /output: never follow a link it may have planted there.
        if result.is_symlink() or not result.is_file():
            return failure("output_missing", log=log)
        if result.stat().st_size > MAX_OUTPUT_BYTES:
            return failure("output_invalid", "출력 파일이 허용 크기를 넘었습니다.", log)
        return Outcome(ok=True, predictions=result.read_bytes(), log=log)
