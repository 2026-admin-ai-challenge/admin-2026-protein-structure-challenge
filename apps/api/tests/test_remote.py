import os
import shlex
import sys
import textwrap
import types

import pytest

from app import evaluators
from app.evaluators import docker as local
from app.evaluators import remote
from app.evaluators.remote import Check, RemoteEvaluator, TargetInvalid, load_target, preflight, remote_shell, ssh_command
from conftest import make_zip

TARGET = remote.Target("100.64.0.10", 2222, "evaluator", "/run/secrets/eval_ssh_key", "/run/secrets/eval_known_hosts")
SYSTEM_OK = "os=Linux\ngpu=0, Tesla P100-PCIE-16GB, 535.183.01, 16384 MiB\ndocker=27.3.1\ntoolkit=ok\n"
PROJECT_OK = "image=1\nwork=ok\nfree_kb=104857600\n"
GPU_OK = "GPU 0: Tesla P100-PCIE-16GB (UUID: GPU-1)\n"


def env(**values):
    return {"EVAL_SSH_HOST": "100.64.0.10", "EVAL_SSH_USER": "evaluator", **values}


def test_remote_is_a_third_evaluator(monkeypatch):
    monkeypatch.setattr(evaluators, "EVALUATOR", "remote")
    assert isinstance(evaluators.get_evaluator(), RemoteEvaluator)
    assert RemoteEvaluator.name == "remote" and len(RemoteEvaluator.name) <= 12  # submissions.evaluator is String(12)


def test_target_accepts_addresses_and_names():
    assert load_target(env()).host == "100.64.0.10"
    assert load_target(env(EVAL_SSH_HOST="gpu.example.ac.kr", EVAL_SSH_PORT="2222")).port == 2222
    assert load_target(env(EVAL_SSH_HOST="fd7a:115c:a1e0::1")).host == "fd7a:115c:a1e0::1"


@pytest.mark.parametrize("values", [
    {"EVAL_SSH_HOST": ""}, {"EVAL_SSH_USER": ""},
    # Anything ssh could read as an option, or a shell could read as a command, is refused.
    {"EVAL_SSH_HOST": "-oProxyCommand=touch /tmp/x"}, {"EVAL_SSH_HOST": "host; rm -rf /"}, {"EVAL_SSH_HOST": "a b"},
    {"EVAL_SSH_USER": "-oProxyCommand=x"}, {"EVAL_SSH_USER": "root;id"}, {"EVAL_SSH_USER": "Root"},
    {"EVAL_SSH_PORT": "0"}, {"EVAL_SSH_PORT": "65536"}, {"EVAL_SSH_PORT": "22 -o x"},
])
def test_target_refuses_what_could_become_an_option_or_a_command(values):
    with pytest.raises(TargetInvalid):
        load_target(env(**values))


def test_allow_list_limits_where_submissions_may_go():
    assert load_target(env(EVAL_SSH_ALLOWED="100.64.0.0/10, 168.188.0.0/16")).host == "100.64.0.10"
    with pytest.raises(TargetInvalid, match="outside"):
        load_target(env(EVAL_SSH_HOST="203.0.113.5", EVAL_SSH_ALLOWED="100.64.0.0/10"))
    with pytest.raises(TargetInvalid, match="outside"):  # a name could resolve anywhere
        load_target(env(EVAL_SSH_HOST="gpu.example.org", EVAL_SSH_ALLOWED="100.64.0.0/10"))
    with pytest.raises(TargetInvalid, match="CIDR"):
        load_target(env(EVAL_SSH_ALLOWED="not-a-network"))


