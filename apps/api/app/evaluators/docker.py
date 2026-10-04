"""Runs participant inference in a locked-down container.

The container gets the unpacked submission and the hidden evaluation INPUT, both read
only, plus one writable output directory. It never receives labels, the Public/Private
split, database credentials or the Docker socket, and it has no network.

PROVISIONAL contract (to be fixed with the data team, Q2):
    working directory /submission,
    command `python inference.py --input /input/test_features.csv --output /output/predictions.csv`
    /input also holds test.csv (id,sequence) and test_structures.zip, like the starter kit.
    output: UTF-8 CSV with header `id,label`, one row per evaluation ID.
"""
import collections
import os
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


def build_command(name, code_dir: Path, output_dir: Path):
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
        "-v", f"{_host_path(code_dir)}:/submission:ro",
        "-v", f"{INPUT_HOST_DIR}:/input:ro",
        "-v", f"{_host_path(output_dir)}:/output:rw",
        "-w", "/submission",
        IMAGE,
        # Second timer inside the container: it still stops if the worker dies mid-run.
        "timeout", "--signal=KILL", str(INFERENCE_TIMEOUT_SECONDS + KILL_GRACE_SECONDS),
        *shlex.split(COMMAND),
    ]


def prune_abandoned():
    """Removes work directories left behind by a worker that died mid-run. Only ones old
    enough that no live run can still own them are touched."""
    cutoff = time.time() - (2 * INFERENCE_TIMEOUT_SECONDS + 600)
    for directory in WORK_DIR.glob("submission-*"):
        try:
            if directory.stat().st_mtime < cutoff:
                shutil.rmtree(directory, ignore_errors=True)
        except OSError:
            pass


class DockerEvaluator(Evaluator):
    name = "docker"

    def ready(self):
        if not INPUT_HOST_DIR:
            return False, "EVAL_INPUT_HOST_DIR is not set"
        try:
            probe = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired) as error:
            return False, f"docker is not reachable: {error}"
        if probe.returncode != 0:
            return False, f"evaluation image not found: {IMAGE}"
        return True, f"docker evaluator: image {IMAGE}, {CPUS} cpus, {MEMORY} memory"

    def run(self, submission, zip_path, tick):
        work = WORK_DIR / f"submission-{submission.id}-{uuid.uuid4().hex[:8]}"
        code_dir, output_dir = work / "submission", work / "output"
        prune_abandoned()
        try:
            try:
                inspect(zip_path)
                safe_extract(zip_path, code_dir)
            except ZipRejected as error:
                return failure("zip_invalid", str(error))
            output_dir.mkdir(parents=True)
            os.chmod(output_dir, 0o777)
            return self._execute(f"admin-eval-{submission.id}-{work.name[-8:]}", code_dir, output_dir, tick)
        except OSError as error:
            return failure("system_error", log=f"worker I/O error: {error}")
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _execute(self, name, code_dir, output_dir, tick):
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

        try:
            process = subprocess.Popen(build_command(name, code_dir, output_dir),
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except OSError as error:
            return failure("system_error", log=f"could not start docker: {error}")
        reader = threading.Thread(target=drain, args=(process.stdout,), daemon=True)
        reader.start()
        started = time.monotonic()
        stopped_for = None
        while process.poll() is None:
            if time.monotonic() - started > INFERENCE_TIMEOUT_SECONDS:
                stopped_for = "timeout"
            elif _directory_size(output_dir) > MAX_OUTPUT_BYTES:
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
        elapsed = time.monotonic() - started
        code = process.returncode

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
