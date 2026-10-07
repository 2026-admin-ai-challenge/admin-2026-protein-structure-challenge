import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import packages, zipcheck
from app.evaluators import docker as docker_evaluator
from app.packages import RequirementsRejected, pins
from app.zipcheck import ZipRejected
from conftest import make_zip

EVALUATOR = Path(__file__).resolve().parents[2] / "evaluator"


def test_lock_and_base_packages_agree():
    assert len(packages.lock()) == 89
    # The image installs its base packages from the wheels of the lock, so each must be there.
    base = pins((EVALUATOR / "requirements.txt").read_text(encoding="utf-8"))
    assert base == ["joblib==1.6.0", "numpy==2.5.3", "pandas==3.0.6", "scikit-learn==1.9.1", "scipy==1.18.1", "torch==2.14.1"]
    # A pip freeze of the competition environment is accepted as it is.
    assert len(pins((EVALUATOR / "requirements-competition.lock.txt").read_text(encoding="utf-8"))) == 89


def test_locked_versions_are_installed_whatever_the_file_asks():
    text = "numpy<2\nscikit_learn>=1.5,<2\npyyaml~=6.0\nHuggingface-Hub==1.33.*\ntorch==2.14.1+cu128\nfilelock==4.0.10\n"
    # Names as the lock writes them, versions from the lock: the image has no other version.
    assert pins(text) == ["filelock==4.0.9", "huggingface_hub==1.33.0", "numpy==2.5.3", "PyYAML==6.0.3",
                          "scikit-learn==1.9.1", "torch==2.14.1"]


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
    assert pins(text) == ["pandas==3.0.6", "scipy==1.18.1", "tzdata==2026.4"]


def test_unknown_packages_are_named():
    with pytest.raises(RequirementsRejected) as raised:
        pins("jupyterlab>=4,<5\nnumpy<2\nfilelock==4.0.10\ntensorflow\nnumpy==2.5.3\n")
    message = str(raised.value)
    assert "jupyterlab, tensorflow" in message
    assert "numpy" not in message and "filelock" not in message


@pytest.mark.parametrize("line,expected", [
    ("-r other.txt", "-r 옵션"),
    ("-e .", "-e 옵션"),
    ("--editable=git+https://github.com/a/b", "--editable 옵션"),
    ("--user", "지원하지 않는 옵션"),
    ("git+https://github.com/a/b.git", "해석할 수 없습니다"),
    ("./wheels/numpy-2.5.3-cp312-none-any.whl", "해석할 수 없습니다"),
    ("numpy @ file:///home/conda/feedstock_root/numpy", "URL"),
    ("transformers[torch]==5.18.0", "extras"),
])
def test_lines_that_would_fetch_something_else_are_refused(line, expected):
    with pytest.raises(RequirementsRejected, match="1번째 줄") as raised:
        pins(line + "\n")
    assert expected in str(raised.value)


def test_encodings_and_size():
    # PowerShell 5.1 `pip freeze > requirements.txt` writes UTF-16 with a BOM.
    assert packages.decode("numpy==2.5.3\r\n".encode("utf-16")) == "numpy==2.5.3\r\n"
    assert packages.decode("﻿numpy\n".encode("utf-8")) == "numpy\n"
    with pytest.raises(RequirementsRejected, match="읽을 수 없습니다"):
        packages.decode(b"numpy\x80\n")
    with pytest.raises(RequirementsRejected, match="너무 큽니다"):
        packages.decode(b"#" * (packages.MAX_BYTES + 1))


def test_zip_check_reads_the_root_requirements(tmp_path):
    path = tmp_path / "code.zip"
    path.write_bytes(make_zip(extra={"requirements.txt": "lightgbm==4.7.0\r\nnumpy\r\n".encode("utf-16"),
                                     "model/requirements.txt": "tensorflow\n"}))
    assert zipcheck.inspect(path)["packages"] == ["lightgbm==4.7.0", "numpy==2.5.3"]
    path.write_bytes(make_zip(extra={"requirements.txt": "tensorflow\n"}))
    with pytest.raises(ZipRejected, match="tensorflow"):
        zipcheck.inspect(path)
    path.write_bytes(make_zip(extra={"requirements.txt": ""}))
    assert zipcheck.inspect(path)["packages"] == []