def test_ssh_command_checks_the_host_key_and_never_prompts():
    command = ssh_command(TARGET, "true")
    joined = " ".join(command)
    for option in ["StrictHostKeyChecking=yes", "BatchMode=yes", "PasswordAuthentication=no", "IdentitiesOnly=yes",
                   "UserKnownHostsFile=/run/secrets/eval_known_hosts", "ForwardAgent=no", "ClearAllForwardings=yes"]:
        assert option in joined
    assert command[:3] == ["ssh", "-F", "/dev/null"] and "-n" in command
    assert command[-3:] == ["--", "100.64.0.10", "true"]  # the host can never be read as an option
    assert "-n" not in ssh_command(TARGET, "cat", stdin=True)


def test_remote_shell_keeps_arguments_and_hides_a_submission_exit_255():
    command = ["docker", "run", "--gpus", '"device=0"', "--format", "{{.X}} y", "it's"]
    shell, flag, script = shlex.split(remote_shell(command, guard=True))
    assert (shell, flag) == ("sh", "-c")
    run, guard = script.split(";", 1)
    assert shlex.split(run) == command  # every argument reaches docker unchanged, quotes included
    assert '"$c" -eq 255' in guard and "exit 1" in guard
    assert shlex.split(remote_shell(command))[2] == shlex.join(command)


def test_gpu_reaches_inference_but_never_the_install(monkeypatch, tmp_path):
    monkeypatch.setattr(local, "WORK_DIR", tmp_path)
    monkeypatch.setattr(local, "WORK_HOST_DIR", tmp_path)
    monkeypatch.setattr(local, "GPUS", "0,1")
    run = local.build_command("admin-eval-1", tmp_path / "s" / "submission", tmp_path / "s" / "output")
    assert run[run.index("--gpus") + 1] == '"device=0,1"' and run[run.index("--network") + 1] == "none"
    assert "--gpus" not in local.install_command("i", "v", ["x"], online=True)
    monkeypatch.setattr(local, "GPUS", "")
    assert "--gpus" not in local.build_command("admin-eval-1", tmp_path / "s" / "submission", tmp_path / "s" / "output")


def scripted(monkeypatch, *responses):
    """Replaces the ssh call with canned (exit code, stdout, stderr) answers; returns the commands sent."""
    sent, answers = [], list(responses)

    def fake(target, command, timeout):
        sent.append(command)
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(remote, "_run", fake)
    return sent


@pytest.fixture
def gpu_zero(monkeypatch):
    monkeypatch.setattr(local, "GPUS", "0")
    monkeypatch.setattr(local, "INPUT_HOST_DIR", "/srv/admin-eval-input")
    monkeypatch.setattr(local, "WORK_HOST_DIR", local.Path("/srv/admin-eval-work"))


def failed(checks):
    return {check.name: check for check in checks if not check.ok}


def test_a_ready_machine_passes_every_check(monkeypatch, gpu_zero):
    sent = scripted(monkeypatch, (0, SYSTEM_OK, ""), (0, PROJECT_OK, ""), (0, GPU_OK, ""))
    checks, gpus = preflight(TARGET)
    assert not failed(checks) and gpus[0][1] == "Tesla P100-PCIE-16GB"
    assert {"os", "nvidia_driver", "docker", "nvidia_toolkit", "image", "input", "work_dir", "gpu_container"} <= {c.name for c in checks}
    assert "--gpus" in sent[2] and "--network none" in sent[2]


@pytest.mark.parametrize("stderr, hint", [
    ("Host key verification failed.", "ssh-keyscan"),
    ("evaluator@100.64.0.10: Permission denied (publickey).", "authorized_keys"),
    ("ssh: connect to host 100.64.0.10 port 2222: Connection refused", "방화벽"),
])
def test_a_failed_connection_is_cancelled_with_its_reason(monkeypatch, gpu_zero, stderr, hint):
    scripted(monkeypatch, (255, "", stderr))
    checks, _ = preflight(TARGET)
    assert [c.name for c in checks] == ["ssh"] and not checks[0].ok
    assert stderr in checks[0].reason and hint in checks[0].fix


