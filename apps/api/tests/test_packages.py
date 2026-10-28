import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import packages, zipcheck
from app.evaluators import docker as docker_evaluator
from app.packages import RequirementsRejected, requirements
from app.zipcheck import ZipRejected
from conftest import make_zip

EVALUATOR = Path(__file__).resolve().parents[2] / "evaluator"


def test_base_packages_come_from_the_lock():
    lock = requirements((EVALUATOR / "requirements-competition.lock.txt").read_text(encoding="utf-8"))
    assert len(lock) == 89 and all("==" in item for item in lock)
    # The image installs its base packages from the wheels of the lock, so each must be there.
    base = requirements((EVALUATOR / "requirements.txt").read_text(encoding="utf-8"))
    assert base == ["catboost==1.2.10", "joblib==1.6.0", "matplotlib==3.11.2", "numpy==2.5.3", "pandas==3.0.6",
                    "plotly==7.1.0", "pyarrow==25.0.1", "scikit-learn==1.9.1", "scipy==1.18.1", "SQLAlchemy==2.1.1",
                    "torch==2.14.1", "transformers==5.18.0"]
    assert set(base) <= set(lock)


def test_versions_are_kept_as_written():
    text = ("numpy<2\nscikit_learn>=1.5,<2\npyyaml~=6.0\ntorch==2.14.1+cu128\nfilelock==4.0.10\n"
            "tensorflow\ntransformers[torch]==5.18.0\nnumpy>=1.20\n")
    # Any PyPI package; lines naming the same package are merged; a CUDA build label is dropped.
    assert requirements(text) == ["filelock==4.0.10", "numpy<2,>=1.20", "pyyaml~=6.0", "scikit_learn<2,>=1.5",
                                  "tensorflow", "torch==2.14.1", "transformers[torch]==5.18.0"]


def test_pip_file_syntax():
    text = "\n".join([
        "# pip freeze",
        "--extra-index-url https://download.pytorch.org/whl/cpu",
        "-i https://pypi.org/simple",
        "pandas==3.0.6  # tables",
        "scipy==1.18.1 \\",
        "    --hash=sha256:0123 \\",
        "    --hash=sha256:4567",
        'colorama==0.4.6 ; sys_platform == "win32"',
        'pywin32==311 ; platform_system == "Windows"',
        'tzdata ; sys_platform == "linux"',
        "",
    ])
    # Windows-only lines are skipped as pip would skip them in the Linux container.
    assert requirements(text) == ["pandas==3.0.6", "scipy==1.18.1", "tzdata"]


@pytest.mark.parametrize("line,expected", [
    ("-r other.txt", "-r 옵션"),
    ("-e .", "-e 옵션"),
    ("--editable=git+https://github.com/a/b", "--editable 옵션"),
    ("--user", "지원하지 않는 옵션"),
    ("git+https://github.com/a/b.git", "해석할 수 없습니다"),
    ("./wheels/numpy-2.5.3-cp312-none-any.whl", "해석할 수 없습니다"),
    ("numpy @ file:///home/conda/feedstock_root/numpy", "URL"),
    ("numpy @ https://example.com/numpy.whl", "URL"),
])
def test_lines_that_would_fetch_from_elsewhere_are_refused(line, expected):
    with pytest.raises(RequirementsRejected, match="1번째 줄") as raised:
        requirements(line + "\n")
    assert expected in str(raised.value)


def test_encodings_and_size():
    # PowerShell 5.1 `pip freeze > requirements.txt` writes UTF-16 with a BOM.
    assert packages.decode("numpy==2.5.3\r\n".encode("utf-16")) == "numpy==2.5.3\r\n"
    assert packages.decode("﻿numpy\n".encode("utf-8")) == "numpy\n"
    with pytest.raises(RequirementsRejected, match="읽을 수 없습니다"):
        packages.decode(b"numpy\x80\n")
    with pytest.raises(RequirementsRejected, match="너무 큽니다"):
        packages.decode(b"#" * (packages.MAX_BYTES + 1))
    with pytest.raises(RequirementsRejected, match="너무 많습니다"):
        requirements("".join(f"package-{index}\n" for index in range(packages.MAX_REQUIREMENTS + 1)))