def test_install_and_inference_containers(monkeypatch, tmp_path):
    monkeypatch.setattr(docker_evaluator, "WORK_DIR", tmp_path)
    monkeypatch.setattr(docker_evaluator, "WORK_HOST_DIR", tmp_path)
    monkeypatch.setattr(docker_evaluator, "INPUT_HOST_DIR", "/srv/eval-input")
    install = " ".join(docker_evaluator.install_command("admin-eval-1-install", "admin-eval-env-1", ["xgboost==3.4.1"]))
    for flag in ["--network none", "--read-only", "--user 65534:65534", "--cap-drop ALL", "no-new-privileges",
                 "--pids-limit", "--memory", "admin-eval-env-1:/deps:rw"]:
        assert flag in install
    # The install container sees neither the submission nor the evaluation input.
    assert "/submission" not in install and "/input" not in install
    assert install.endswith("python /opt/eval/install_packages.py /deps/venv xgboost==3.4.1")
    run = docker_evaluator.build_command("admin-eval-1", tmp_path / "s" / "submission", tmp_path / "s" / "output", "admin-eval-env-1")
    assert "admin-eval-env-1:/deps:ro" in run and run[run.index("admin-eval-env-1:/deps:ro") + 2].startswith("PATH=/deps/venv/bin:")
    assert "/deps" not in " ".join(docker_evaluator.build_command("admin-eval-1", tmp_path / "s" / "submission", tmp_path / "s" / "output"))


class FakeDocker:
    """Stands in for the docker CLI: records every container and volume command."""

    def __init__(self, install_code=0):
        self.install_code, self.containers, self.commands = install_code, [], []

    def run(self, command, **kwargs):
        self.commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    def watch(self, name, command, limit, tick, output_dir=None):
        self.containers.append(command)
        if output_dir is None:
            return self.install_code, "pip output", None, 1.0
        (output_dir / "predictions.csv").write_bytes(b"id,label\n")
        return 0, "inference output", None, 1.0


@pytest.mark.parametrize("requirements,installed", [("", False), ("numpy\nlightgbm==4.7.0\n", True)])
def test_packages_are_installed_into_a_volume_for_the_run(monkeypatch, tmp_path, requirements, installed):
    monkeypatch.setattr(docker_evaluator, "WORK_DIR", tmp_path)
    monkeypatch.setattr(docker_evaluator, "WORK_HOST_DIR", tmp_path)
    fake = FakeDocker()
    monkeypatch.setattr(docker_evaluator.subprocess, "run", fake.run)
    monkeypatch.setattr(docker_evaluator.DockerEvaluator, "_watch", lambda self, *args, **kwargs: fake.watch(*args, **kwargs))
    path = tmp_path / "code.zip"
    path.write_bytes(make_zip(extra={"requirements.txt": requirements}))
    outcome = docker_evaluator.DockerEvaluator().run(SimpleNamespace(id=7), path, lambda: None)
    assert outcome.ok and outcome.predictions == b"id,label\n"
    if not installed:
        assert len(fake.containers) == 1 and "/deps" not in " ".join(fake.containers[0])
        return
    install, inference = fake.containers
    volume = next(part.split(":")[0] for part in install if part.endswith(":/deps:rw"))
    assert volume.startswith("admin-eval-env-") and install[-2:] == ["lightgbm==4.7.0", "numpy==2.5.3"]
    assert f"{volume}:/deps:ro" in inference
    assert ["docker", "volume", "rm", "-f", volume] in fake.commands  # removed after the run
    assert "installed from requirements.txt: lightgbm==4.7.0 numpy==2.5.3" in outcome.log


def test_failed_install_is_a_server_error(monkeypatch, tmp_path):
    monkeypatch.setattr(docker_evaluator, "WORK_DIR", tmp_path)
    monkeypatch.setattr(docker_evaluator, "WORK_HOST_DIR", tmp_path)
    fake = FakeDocker(install_code=1)
    monkeypatch.setattr(docker_evaluator.subprocess, "run", fake.run)
    monkeypatch.setattr(docker_evaluator.DockerEvaluator, "_watch", lambda self, *args, **kwargs: fake.watch(*args, **kwargs))
    path = tmp_path / "code.zip"
    path.write_bytes(make_zip(extra={"requirements.txt": "lightgbm\n"}))
    outcome = docker_evaluator.DockerEvaluator().run(SimpleNamespace(id=8), path, lambda: None)
    # The package list passed the upload check, so the team is not blamed and inference never runs.
    assert outcome.failure_code == "system_error" and "pip output" in outcome.log
    assert len(fake.containers) == 1
    assert any(command[:4] == ["docker", "volume", "rm", "-f"] for command in fake.commands)


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


def test_image_must_hold_the_same_lock(monkeypatch):
    monkeypatch.setattr(docker_evaluator, "INPUT_HOST_DIR", "/srv/eval-input")
    lock_text = (EVALUATOR / "requirements-competition.lock.txt").read_text(encoding="utf-8")
    image = {"id": "sha256:1", "lock": lock_text}
    reads = []

    def run(command, **kwargs):
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(command, 0, stdout=image["id"].encode() + b"\n", stderr=b"")
        reads.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=image["lock"].encode(), stderr=b"")

    monkeypatch.setattr(docker_evaluator.subprocess, "run", run)
    evaluator = docker_evaluator.DockerEvaluator()
    assert evaluator.ready()[0] and evaluator.ready()[0]
    assert len(reads) == 1  # read once per image
    image.update(id="sha256:2", lock=lock_text.replace("numpy==2.5.3", "numpy==2.6.0"))
    ok, detail = evaluator.ready()
    assert not ok and "rebuild" in detail and len(reads) == 2