def test_missing_driver_docker_and_toolkit_are_each_named(monkeypatch, gpu_zero):
    scripted(monkeypatch, (0, "os=Linux\nnvidia=missing\ndocker=missing\ntoolkit=missing\n", ""))
    checks, _ = preflight(TARGET)
    problems = failed(checks)
    assert set(problems) == {"nvidia_driver", "docker", "nvidia_toolkit"}
    assert "NVIDIA 드라이버" in problems["nvidia_driver"].reason
    assert "Docker가 설치돼 있지 않습니다" in problems["docker"].reason
    assert "Container Toolkit" in problems["nvidia_toolkit"].reason and "nvidia-ctk" in problems["nvidia_toolkit"].fix
    message = remote.describe(TARGET, checks)
    assert message.startswith("원격 채점 서버 evaluator@100.64.0.10:2222 연결을 취소했습니다. 사유:")
    assert message.count("\n") == 3 and "→" in message


@pytest.mark.parametrize("state, words", [("denied", "docker 그룹"), ("down", "꺼져"), ("error:boom", "boom")])
def test_docker_that_cannot_be_used_says_why(monkeypatch, gpu_zero, state, words):
    scripted(monkeypatch, (0, SYSTEM_OK.replace("docker=27.3.1", f"docker={state}"), ""))
    problems = failed(preflight(TARGET)[0])
    assert list(problems) == ["docker"] and words in problems["docker"].reason


def test_windows_and_wrong_gpu_numbers_are_refused(monkeypatch, gpu_zero):
    monkeypatch.setattr(local, "GPUS", "3")
    scripted(monkeypatch, (0, SYSTEM_OK.replace("os=Linux", "os=MINGW64_NT"), ""), (0, PROJECT_OK, ""))
    problems = failed(preflight(TARGET)[0])
    assert set(problems) == {"os", "gpu_selection"}
    assert "WSL2" in problems["os"].fix and "0" in problems["gpu_selection"].reason


def test_project_problems_are_found_after_the_system_passes(monkeypatch, gpu_zero):
    scripted(monkeypatch, (0, SYSTEM_OK, ""),
             (0, "image=missing\ninput_missing=test.csv\ninput_missing=test_structures.zip\nwork=ok\nfree_kb=1048576\n", ""))
    problems = failed(preflight(TARGET)[0])
    assert set(problems) == {"image", "input", "disk"}  # no GPU container test without the image
    assert "docker pull" in problems["image"].fix
    assert "test.csv, test_structures.zip" in problems["input"].reason and "1.0 GB" in problems["disk"].reason


def test_a_container_that_cannot_see_the_gpu_cancels_the_connection(monkeypatch, gpu_zero):
    scripted(monkeypatch, (0, SYSTEM_OK, ""), (0, PROJECT_OK, ""),
             (125, "", "docker: Error response from daemon: could not select device driver \"\" with capabilities: [[gpu]]."))
    problems = failed(preflight(TARGET)[0])
    assert list(problems) == ["gpu_container"] and "could not select device driver" in problems["gpu_container"].reason


def ready_machine(monkeypatch, tmp_path):
    key, known = tmp_path / "key", tmp_path / "known_hosts"
    key.write_text("key")
    known.write_text("[100.64.0.10]:2222 ssh-ed25519 AAAA")
    for name, value in env(EVAL_SSH_PORT="2222", EVAL_SSH_KEY=str(key), EVAL_SSH_KNOWN_HOSTS=str(known),
                           EVAL_WORK_HOST_DIR="/srv/admin-eval-work").items():
        monkeypatch.setenv(name, value)