def test_zip_check_reads_the_root_requirements(tmp_path):
    path = tmp_path / "code.zip"
    path.write_bytes(make_zip(extra={"requirements.txt": "lightgbm==4.7.0\r\nnumpy\r\n".encode("utf-16"),
                                     "model/requirements.txt": "-e .\n"}))
    assert zipcheck.inspect(path)["packages"] == ["lightgbm==4.7.0", "numpy"]
    path.write_bytes(make_zip(extra={"requirements.txt": "numpy\n-r more.txt\n"}))
    with pytest.raises(ZipRejected, match="2번째 줄"):
        zipcheck.inspect(path)
    path.write_bytes(make_zip(extra={"requirements.txt": ""}))
    assert zipcheck.inspect(path)["packages"] == []


def test_install_and_inference_containers(monkeypatch, tmp_path):
    monkeypatch.setattr(docker_evaluator, "WORK_DIR", tmp_path)
    monkeypatch.setattr(docker_evaluator, "WORK_HOST_DIR", tmp_path)
    monkeypatch.setattr(docker_evaluator, "INPUT_HOST_DIR", "/srv/eval-input")
    isolation = ["--read-only", "--user 65534:65534", "--cap-drop ALL", "no-new-privileges", "--pids-limit", "--memory",
                 "admin-eval-env-1:/deps:rw"]
    offline = " ".join(docker_evaluator.install_command("i-offline", "admin-eval-env-1", ["xgboost==3.4.1"]))
    online = " ".join(docker_evaluator.install_command("i-online", "admin-eval-env-1", ["xgboost==3.4.1"], online=True))
    for flag in isolation:
        assert flag in offline and flag in online
    # Only the online pass reaches the network, with the shared pip cache.
    assert "--network none" in offline and "pip-cache" not in offline
    assert "--network bridge" in online and "admin-eval-pip-cache:/pip-cache:rw" in online
    assert offline.endswith("python /opt/eval/install_packages.py offline /deps/venv xgboost==3.4.1")
    assert online.endswith("python /opt/eval/install_packages.py online /deps/venv xgboost==3.4.1")
    # Install containers see neither the submission nor the evaluation input.
    for command in (offline, online):
        assert "/submission" not in command and "/input" not in command
    monkeypatch.setattr(docker_evaluator, "PIP_CACHE_VOLUME", "")
    assert "PIP_NO_CACHE_DIR=1" in docker_evaluator.install_command("i", "v", ["x"], online=True)
    run = docker_evaluator.build_command("admin-eval-1", tmp_path / "s" / "submission", tmp_path / "s" / "output", "admin-eval-env-1")
    assert "--network none" in " ".join(run) and "admin-eval-env-1:/deps:ro" in run
    assert run[run.index("admin-eval-env-1:/deps:ro") + 2].startswith("PATH=/deps/venv/bin:")
    assert "/deps" not in " ".join(docker_evaluator.build_command("admin-eval-1", tmp_path / "s" / "submission", tmp_path / "s" / "output"))


class FakeDocker:
    """Stands in for the docker CLI. `installs` are the (exit code, output) of each install pass."""

    def __init__(self, *installs):
        self.installs, self.containers, self.commands = list(installs), [], []

    def run(self, command, **kwargs):
        self.commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    def watch(self, name, command, limit, tick, output_dir=None):
        self.containers.append(command)
        if output_dir is None:
            code, log = self.installs.pop(0)
            return code, log, None, 1.0
        (output_dir / "predictions.csv").write_bytes(b"id,label\n")
        return 0, "inference output", None, 1.0


def score(monkeypatch, tmp_path, fake, requirements_text):
    monkeypatch.setattr(docker_evaluator, "WORK_DIR", tmp_path)
    monkeypatch.setattr(docker_evaluator, "WORK_HOST_DIR", tmp_path)
    monkeypatch.setattr(docker_evaluator.subprocess, "run", fake.run)
    monkeypatch.setattr(docker_evaluator.DockerEvaluator, "_watch", lambda self, *args, **kwargs: fake.watch(*args, **kwargs))
    path = tmp_path / "code.zip"
    path.write_bytes(make_zip(extra={"requirements.txt": requirements_text}))
    return docker_evaluator.DockerEvaluator().run(SimpleNamespace(id=7), path, lambda: None)


def volume_of(command):
    return next(part.split(":")[0] for part in command if part.endswith(":/deps:rw"))


