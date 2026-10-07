"""Runs participant inference in a locked-down container.

The container gets the unpacked submission and the hidden evaluation INPUT, both read
only, plus one writable output directory. It never receives labels, the Public/Private
split, database credentials or the Docker socket, and it has no network.

The image holds only base packages, plus wheels of the competition lock. When the
submission's requirements.txt names packages (checked against the lock at upload), an
install container first puts them into a fresh Docker volume, from those wheels and with
the same restrictions. Inference then runs with that volume read only at /deps and its
environment first on PATH. The volume is removed after the run.

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

from .. import packages
from ..config import INFERENCE_TIMEOUT_SECONDS, PACKAGE_LOCK, REPO_ROOT
from ..errors import FAILURES
from ..zipcheck import ZipRejected, inspect, safe_extract
from .base import Evaluator, Outcome, failure

IMAGE = os.getenv("EVAL_IMAGE", "admin-evaluator:latest")
COMMAND = os.getenv("EVAL_COMMAND", "python inference.py --input /input/test_features.csv --output /output/predictions.csv")
CPUS = os.getenv("EVAL_CPUS", "4")
MEMORY = os.getenv("EVAL_MEMORY", "8g")
PIDS = os.getenv("EVAL_PIDS", "256")
TMPFS_SIZE = os.getenv("EVAL_TMPFS_SIZE", "1g")
# Installing a submission's packages from local wheels. Not counted in the inference limit.
INSTALL_TIMEOUT_SECONDS = int(os.getenv("EVAL_INSTALL_TIMEOUT_SECONDS", "600"))
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
# Paths inside the evaluation image (apps/evaluator/Dockerfile).
IMAGE_LOCK = "/opt/eval/requirements-competition.lock.txt"
INSTALLER = "/opt/eval/install_packages.py"
DEPS, VENV = "/deps", "/deps/venv"
BASE_PATH = "/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin"
# admin-eval-env-<unix time>-<submission>-<random>: the time lets abandoned volumes be found.
VOLUME_PREFIX = "admin-eval-env-"
VOLUME_TIME = re.compile(rf"^{VOLUME_PREFIX}(\d+)-")
IMAGE_RECHECK_SECONDS = 30


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


def _isolated(name):
    """`docker run` with the restrictions every container of a submission gets."""
    return [
        "docker", "run", "--rm", "--name", name,
        "--network", "none",
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


def install_command(name, volume, pins):
    """`pins` are `name==version` from the lock (app.packages), never text from the ZIP."""
    return [
        *_isolated(name),
        "-v", f"{volume}:{DEPS}:rw",
        IMAGE,
        "timeout", "--signal=KILL", str(INSTALL_TIMEOUT_SECONDS + KILL_GRACE_SECONDS),
        "python", INSTALLER, VENV, *pins,
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

    def __init__(self):
        self._image_check = None  # (image ID, monotonic time, problem) of the last lock check

    def ready(self):
        if not INPUT_HOST_DIR:
            return False, "EVAL_INPUT_HOST_DIR is not set"
        try:
            probe = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", IMAGE], capture_output=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired) as error:
            return False, f"docker is not reachable: {error}"
        if probe.returncode != 0:
            return False, f"evaluation image not found: {IMAGE}"
        problem = self._lock_problem(probe.stdout.decode().strip())
        if problem:
            return False, problem
        return True, f"docker evaluator: image {IMAGE}, {CPUS} cpus, {MEMORY} memory"

    def _lock_problem(self, image_id):
        """Uploads are checked against PACKAGE_LOCK, so the image must hold wheels of the same
        list. Asked again when the image changes, and every 30 seconds while it differs."""
        if self._image_check and self._image_check[0] == image_id:
            _, checked_at, problem = self._image_check
            if not problem or time.monotonic() - checked_at < IMAGE_RECHECK_SECONDS:
                return problem
        rebuild = f"rebuild {IMAGE} from apps/evaluator"
        try:
            result = subprocess.run([*_isolated(f"admin-eval-lock-{uuid.uuid4().hex[:8]}"), IMAGE, "cat", IMAGE_LOCK],
                                    capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as error:
            problem = f"could not read the package list of {IMAGE}: {error}"
        else:
            if result.returncode != 0:
                problem = f"{IMAGE} has no {IMAGE_LOCK}: {rebuild}"
            elif packages.parse_lock(result.stdout.decode("utf-8", "replace")) != packages.lock():
                problem = f"{IMAGE} was built from another package list than {PACKAGE_LOCK.name}: {rebuild}"
            else:
                problem = None
        self._image_check = (image_id, time.monotonic(), problem)
        return problem

    def run(self, submission, zip_path, tick):
        work = WORK_DIR / f"submission-{submission.id}-{uuid.uuid4().hex[:8]}"
        code_dir, output_dir = work / "submission", work / "output"
        name, volume = f"admin-eval-{submission.id}-{work.name[-8:]}", None
        prune_abandoned()
        try:
            try:
                pins = inspect(zip_path)["packages"]
                safe_extract(zip_path, code_dir)
            except ZipRejected as error:
                return failure("zip_invalid", str(error))
            output_dir.mkdir(parents=True)
            os.chmod(output_dir, 0o777)
            if pins:
                volume = f"{VOLUME_PREFIX}{int(time.time())}-{submission.id}-{work.name[-8:]}"
                problem = self._install(f"{name}-install", volume, pins, tick)
                if problem:
                    return problem
            outcome = self._execute(name, code_dir, output_dir, volume, tick)
            if pins:
                outcome.log = f"installed from requirements.txt: {' '.join(pins)}\n{outcome.log or ''}"
            return outcome
        except OSError as error:
            return failure("system_error", log=f"worker I/O error: {error}")
        finally:
            shutil.rmtree(work, ignore_errors=True)
            if volume:
                _remove_volume(volume)

    def _install(self, name, volume, pins, tick):
        """None, or the failure to report. The packages passed the lock check at upload, so a
        failed install is the server's fault and never uses up the team's attempt."""
        try:
            code, log, stopped_for, _ = self._watch(name, install_command(name, volume, pins), INSTALL_TIMEOUT_SECONDS, tick)
        except OSError as error:
            return failure("system_error", log=f"could not start docker: {error}")
        if stopped_for or code != 0:
            reason = f"timed out after {INSTALL_TIMEOUT_SECONDS} s" if stopped_for else f"failed with exit code {code}"
            return failure("system_error", log=f"package install {reason}: {' '.join(pins)}\n{log}")
        return None

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