def test_ready_reports_the_reasons_and_takes_no_work(monkeypatch, tmp_path, gpu_zero):
    ready_machine(monkeypatch, tmp_path)
    calls = []

    def fake(target, gpu_container=True):
        calls.append(gpu_container)
        return [Check("os", True), Check("docker", False, "Docker가 설치돼 있지 않습니다.", "설치하세요.")], []

    monkeypatch.setattr(remote, "preflight", fake)
    evaluator = RemoteEvaluator()
    ok, detail = evaluator.ready()
    assert not ok and "연결을 취소했습니다" in detail and "Docker가 설치돼 있지 않습니다. → 설치하세요." in detail
    assert evaluator.ready() == (ok, detail) and len(calls) == 1  # looked at again only after a while


def test_ready_without_settings_names_what_is_missing(monkeypatch, tmp_path, gpu_zero):
    monkeypatch.delenv("EVAL_SSH_HOST", raising=False)
    ok, detail = RemoteEvaluator().ready()
    assert not ok and "EVAL_SSH_HOST" in detail
    ready_machine(monkeypatch, tmp_path)
    monkeypatch.setenv("EVAL_SSH_KEY", str(tmp_path / "absent"))
    ok, detail = RemoteEvaluator().ready()
    assert not ok and "SSH 개인키 파일" in detail and "absent" in detail


def test_ready_machine_proves_the_gpu_only_now_and_then(monkeypatch, tmp_path, gpu_zero):
    ready_machine(monkeypatch, tmp_path)
    calls = []

    def fake(target, gpu_container=True):
        calls.append(gpu_container)
        return [Check("os", True)], [["0", "Tesla P100-PCIE-16GB", "535.183.01", "16384 MiB"]]

    monkeypatch.setattr(remote, "preflight", fake)
    evaluator = RemoteEvaluator()
    ok, detail = evaluator.ready()
    assert ok and "GPU 0 Tesla P100-PCIE-16GB" in detail and "evaluator@100.64.0.10:2222" in detail
    evaluator._verdict = None  # as if the cache ran out
    assert evaluator.ready()[0] and calls == [True, False]


# --- the whole run, with a fake ssh that runs the remote command here and a fake docker ---

FAKE_SSH = """\
#!/usr/bin/env python3
import os, sys
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write("ssh " + " ".join(sys.argv[1:]) + "\\n")
if os.environ.get("FAKE_SSH_DOWN"):
    sys.stderr.write("ssh: connect to host port: Connection refused\\n")
    sys.exit(255)
arguments = sys.argv[1:]
command = arguments[arguments.index("--") + 2]
os.execvp("sh", ["sh", "-c", command])
"""

FAKE_DOCKER = """\
#!/usr/bin/env python3
import os, sys
arguments = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write("docker " + " ".join(arguments) + "\\n")
if arguments[:2] == ["image", "inspect"]:
    print("1")
elif arguments[:1] == ["run"]:
    mounts = dict(reversed(value.split(":")[:2]) for flag, value in zip(arguments, arguments[1:]) if flag == "-v")
    if "/output" in mounts:
        behaviour = open(os.path.join(mounts["/submission"], "behave.txt")).read().strip()
        target = os.path.join(mounts["/output"], "predictions.csv")
        if behaviour == "exit255":
            sys.exit(255)
        if behaviour == "symlink":
            os.symlink("/etc/passwd", target)
        elif behaviour == "ok":
            with open(target, "w") as output:
                output.write("id,label\\nTEST_1,1.10\\n")
"""


@pytest.fixture
def fake_machine(monkeypatch, tmp_path):
    if os.name == "nt":
        pytest.skip("runs fake ssh/docker scripts through sh")
    bin_dir, log = tmp_path / "bin", tmp_path / "calls.log"
    bin_dir.mkdir()
    for name, script in {"ssh": FAKE_SSH, "docker": FAKE_DOCKER}.items():
        (bin_dir / name).write_text(textwrap.dedent(script))
        (bin_dir / name).chmod(0o755)
    remote_work, remote_input = tmp_path / "gpu" / "work", tmp_path / "gpu" / "input"
    remote_input.mkdir(parents=True)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setattr(local, "WORK_DIR", tmp_path / "here")
    monkeypatch.setattr(local, "WORK_HOST_DIR", remote_work)
    monkeypatch.setattr(local, "INPUT_HOST_DIR", str(remote_input))
    monkeypatch.setattr(local, "GPUS", "0")
    for name, value in env(EVAL_SSH_KEY=str(tmp_path / "key"), EVAL_SSH_KNOWN_HOSTS=str(tmp_path / "known")).items():
        monkeypatch.setenv(name, value)
    return types.SimpleNamespace(log=log, work=remote_work, tmp=tmp_path)