def test_no_requirements_means_no_install(monkeypatch, tmp_path):
    fake = FakeDocker()
    outcome = score(monkeypatch, tmp_path, fake, "")
    assert outcome.ok and outcome.predictions == b"id,label\n"
    assert len(fake.containers) == 1 and "/deps" not in " ".join(fake.containers[0])


def test_image_wheels_are_enough_without_network(monkeypatch, tmp_path):
    fake = FakeDocker((0, "installed"))
    outcome = score(monkeypatch, tmp_path, fake, "numpy\nlightgbm==4.7.0\n")
    offline, inference = fake.containers
    volume = volume_of(offline)
    assert "none" in offline and offline[-2:] == ["lightgbm==4.7.0", "numpy"]
    assert outcome.ok and f"{volume}:/deps:ro" in inference
    assert ["docker", "volume", "rm", "-f", volume] in fake.commands  # removed after the run
    assert "installed from requirements.txt (image wheels): lightgbm==4.7.0 numpy" in outcome.log


def test_missing_wheels_are_downloaded_before_isolated_inference(monkeypatch, tmp_path):
    fake = FakeDocker((1, "ERROR: No matching distribution found for tensorflow"), (0, "installed"))
    outcome = score(monkeypatch, tmp_path, fake, "tensorflow==2.20.0\n")
    offline, online, inference = fake.containers
    assert volume_of(offline) == volume_of(online)
    assert online[online.index("--network") + 1] == "bridge"
    assert inference[inference.index("--network") + 1] == "none"
    assert outcome.ok and "(PyPI): tensorflow==2.20.0" in outcome.log


def test_package_that_cannot_be_installed_is_the_teams_failure(monkeypatch, tmp_path):
    pip = "Collecting nosuchpackage\nERROR: Could not find a version that satisfies the requirement nosuchpackage\n" \
          "ERROR: No matching distribution found for nosuchpackage"
    fake = FakeDocker((1, pip), (1, pip))
    outcome = score(monkeypatch, tmp_path, fake, "nosuchpackage\n")
    # pip's errors reach the team: the install container never holds anything secret.
    assert outcome.failure_code == "install_failed" and "No matching distribution found for nosuchpackage" in outcome.message
    assert len(fake.containers) == 2  # inference never runs
    assert any(command[:4] == ["docker", "volume", "rm", "-f"] for command in fake.commands)


@pytest.mark.parametrize("installs", [
    [(1, "missing"), (1, "WARNING: Retrying after connection broken by 'NewConnectionError(...)'\nERROR: No matching distribution")],
    [(125, "docker: Error response from daemon")],
])
def test_unreachable_pypi_or_docker_is_a_server_error(monkeypatch, tmp_path, installs):
    fake = FakeDocker(*installs)
    outcome = score(monkeypatch, tmp_path, fake, "tensorflow\n")
    assert outcome.failure_code == "system_error" and len(fake.containers) == len(installs)


def test_abandoned_volumes_are_pruned(monkeypatch, tmp_path):
    monkeypatch.setattr(docker_evaluator, "WORK_DIR", tmp_path)
    old, recent = "admin-eval-env-1000-3-aaaaaaaa", f"admin-eval-env-{int(docker_evaluator.time.time())}-4-bbbbbbbb"
    removed = []

    def run(command, **kwargs):
        if command[:3] == ["docker", "volume", "ls"]:
            return subprocess.CompletedProcess(command, 0, stdout=f"{old}\n{recent}\n".encode(), stderr=b"")
        removed.append(command[-1])
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(docker_evaluator.subprocess, "run", run)
    docker_evaluator.prune_abandoned()
    assert removed == [old]


@pytest.mark.parametrize("label,ok", [("1\n", True), ("<no value>\n", False)])
def test_image_without_the_installer_is_not_ready(monkeypatch, label, ok):
    # An older image would fail every install as if the team were at fault.
    monkeypatch.setattr(docker_evaluator, "INPUT_HOST_DIR", "/srv/eval-input")
    monkeypatch.setattr(docker_evaluator.subprocess, "run",
                        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, stdout=label.encode(), stderr=b""))
    ready, detail = docker_evaluator.DockerEvaluator().ready()
    assert ready == ok and (ok or "rebuild" in detail)