def passed(evaluator=None):
    """An evaluator whose machine passed its checks (the fake machine has no real GPU)."""
    evaluator = evaluator or RemoteEvaluator()
    evaluator._verified = load_target()
    return evaluator


def run_with(machine, behaviour, evaluator=None):
    path = machine.tmp / "code.zip"
    path.write_bytes(make_zip(extra={"behave.txt": behaviour}))
    return (evaluator or passed()).run(types.SimpleNamespace(id=7), path, lambda: None)


def test_a_submission_runs_on_the_gpu_machine_and_comes_back(fake_machine):
    outcome = run_with(fake_machine, "ok")
    assert outcome.ok and outcome.predictions == b"id,label\nTEST_1,1.10\n"
    calls = fake_machine.log.read_text()
    assert "StrictHostKeyChecking=yes" in calls
    inference = next(line for line in calls.splitlines() if line.startswith("docker run") and "/output" in line)
    assert '--gpus "device=0"' in inference and "--network none" in inference and "--read-only" in inference
    assert list(fake_machine.work.glob("submission-*")) == []  # removed on the GPU machine
    assert list((fake_machine.tmp / "here").glob("submission-*")) == []  # and here
    assert "docker rm -f admin-eval-7-" in calls  # containers that could outlive a dropped link


def test_a_run_stays_on_the_machine_that_passed(fake_machine, monkeypatch):
    evaluator = passed()
    monkeypatch.setenv("EVAL_SSH_HOST", "203.0.113.9")  # changed while the queue waits
    assert run_with(fake_machine, "ok", evaluator).ok
    assert "203.0.113.9" not in fake_machine.log.read_text()


def test_no_run_without_a_machine_that_passed(fake_machine):
    outcome = run_with(fake_machine, "ok", RemoteEvaluator())
    assert outcome.failure_code == "system_error" and not fake_machine.log.exists()


def test_leftovers_are_looked_for_now_and_then(fake_machine):
    evaluator = passed()
    assert run_with(fake_machine, "ok", evaluator).ok and run_with(fake_machine, "ok", evaluator).ok
    assert fake_machine.log.read_text().count("find ") == 1


def test_exit_255_from_a_submission_is_its_own_error(fake_machine):
    outcome = run_with(fake_machine, "exit255")
    assert (outcome.failure_code, outcome.message.endswith("(종료 코드 1)")) == ("runtime_error", True)


def test_a_planted_link_is_not_followed(fake_machine):
    assert run_with(fake_machine, "symlink").failure_code == "output_missing"


def test_an_unreachable_machine_is_a_server_error_and_is_checked_again(fake_machine, monkeypatch):
    monkeypatch.setenv("FAKE_SSH_DOWN", "1")
    evaluator = passed()
    evaluator._verdict = (float("inf"), evaluator._verified, (True, "cached"))
    outcome = run_with(fake_machine, "ok", evaluator)
    assert outcome.failure_code == "system_error" and "Connection refused" in outcome.log
    # The next submission waits until the machine passes every check again.
    assert evaluator._verified is None and evaluator._verdict is None


def test_checks_run_by_hand_print_each_reason(monkeypatch, capsys, tmp_path, gpu_zero):
    ready_machine(monkeypatch, tmp_path)
    scripted(monkeypatch, (0, "os=Linux\nnvidia=missing\ndocker=27.3.1\ntoolkit=missing\n", ""), (0, PROJECT_OK, ""))
    assert remote.main() == 1
    printed = capsys.readouterr().out
    assert "[취소 사유] nvidia_driver" in printed and "[취소 사유] nvidia_toolkit" in printed and "[OK] docker" in printed
    assert "연결을 취소했습니다. 사유:" in printed


def test_settings_are_checked_before_any_connection(monkeypatch, tmp_path, gpu_zero):
    ready_machine(monkeypatch, tmp_path)
    monkeypatch.setattr(local, "GPUS", "")
    monkeypatch.setattr(local, "INPUT_HOST_DIR", "")
    sent = scripted(monkeypatch)  # any ssh call would fail the test
    checks, _ = remote.examine(load_target())
    assert {c.name for c in checks} == {"gpu_selection", "input"} and sent == []


def test_ready_checks_again_at_once_when_the_settings_change(monkeypatch, tmp_path, gpu_zero):
    ready_machine(monkeypatch, tmp_path)
    seen = []

    def fake(target, gpu_container=True):
        seen.append((target.host, gpu_container))
        return [Check("os", True)], [["0", "Tesla P100-PCIE-16GB", "535.183.01", "16384 MiB"]]

    monkeypatch.setattr(remote, "preflight", fake)
    evaluator = RemoteEvaluator()
    assert evaluator.ready()[0] and evaluator.ready()[0]
    monkeypatch.setenv("EVAL_SSH_HOST", "100.64.0.11")
    assert evaluator.ready()[0]
    assert seen == [("100.64.0.10", True), ("100.64.0.11", True)]  # cached for the same machine only
    assert evaluator._verified.host == "100.64.0.11"


def test_a_kill_that_cannot_reach_docker_still_ends_as_a_timeout(monkeypatch):
    class Unreachable(local.DockerEvaluator):
        def _wrap(self, command, guard=False):
            return command if guard else ["no-such-command-for-this-test"]

    sleeper = [sys.executable, "-c", "import time; time.sleep(3)"]
    code, _, stopped_for, _ = Unreachable()._watch("admin-eval-1", sleeper, 0.5, lambda: None)
    assert stopped_for == "timeout"


# --- EVAL_GPU_PICK=free: one nearly empty GPU per run ---

@pytest.mark.parametrize("pick, gpus, slots, words", [
    ("sometimes", "0", 1, "fixed 또는 free"),
    ("free", "", 1, "고를 GPU가 없습니다"),
    ("fixed", "0", 3, "모든 슬롯이 같은 GPU(0)"),
])
def test_gpu_settings_that_cannot_work_are_refused(monkeypatch, pick, gpus, slots, words):
    monkeypatch.setattr(local, "GPU_PICK", pick)
    monkeypatch.setattr(local, "GPUS", gpus)
    monkeypatch.setattr(local, "WORKER_SLOTS", slots)
    assert words in local.gpu_problem(pick=True)


def test_only_evaluators_on_a_gpu_machine_pick_gpus(monkeypatch):
    monkeypatch.setattr(local, "GPU_PICK", "free")
    monkeypatch.setattr(local, "GPUS", "all")
    monkeypatch.setattr(local, "WORKER_SLOTS", 5)
    assert "remote와 sandbox" in local.gpu_problem()  # the local docker evaluator
    assert local.gpu_problem(pick=True) is None
    assert RemoteEvaluator().picks_gpus and not local.DockerEvaluator().picks_gpus


# Two rounds of the load script on the shared CNU machine.
LOAD = """\
gpu=0, 260, 0
gpu=1, 15708, 0
gpu=3, 968, 0
gpu=6, 8, 0
gpu=7, 4520, 77
gpu=0, 300, 3
gpu=1, 15708, 0
gpu=3, 968, 45
gpu=4, [N/A], 0
gpu=6, 8, 0
gpu=7, 4520, 80
"""


def test_the_emptiest_gpu_that_stayed_free_comes_first(monkeypatch):
    monkeypatch.setattr(local, "GPUS", "all")
    load = remote.gpu_load(LOAD)
    assert load["0"] == (300, 3) and load["3"] == (968, 45) and load["4"][0] == float("inf")
    # 1 and 7 are someone else's, 3 was busy for a moment, 4 cannot be read.
    assert remote.usable_gpus(load) == ["6", "0"]
    assert remote.usable_gpus(load, held={"6"}) == ["0"]
    monkeypatch.setattr(local, "GPUS", "1,3,0")
    assert remote.usable_gpus(remote.gpu_load(LOAD)) == ["0"]


def test_the_queue_waits_while_no_gpu_is_free_and_says_why(monkeypatch, gpu_zero):
    monkeypatch.setattr(local, "GPU_PICK", "free")
    monkeypatch.setattr(local, "GPUS", "all")
    sent = scripted(monkeypatch, (0, "gpu=0, 15708, 0\ngpu=1, 300, 95\ngpu=2, 10, 0\n", ""),
                    (0, "gpu=0, 15708, 0\ngpu=1, 10, 0\ngpu=2, 10, 0\n", ""),
                    (0, "nvidia_error=NVIDIA-SMI has failed\n", ""))
    evaluator = RemoteEvaluator()
    evaluator._verified = TARGET
    assert evaluator.free_gpus(held={"2"}) == []
    note = evaluator.gpu_note
    assert "GPU 0 15708 MiB·0%" in note and "GPU 1 300 MiB·95%" in note and "GPU 2 다른 슬롯이 채점 중" in note
    assert "nvidia-smi --query-gpu=index,memory.used,utilization.gpu" in sent[0]
    assert evaluator.free_gpus() == [] and len(sent) == 1  # not asked again at once
    evaluator._gpu_asked_at -= remote.GPU_RECHECK_SECONDS
    assert evaluator.free_gpus(held={"2"}) == ["1"] and evaluator.gpu_note is None
    assert evaluator.free_gpus() == [] and "NVIDIA-SMI has failed" in evaluator.gpu_note  # asked at once after a hit


def test_a_run_gets_only_the_gpu_it_was_handed(monkeypatch, tmp_path):
    monkeypatch.setattr(local, "WORK_DIR", tmp_path)
    monkeypatch.setattr(local, "WORK_HOST_DIR", tmp_path)
    monkeypatch.setattr(local, "GPUS", "all")
    evaluator = RemoteEvaluator()
    evaluator._gpu = "3"
    run = evaluator._inference_command("admin-eval-1", tmp_path / "s" / "submission", tmp_path / "s" / "output", None)
    assert run[run.index("--gpus") + 1] == '"device=3"'
    evaluator._gpu = None
    run = evaluator._inference_command("admin-eval-1", tmp_path / "s" / "submission", tmp_path / "s" / "output", None)
    assert run[run.index("--gpus") + 1] == "all"


def test_a_picked_gpu_is_used_and_logged(fake_machine, monkeypatch):
    monkeypatch.setattr(local, "GPU_PICK", "free")
    monkeypatch.setattr(local, "GPUS", "all")
    path = fake_machine.tmp / "code.zip"
    path.write_bytes(make_zip(extra={"behave.txt": "ok"}))
    outcome = passed().run(types.SimpleNamespace(id=7, gpu="3"), path, lambda: None)
    assert outcome.ok and outcome.log.startswith("ran on GPU 3 (EVAL_GPU_PICK=free)")
    inference = next(line for line in fake_machine.log.read_text().splitlines() if line.startswith("docker run") and "/output" in line)
    assert '--gpus "device=3"' in inference
    # A run the worker handed no GPU must not fall back to all of them.
    assert passed().run(types.SimpleNamespace(id=8, gpu=None), path, lambda: None).failure_code == "system_error"
