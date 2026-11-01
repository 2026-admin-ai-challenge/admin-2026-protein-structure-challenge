import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import types

import pytest

from app import evaluators
from app.evaluators import docker as local
from app.evaluators import remote as remote_module
from app.evaluators import sandbox
from app.evaluators import sandbox_launch as launch
from app.evaluators.remote import load_target
from app.evaluators.sandbox import SandboxEvaluator
from conftest import make_zip
from test_remote import FAKE_SSH, env, failed, ready_machine, scripted

ROOT = "/home/evaluator/admin-eval"
RUN = f"{ROOT}/work/submission-7-abcd1234"
PROBE_OK = 'probe={"ssh_visible": false, "input": true, "network": "blocked", "torch": "2.14.1+cu126", "cuda": true, "gpus": 1, "computed": true}\n'


def check_output(**changes):
    """What the check script prints on a ready machine; a value of None drops that line."""
    lines = {"os": "Linux", "gpu": "0, Tesla P100-PCIE-16GB, 535.183.01, 16384 MiB", "bwrap": "0.6.1", "userns": "ok",
             "cgroup": "cpu memory pids", "version_installer": "1", "version_lock": "abcdef0123456789",
             "version_torch_index": "https://download.pytorch.org/whl/cu126", "python": "3.12.14", "work": "ok", "free_kb": "104857600"}
    lines.update(changes)
    return "".join(f"{key}={value}\n" for key, value in lines.items() if value is not None)


def probe(**changes):
    return "probe=" + json.dumps({**json.loads(PROBE_OK[len("probe="):]), **changes}) + "\n"


@pytest.fixture
def configured(monkeypatch, tmp_path):
    ready_machine(monkeypatch, tmp_path)
    monkeypatch.setattr(sandbox, "ROOT", ROOT)
    monkeypatch.setattr(sandbox, "LIMITS", "cgroup")
    monkeypatch.setattr(local, "GPUS", "0")
    monkeypatch.setattr(local, "MEMORY", "8g")
    monkeypatch.setattr(local, "CPUS", "4")
    monkeypatch.setattr(local, "INPUT_HOST_DIR", f"{ROOT}/input")
    monkeypatch.setattr(local, "WORK_HOST_DIR", local.Path(f"{ROOT}/work"))


def test_sandbox_is_a_fourth_evaluator(monkeypatch):
    monkeypatch.setattr(evaluators, "EVALUATOR", "sandbox")
    assert isinstance(evaluators.get_evaluator(), SandboxEvaluator)
    assert len(SandboxEvaluator.name) <= 12  # submissions.evaluator is String(12)


# --- the checks ------------------------------------------------------------------------

def test_a_ready_machine_passes_every_check_and_proves_a_real_sandbox(monkeypatch, configured):
    sent = scripted(monkeypatch, (0, check_output(), ""), (0, PROBE_OK, ""))
    checks, facts = sandbox.examine(load_target())
    assert not failed(checks)
    assert {"os", "nvidia_driver", "gpu_selection", "bwrap", "limits", "environment", "input", "work_dir", "disk", "sandbox"} <= {c.name for c in checks}
    assert facts["python"] == "3.12.14" and facts["lock"] == "abcdef0123456789"
    script = shlex.split(sent[0])[2]
    assert f"ROOT={ROOT}\n" in script and "LIMITS=cgroup\n" in script and "GPUS=0\n" in script
    probe_script = shlex.split(sent[1])[2]
    assert "submission-probe-" in probe_script and sandbox.MARKER in probe_script and '"mode": "probe"' in probe_script


def test_settings_need_the_root_but_not_a_gpu(monkeypatch, configured):
    monkeypatch.setattr(local, "GPUS", "")
    monkeypatch.setattr(sandbox, "ROOT", "")
    sent = scripted(monkeypatch)  # any ssh call would fail the test
    assert set(failed(sandbox.examine(load_target())[0])) == {"sandbox_root"} and sent == []
    monkeypatch.setattr(sandbox, "ROOT", ROOT)
    monkeypatch.setattr(sandbox, "LIMITS", "maybe")
    assert set(failed(sandbox.examine(load_target())[0])) == {"limits"}
    monkeypatch.setattr(sandbox, "LIMITS", "cgroup")
    monkeypatch.setattr(local, "MEMORY", "lots")
    assert "EVAL_MEMORY" in failed(sandbox.examine(load_target())[0])["limits"].reason


def test_a_cpu_only_sandbox_asks_nothing_of_nvidia(monkeypatch, configured):
    monkeypatch.setattr(local, "GPUS", "")
    scripted(monkeypatch, (0, check_output(gpu=None), ""), (0, probe(cuda=False, computed=None), ""))
    checks, _ = sandbox.examine(load_target())
    assert not failed(checks) and "nvidia_driver" not in {c.name for c in checks}


@pytest.mark.parametrize("changes, name, reason, fix", [
    ({"bwrap": "missing", "userns": None}, "bwrap", "bubblewrap", "apt install bubblewrap"),
    ({"userns": None, "userns_error": "bwrap: setting up uid map: Permission denied"}, "userns", "uid map", "apparmor_restrict"),
    ({"cgroup": None, "cgroup_error": "Failed to connect to bus: No medium found"}, "limits", "No medium found", "enable-linger evaluator"),
    ({"cgroup": "cpu"}, "limits", "memory·pids", "Delegate=memory"),
    ({"version_installer": None, "version_lock": None, "version_torch_index": None, "version": "missing"}, "environment", "VERSION", "setup-server.sh"),
    ({"version_installer": "0"}, "environment", "낡았습니다", "다시 실행"),
    ({"python": "missing", "wheels": "missing"}, "environment", "env/bin/python, wheels/", "setup-server.sh"),
    ({"python": "error while loading shared libraries"}, "environment", "실행되지 않습니다", "setup-server.sh"),
])
def test_each_missing_piece_is_named_with_its_fix_and_no_sandbox_is_tried(monkeypatch, configured, changes, name, reason, fix):
    scripted(monkeypatch, (0, check_output(**changes), ""))  # a probe would need a second answer
    problems = failed(sandbox.examine(load_target())[0])
    assert list(problems) == [name] and reason in problems[name].reason and fix in problems[name].fix


def test_a_docker_container_that_forbids_namespaces_says_what_to_ask_its_admin(monkeypatch, configured):
    # What the CNU GPU server printed on 2026-10-28: a container without bwrap, user namespaces or systemd.
    scripted(monkeypatch, (0, check_output(container="docker", bwrap="missing", userns=None, cgroup=None,
                                           userns_error="unshare: unshare failed: Operation not permitted",
                                           cgroup_error="systemd-run: command not found"), ""))
    problems = failed(sandbox.examine(load_target())[0])
    assert list(problems) == ["bwrap", "userns", "limits"]
    assert "Operation not permitted" in problems["userns"].reason and "seccomp=unconfined" in problems["userns"].fix
    assert "EVAL_SANDBOX_LIMITS=none" in problems["limits"].fix and "loginctl" not in problems["limits"].fix


CNU_CONTAINER = dict(uid="0", container="docker", bwrap="missing", userns=None, cgroup=None,
                     userns_error="unshare: unshare failed: Operation not permitted", cgroup_error="systemd-run: command not found")


def test_without_isolation_that_container_passes_and_the_probe_asks_only_for_input_and_gpu(monkeypatch, configured):
    sent = scripted(monkeypatch, (0, check_output(**CNU_CONTAINER), ""), (0, probe(network="open", ssh_visible=True), ""))
    checks, facts = sandbox.examine(load_target(), isolation=False)
    assert not failed(checks) and not {"bwrap", "userns", "limits"} & {c.name for c in checks} and facts["root"]
    step = json.loads(_probe_spec(sent[1]))
    assert step["isolation"] is False and step["run_uid"] == sandbox.RUN_UID and step["limits"] is None


def _probe_spec(command):
    """The spec JSON inside a probe's remote command."""
    script = shlex.split(command)[2]
    return next(part for part in shlex.split(script.split("; c=$?")[0].split("&& ", 1)[1]) if part.startswith('{"mode"'))


def test_without_isolation_the_input_and_gpu_are_still_proved(configured):
    problems = failed(sandbox.probe_checks(0, probe(network="open", input=False, cuda=False, computed=None), "", isolation=False))
    assert set(problems) == {"sandbox_input", "sandbox_gpu"} and "uid 64000" in problems["sandbox_input"].fix
    assert "격리 없음" in problems["sandbox_gpu"].reason


def test_turning_isolation_off_checks_the_machine_again_and_says_so(monkeypatch, configured):
    sent = scripted(monkeypatch, (0, check_output(), ""), (0, PROBE_OK, ""))
    evaluator = SandboxEvaluator()
    assert evaluator.ready()[0] and len(sent) == 2
    evaluator.configure(types.SimpleNamespace(eval_isolation=True))  # unchanged: the verdict stays
    assert evaluator.ready()[0] and len(sent) == 2
    scripted(monkeypatch, (0, check_output(**CNU_CONTAINER), ""), (0, probe(network="open"), ""))
    evaluator.configure(types.SimpleNamespace(eval_isolation=False))
    assert evaluator._verified is None
    ok, detail = evaluator.ready()
    assert ok and f"격리 꺼짐(네트워크·파일 접근 제한 없음, uid {sandbox.RUN_UID}로 실행" in detail
    evaluator._run_dir = RUN
    infer = json.loads(evaluator._inference_command("admin-eval-7-abcd1234", None, None, None)[-1])
    assert infer["isolation"] is False and infer["limits"] is None and infer["tasks"] == int(local.PIDS)


def test_the_inference_step_gets_the_gpu_the_run_was_handed(monkeypatch):
    monkeypatch.setattr(local, "GPUS", "all")
    evaluator = SandboxEvaluator()
    evaluator._run_dir, evaluator._gpu = RUN, "3"
    assert json.loads(evaluator._inference_command("admin-eval-7-abcd1234", None, None, None)[-1])["gpus"] == "3"
    evaluator._gpu = None
    assert json.loads(evaluator._inference_command("admin-eval-7-abcd1234", None, None, None)[-1])["gpus"] == "all"


def test_a_worker_slot_runs_its_probe_and_steps_as_its_own_user(monkeypatch, configured):
    # Slots are threads of one process (app.worker), and every step ends by killing its user's processes.
    sent = scripted(monkeypatch, (0, check_output(**CNU_CONTAINER), ""), (0, probe(network="open"), ""))
    evaluator = SandboxEvaluator()
    evaluator.configure(types.SimpleNamespace(eval_isolation=False))
    evaluator.run_uid = 64002
    ok, detail = evaluator.ready()
    assert ok and "uid 64002로 실행" in detail and json.loads(_probe_spec(sent[1]))["run_uid"] == 64002
    evaluator._run_dir = RUN
    install = json.loads(evaluator._install_command("admin-eval-7-abcd1234", None, ["numpy"], False, 60)[-1])
    infer = json.loads(evaluator._inference_command("admin-eval-7-abcd1234", None, None, None)[-1])
    assert install["run_uid"] == infer["run_uid"] == 64002
    cleanups = []
    monkeypatch.setattr(evaluator, "_remote", cleanups.append)
    evaluator._unstage(local.WORK_DIR / "submission-7-abcd1234")
    assert "pkill -KILL -U 64002 " in cleanups[0]


@pytest.mark.parametrize("load, gpus", [
    ("gpu=0, 15708, 97\ngpu=1, 4520, 77\ngpu=2, 6, 0\ngpu=0, 15710, 99\n", "2"),
    ("nvidia_error=Failed to initialize NVML: Driver/library version mismatch\n", "all"),
])
def test_with_gpu_picking_the_probe_computes_on_the_emptiest_gpu(monkeypatch, configured, load, gpus):
    # With all GPUs visible CUDA takes GPU 0, which another user may have filled.
    monkeypatch.setattr(local, "GPUS", "all")
    monkeypatch.setattr(local, "GPU_PICK", "free")
    sent = scripted(monkeypatch, (0, check_output(), ""), (0, load, ""), (0, PROBE_OK, ""))
    checks, _ = sandbox.examine(load_target())
    assert not failed(checks) and "nvidia-smi --query-gpu=index,memory.used" in sent[1]
    assert json.loads(_probe_spec(sent[2]))["gpus"] == gpus


def test_the_message_says_which_reasons_turning_isolation_off_would_skip(monkeypatch, configured):
    scripted(monkeypatch, (0, check_output(**CNU_CONTAINER, version="missing"), ""))
    evaluator = SandboxEvaluator()
    ok, detail = evaluator.ready()
    assert not ok and "4) 채점 환경이 없습니다" in detail
    assert detail.splitlines()[-1].startswith("격리 없이 채점하려면 관리자 페이지의 '채점 격리'에서 격리를 끄세요. 그러면 1, 2, 3번은")
    scripted(monkeypatch, (0, check_output(**CNU_CONTAINER, version="missing"), ""))
    evaluator.configure(types.SimpleNamespace(eval_isolation=False))
    ok, detail = evaluator.ready()
    assert not ok and "1) 채점 환경이 없습니다" in detail and "채점 격리" not in detail


def test_limits_can_be_turned_off(monkeypatch, configured):
    monkeypatch.setattr(sandbox, "LIMITS", "none")
    scripted(monkeypatch, (0, check_output(cgroup=None), ""), (0, PROBE_OK, ""))
    checks, _ = sandbox.examine(load_target())
    assert not failed(checks) and "limits" not in {c.name for c in checks}
    assert sandbox.limits() is None


@pytest.mark.parametrize("answer, name, words", [
    ((125, "", "bwrap: setting up uid map: Permission denied\nsandbox: the sandbox did not start"), "sandbox", "uid map"),
    ((137, "", ""), "sandbox", "60초"),
    ((1, "", "Traceback (most recent call last):"), "sandbox", "실패했습니다"),
    ((0, probe(network="open"), ""), "sandbox_network", "네트워크"),
    ((0, probe(ssh_visible=True), ""), "sandbox_files", "~/.ssh"),
    ((0, probe(input=False), ""), "sandbox_input", "평가 입력"),
    ((0, probe(cuda=False, computed=None), ""), "sandbox_gpu", "CUDA를 쓸 수 없음"),
    ((0, probe(error="RuntimeError: CUDA error: no kernel image is available"), ""), "sandbox_gpu", "no kernel image"),
])
def test_a_probe_that_fails_cancels_the_connection(configured, answer, name, words):
    problems = failed(sandbox.probe_checks(*answer))
    assert list(problems) == [name] and words in problems[name].reason


def test_ready_names_the_environment_and_proves_the_sandbox_only_now_and_then(monkeypatch, configured):
    scripted(monkeypatch, (0, check_output(), ""), (0, PROBE_OK, ""))
    evaluator = SandboxEvaluator()
    ok, detail = evaluator.ready()
    assert ok and detail.startswith("sandbox evaluator: evaluator@100.64.0.10:2222, GPU 0 Tesla P100-PCIE-16GB")
    assert "Python 3.12.14" in detail and "lock abcdef012345" in detail and "4 cpus, 8g memory" in detail
    evaluator.shared.verdicts.clear()  # as if the cache ran out
    scripted(monkeypatch, (0, check_output(), ""))  # no second probe within GPU_CONTAINER_CACHE_SECONDS
    assert evaluator.ready()[0]


# --- the sandbox's command line ----------------------------------------------------------

MERGED_USR = {"/bin": ("link", "usr/bin"), "/sbin": ("link", "usr/sbin"), "/lib": ("link", "usr/lib"), "/lib64": ("link", "usr/lib64")}
TWO = {"--ro-bind", "--bind", "--dev-bind", "--ro-bind-try", "--dev-bind-try", "--symlink"}
ONE = {"--proc", "--dev", "--tmpfs", "--chdir", "--cap-drop"}


def merged(path):
    return MERGED_USR.get(path, (None, None))


def step(mode, **extra):
    return {"mode": mode, "root": ROOT, "run": RUN, "input": f"{ROOT}/input", "gpus": "0", "seconds": 615,
            "pidfile": None, "limits": None, **extra}


def parse(argv):
    """(mounts {sandbox path: (option, host path)}, flags, command, environment) of a planned step."""
    bwrap = argv.index("bwrap")
    environment = dict(item.split("=", 1) for item in argv[argv.index("-i") + 1:bwrap])
    i, mounts, flags = bwrap + 1, {}, {}
    while argv[i].startswith("--"):
        if argv[i] in TWO:
            mounts[argv[i + 2]] = (argv[i], argv[i + 1])
            i += 3
        elif argv[i] in ONE:
            if argv[i] in ("--chdir", "--cap-drop"):
                flags[argv[i]] = argv[i + 1]
            else:
                mounts[argv[i + 1]] = (argv[i], None)
            i += 2
        else:
            flags[argv[i]] = True
            i += 1
    return mounts, flags, argv[i:], environment


def test_inference_sees_its_own_directories_and_the_gpu_but_no_network():
    argv = launch.plan(step("infer", command=["python", "inference.py"], deps=True), "/usr", merged,
                       devices=["/dev/nvidia0", "/dev/nvidiactl", "/dev/nvidia-uvm"])
    mounts, flags, command, environment = parse(argv)
    assert argv[:2] == ["env", "-i"]  # nothing of the launcher's own environment
    assert {"--die-with-parent", "--new-session", "--unshare-all"} <= set(flags) and flags["--cap-drop"] == "ALL"
    assert "--share-net" not in flags and "/etc/resolv.conf" not in mounts
    assert mounts["/submission"] == ("--ro-bind", f"{RUN}/submission") and mounts["/input"] == ("--ro-bind", f"{ROOT}/input")
    assert mounts["/output"] == ("--bind", f"{RUN}/output") and mounts["/deps"] == ("--ro-bind", f"{RUN}/deps")
    assert mounts[f"{ROOT}/env"] == ("--ro-bind", f"{ROOT}/env") and mounts["/bin"] == ("--symlink", "usr/bin")
    assert mounts["/dev/nvidia0"][0] == "--dev-bind-try" and mounts["/tmp"] == ("--tmpfs", None)
    # Nothing else of the scoring directories: no wheels, no other runs, no home directory.
    shown = {source for _, source in mounts.values() if source and source.startswith("/home")}
    assert shown == {f"{ROOT}/env", f"{RUN}/submission", f"{RUN}/output", f"{RUN}/deps", f"{ROOT}/input"}
    assert environment["CUDA_VISIBLE_DEVICES"] == "0" and environment["CUDA_DEVICE_ORDER"] == "PCI_BUS_ID"
    assert environment["PATH"].startswith(f"/deps/venv/bin:{ROOT}/env/bin:") and environment["HOME"] == "/tmp"
    assert flags["--chdir"] == "/submission" and command[:2] == ["/bin/sh", "-c"] and command[4:] == ["python", "inference.py"]


def test_the_private_tmp_comes_before_every_bind():
    argv = launch.plan(step("infer", command=["python"]), "/usr", merged)
    assert argv.index("--tmpfs") < argv.index(f"{ROOT}/env")


def test_a_cpu_only_sandbox_gets_no_nvidia_device():
    mounts, _, _, environment = parse(launch.plan(step("infer", gpus="", command=["python"]), "/usr", merged, devices=["/dev/nvidia0"]))
    assert "/dev/nvidia0" not in mounts and "/sys" not in mounts and "CUDA_VISIBLE_DEVICES" not in environment


@pytest.mark.parametrize("mode", ["install-offline", "install-online"])
def test_the_install_never_sees_the_submission_the_input_or_the_gpu(mode):
    argv = launch.plan(step(mode, requirements=["lightgbm==4.7.0"], torch_index="https://example.org/cu126", pip_cache=True),
                       "/usr", merged, devices=["/dev/nvidia0"])
    mounts, flags, command, environment = parse(argv)
    assert not {"/submission", "/input", "/output", "/dev/nvidia0", "/sys"} & set(mounts)
    assert mounts["/deps"] == ("--bind", f"{RUN}/deps") and mounts[f"{ROOT}/wheels"][0] == "--ro-bind"
    online = mode == "install-online"
    assert command[4:] == [f"{ROOT}/env/bin/python", f"{ROOT}/eval/install_packages.py", "online" if online else "offline",
                           "/deps/venv", "lightgbm==4.7.0"]
    assert environment["ADMIN_EVAL_TORCH_INDEX"] == "https://example.org/cu126" and environment["ADMIN_EVAL_WHEELS"] == f"{ROOT}/wheels"
    # Only the online pass reaches the network, and only it shares the pip cache.
    assert ("--share-net" in flags) == online and ("/etc/resolv.conf" in mounts) == online
    assert ("/pip-cache" in mounts) == online and ("PIP_NO_CACHE_DIR" in environment) == (not online)


def test_limits_put_the_sandbox_in_a_user_scope():
    argv = launch.plan(step("infer", command=["python"], limits={"memory": "8G", "cpu_percent": 400, "tasks": 256}), "/usr", merged)
    assert argv[:4] == ["systemd-run", "--user", "--scope", "--quiet"]
    assert {"MemoryMax=8G", "MemorySwapMax=0", "CPUQuota=400%", "TasksMax=256"} <= set(argv)
    assert argv.index("env") > argv.index("--")  # the scope's own environment never reaches the sandbox


def direct(argv):
    """(environment, command) of a step planned without isolation."""
    shell = argv.index("/bin/sh")
    return dict(item.split("=", 1) for item in argv[2:shell]), argv[shell + 4:]


def test_without_isolation_the_step_runs_directly_on_the_run_directory():
    command = ["python", "inference.py", "--input", "/input/test_features.csv", "--output=/output/predictions.csv", "/inputs"]
    argv, workdir = launch.plan_direct(step("infer", isolation=False, command=command, deps=True), home="/root")
    assert argv[:2] == ["env", "-i"] and "bwrap" not in argv and "systemd-run" not in argv
    environment, command = direct(argv)
    assert command == ["python", "inference.py", "--input", f"{ROOT}/input/test_features.csv",
                       f"--output={RUN}/output/predictions.csv", "/inputs"]
    assert workdir == f"{RUN}/submission" and environment["HOME"] == f"{RUN}/tmp" and environment["USER"] == launch.RUN_USER
    assert environment["PATH"].startswith(f"{RUN}/deps/venv/bin:{ROOT}/env/bin:") and environment["VIRTUAL_ENV"] == f"{RUN}/deps/venv"
    assert environment["CUDA_VISIBLE_DEVICES"] == "0"
    cpu_only, _ = direct(launch.plan_direct(step("infer", gpus="", isolation=False, command=["python"]))[0])
    assert cpu_only["CUDA_VISIBLE_DEVICES"] == ""  # every GPU of the machine would be visible otherwise


def test_without_isolation_the_install_uses_no_shared_cache():
    argv, workdir = launch.plan_direct(step("install-online", isolation=False, requirements=["lightgbm==4.7.0"]))
    environment, command = direct(argv)
    assert command == [f"{ROOT}/env/bin/python", f"{ROOT}/eval/install_packages.py", "online", f"{RUN}/deps/venv", "lightgbm==4.7.0"]
    assert environment["PIP_NO_CACHE_DIR"] == "1" and "PIP_CACHE_DIR" not in environment and workdir == f"{RUN}/tmp"


@pytest.mark.parametrize("mode, wrapped", [("infer", True), ("probe", True), ("install-offline", True), ("install-online", False)])
def test_with_netns_every_step_but_the_online_install_starts_without_network(mode, wrapped):
    extra = {"command": ["python"]} if mode in ("infer", "probe") else {"requirements": ["lightgbm==4.7.0"]}
    argv, _ = launch.plan_direct(step(mode, isolation=False, netns=True, **extra))
    assert (argv[:3] == ["unshare", "--user", "--net"]) == wrapped
    assert argv[3 if wrapped else 0:][:2] == ["env", "-i"]
    plain, _ = launch.plan_direct(step(mode, isolation=False, **extra))
    assert plain[:2] == ["env", "-i"]  # without EVAL_SANDBOX_NETNS nothing changes


def test_netns_is_sent_only_without_isolation(monkeypatch, configured):
    monkeypatch.setattr(sandbox, "NETNS", True)
    assert sandbox.spec("infer", RUN, 10, isolation=False)["netns"] is True
    assert "netns" not in sandbox.spec("infer", RUN, 10)
    monkeypatch.setattr(sandbox, "NETNS", False)
    assert sandbox.spec("infer", RUN, 10, isolation=False)["netns"] is False


def test_with_netns_the_probe_must_find_no_network_again(monkeypatch, configured):
    monkeypatch.setattr(sandbox, "NETNS", True)
    problems = failed(sandbox.probe_checks(0, probe(network="open"), "", isolation=False))
    assert set(problems) == {"sandbox_network"} and "EVAL_SANDBOX_NETNS" in problems["sandbox_network"].reason
    assert not failed(sandbox.probe_checks(0, probe(network="blocked"), "", isolation=False))
    # A machine that forbids user namespaces: the step never starts, so nothing is scored with the network open.
    fault = failed(sandbox.probe_checks(125, "", "unshare: unshare failed: Operation not permitted\n", isolation=False))
    assert set(fault) == {"sandbox"} and "unshare --user --net" in fault["sandbox"].fix


def test_with_netns_the_worker_says_the_network_is_blocked(monkeypatch, configured):
    monkeypatch.setattr(sandbox, "NETNS", True)
    sent = scripted(monkeypatch, (0, check_output(**CNU_CONTAINER), ""), (0, probe(network="blocked"), ""))
    evaluator = SandboxEvaluator()
    evaluator.configure(types.SimpleNamespace(eval_isolation=False))
    ok, detail = evaluator.ready()
    assert ok and "격리 꺼짐(네트워크 차단(온라인 설치 제외), 파일 접근 제한 없음" in detail
    assert json.loads(_probe_spec(sent[1]))["netns"] is True


def test_the_probe_tries_more_than_one_address():
    # The CNU container refused 1.1.1.1 on every port while the rest of the internet was open.
    assert all(f'("{host}", {port})' in sandbox.PROBE for host, port in (("1.1.1.1", 53), ("8.8.8.8", 443), ("9.9.9.9", 443)))


def test_docker_style_limits_become_systemd_ones(monkeypatch, configured):
    monkeypatch.setattr(local, "CPUS", "1.5")
    monkeypatch.setattr(local, "PIDS", "256")
    assert sandbox.limits() == {"memory": "8G", "cpu_percent": 150, "tasks": 256}
    assert sandbox.systemd_size("512m") == "512M" and sandbox.systemd_size("1073741824") == "1073741824"


def test_top_directories_follow_the_machine():
    machine = {"/bin": ("dir", None), "/lib": ("link", "usr/lib"), "/lib64": ("dir", None)}
    assert launch.system_mounts(lambda path: machine.get(path, (None, None))) == [
        "--ro-bind", "/usr", "/usr", "--ro-bind", "/bin", "/bin", "--symlink", "usr/lib", "/lib", "--ro-bind", "/lib64", "/lib64"]


@pytest.mark.parametrize("changes, prefix, words", [
    ({}, "/home/evaluator", "holds"),                 # the Python's prefix is the home directory
    ({}, "/home/evaluator/admin-eval", "holds"),      # or holds the scoring directories
    ({}, "/", "holds"),
    ({"input": "/usr/share/admin-input"}, "/usr", "inside /usr"),
    ({"run": "work/submission-7"}, "/usr", "absolute"),
    ({"run": f"{ROOT}/work/../env"}, "/usr", "normalised"),
])
def test_places_that_would_show_too_much_are_refused(changes, prefix, words):
    assert words in launch.unsafe({**step("infer"), **changes}, prefix, "/home/evaluator")


def test_a_python_of_its_own_is_shown_read_only():
    assert launch.unsafe(step("infer"), "/usr", "/home/evaluator") is None
    assert launch.unsafe(step("infer"), "/home/evaluator/.local/share/uv/python/cpython-3.12.14", "/home/evaluator") is None
    mounts = parse(launch.plan(step("infer", command=["python"]), "/opt/python3.12", merged))[0]
    assert mounts["/opt/python3.12"] == ("--ro-bind", "/opt/python3.12")


def test_each_step_is_sent_with_the_launcher_its_pid_file_and_its_timer(configured):
    evaluator = SandboxEvaluator()
    evaluator._run_dir = RUN
    command = evaluator._install_command("admin-eval-7-abcd1234-install-offline", "v", ["numpy"], False, 600)
    assert command[:2] == ["sh", "-c"] and command[4] == f"{ROOT}/env/bin/python"
    assert command[5] == sandbox.LAUNCHER and sandbox.MARKER in sandbox.LAUNCHER
    install = json.loads(command[6])
    assert install["mode"] == "install-offline" and install["requirements"] == ["numpy"]
    assert install["seconds"] == 600 + local.KILL_GRACE_SECONDS and install["pidfile"] == f"{RUN}/admin-eval-7-abcd1234-install-offline.pid"
    infer = json.loads(evaluator._inference_command("admin-eval-7-abcd1234", None, None, "v")[-1])
    assert infer["deps"] and infer["command"][:2] == ["python", "inference.py"] and infer["gpus"] == "0"
    assert infer["limits"] == {"memory": "8G", "cpu_percent": 400, "tasks": int(local.PIDS)}
    assert infer["seconds"] == local.INFERENCE_TIMEOUT_SECONDS + local.KILL_GRACE_SECONDS
    assert not json.loads(evaluator._inference_command("admin-eval-7-abcd1234", None, None, None)[-1])["deps"]
    assert evaluator._kill_command("admin-eval-7-abcd1234")[-1] == f"{RUN}/admin-eval-7-abcd1234.pid"


# --- the launcher and whole runs, with a fake ssh and a fake bwrap (or a real one) --------

FAKE_BWRAP = """\
#!/usr/bin/env python3
# Stands in for bwrap: reads its options, then runs the command with every sandbox path
# replaced by the host path bound there. No namespaces: only the plumbing is tested.
import os, sys
here = os.path.dirname(os.path.realpath(__file__))
args = sys.argv[1:]
with open(os.path.join(here, "bwrap.log"), "a") as log:
    log.write(" ".join(args) + "\\n")
if os.path.exists(os.path.join(here, "bwrap-fails")):
    sys.stderr.write("bwrap: setting up uid map: Permission denied\\n")
    sys.exit(1)
TWO = {"--ro-bind", "--bind", "--dev-bind", "--ro-bind-try", "--dev-bind-try", "--symlink"}
ONE = {"--proc", "--dev", "--tmpfs", "--chdir", "--cap-drop"}
FLAGS = {"--die-with-parent", "--new-session", "--unshare-all", "--share-net"}
binds, i, workdir = [], 0, "/"
while args[i].startswith("--"):
    if args[i] in TWO:
        if args[i] != "--symlink":
            binds.append((args[i + 2], args[i + 1]))
        i += 3
    elif args[i] in ONE:
        workdir = args[i + 1] if args[i] == "--chdir" else workdir
        i += 2
    elif args[i] in FLAGS:
        i += 1
    else:
        sys.stderr.write("bwrap: Unknown option " + args[i] + "\\n")
        sys.exit(1)

def host(path):
    for inside, outside in sorted(binds, key=lambda pair: -len(pair[0])):
        if path == inside or path.startswith(inside + "/"):
            return outside + path[len(inside):]
    return path

command = [host(arg) for arg in args[i:]]
os.chdir(host(workdir))
os.execvp(command[0], command)
"""

# Stands in for install_packages.py: records what it was asked for.
FAKE_INSTALLER = """\
import os, sys
os.makedirs(sys.argv[2], exist_ok=True)
with open(os.path.join(sys.argv[2], "installed.txt"), "a") as record:
    record.write(" ".join(sys.argv[1:]) + "\\n")
"""

INFERENCE = """\
import os, sys, time
output = sys.argv[sys.argv.index("--output") + 1]
behaviour = open("behave.txt").read().strip()
if behaviour == "ok":
    with open(output, "w") as handle:
        handle.write("id,label\\nTEST_1,1.10\\n")
elif behaviour == "sleep":
    time.sleep(60)
elif behaviour.startswith("flood"):  # flood: and keeps running; flood-exit: and ends at once
    with open(os.path.join(os.path.dirname(output), "flood.bin"), "wb") as handle:
        handle.write(b"x" * 4096)
    if behaviour == "flood":
        time.sleep(60)
elif behaviour == "environment":
    with open(output, "w") as handle:
        handle.write(" ".join(sorted(os.environ)))
elif behaviour == "daemon":
    import subprocess
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "admin-eval-left-behind"])
elif behaviour == "memory":
    hog = bytearray(512 * 1024 * 1024)
    for index in range(0, len(hog), 4096):
        hog[index] = 1
elif behaviour == "cgroup":
    with open(output, "w") as handle, open("/proc/self/cgroup") as cgroup:
        handle.write(cgroup.read())
elif behaviour == "look":
    try:
        open("written.txt", "w").close()
        wrote = "wrote"
    except OSError:
        wrote = "read-only"
    with open(output, "w") as handle:
        handle.write(wrote + " " + " ".join(sorted(os.listdir("/"))))
else:
    sys.exit(int(behaviour))
"""


def _real_bwrap():
    path = shutil.which("bwrap")
    if os.name == "nt" or not path:
        return None
    done = subprocess.run([path, "--unshare-all", "--die-with-parent", "--ro-bind", "/", "/", "true"], capture_output=True)
    return path if done.returncode == 0 else None


REAL_BWRAP = _real_bwrap()


@pytest.fixture
def machine(monkeypatch, tmp_path):
    if os.name == "nt":
        pytest.skip("runs the launcher and fake ssh/bwrap scripts through sh")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, script in {"ssh": FAKE_SSH, "bwrap": FAKE_BWRAP}.items():
        (bin_dir / name).write_text(script)
        (bin_dir / name).chmod(0o755)
    root = tmp_path / "gpu" / "admin-eval"
    (root / "env" / "bin").mkdir(parents=True)
    (root / "env" / "bin" / "python").symlink_to(os.path.realpath(sys.executable))
    (root / "eval").mkdir()
    (root / "eval" / "install_packages.py").write_text(FAKE_INSTALLER)
    (root / "wheels").mkdir()
    (root / "VERSION").write_text("installer=1\nlock=abc\ntorch_index=https://download.pytorch.org/whl/cu126\n")
    work, inputs = root / "work", root / "input"
    work.mkdir()
    inputs.mkdir()
    for name in ("test.csv", "test_features.csv", "test_structures.zip"):
        (inputs / name).write_text("id\nTEST_1\n")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "calls.log"))
    monkeypatch.setattr(sandbox, "ROOT", str(root))
    monkeypatch.setattr(sandbox, "LIMITS", "none")
    monkeypatch.setattr(local, "WORK_DIR", tmp_path / "here")
    monkeypatch.setattr(local, "WORK_HOST_DIR", work)
    monkeypatch.setattr(local, "INPUT_HOST_DIR", str(inputs))
    monkeypatch.setattr(local, "GPUS", "")
    for name, value in env(EVAL_SSH_KEY=str(tmp_path / "key"), EVAL_SSH_KNOWN_HOSTS=str(tmp_path / "known")).items():
        monkeypatch.setenv(name, value)
    return types.SimpleNamespace(tmp=tmp_path, root=root, work=work, bin=bin_dir, sandboxes=bin_dir / "bwrap.log")


def launch_step(machine, behaviour="ok", seconds=30, mode="infer", command=None, isolation=True, **extra):
    """Runs the launcher as the worker would over SSH, on one prepared run directory."""
    run = machine.work / "submission-1-test"
    (run / "submission").mkdir(parents=True, exist_ok=True)
    (run / "output").mkdir(exist_ok=True)
    (run / "submission" / "inference.py").write_text(INFERENCE)
    (run / "submission" / "behave.txt").write_text(behaviour)
    step = sandbox.spec(mode, str(run), seconds, str(run / "step.pid"), isolation, command=command or shlex.split(local.COMMAND), **extra)
    return subprocess.run(sandbox.launch_command(step), capture_output=True, timeout=90), run


def test_without_isolation_a_step_runs_on_the_run_directory_without_bwrap(machine):
    (machine.bin / "bwrap-fails").write_text("")  # never used
    done, run = launch_step(machine, isolation=False)
    assert done.returncode == 0, done.stderr
    assert (run / "output" / "predictions.csv").read_text() == "id,label\nTEST_1,1.10\n"
    assert not machine.sandboxes.exists()
    done, run = launch_step(machine, "environment", isolation=False)
    names = (run / "output" / "predictions.csv").read_text().split()
    assert "FAKE_LOG" not in names and {"HOME", "USER", "VIRTUAL_ENV"} <= set(names)


def test_without_isolation_the_probe_finds_the_input_where_a_submission_would(machine):
    done, _ = launch_step(machine, mode="probe", command=sandbox.PROBE_COMMAND, isolation=False)
    report = json.loads(done.stdout.decode().split("probe=", 1)[1])
    assert report["input"] is True, done.stderr


def _netns_works():
    if os.name == "nt" or not shutil.which("unshare"):
        return False
    return subprocess.run(["unshare", "--user", "--net", "true"], capture_output=True).returncode == 0


@pytest.mark.skipif(not _netns_works(), reason="needs unprivileged user and network namespaces")
def test_with_netns_a_real_step_finds_no_network_but_its_input(machine):
    done, _ = launch_step(machine, mode="probe", command=sandbox.PROBE_COMMAND, isolation=False, netns=True)
    report = json.loads(done.stdout.decode().split("probe=", 1)[1])
    assert report["network"] == "blocked" and report["input"] is True, done.stderr


def test_without_isolation_a_process_left_behind_is_killed(machine):
    done, _ = launch_step(machine, "daemon", isolation=False)
    assert done.returncode == 0, done.stderr
    assert subprocess.run(["pgrep", "-f", "admin-eval-left-behind"], capture_output=True).returncode == 1


def test_without_isolation_the_timer_still_stops_the_step(machine):
    started = time.monotonic()
    done, run = launch_step(machine, "sleep", seconds=2, isolation=False)
    assert done.returncode == 137 and time.monotonic() - started < 20
    assert subprocess.run(["pgrep", "-f", str(run)], capture_output=True).returncode == 1


@pytest.mark.parametrize("behaviour, code", [("ok", 0), ("3", 3), ("255", 1), ("125", 1), ("124", 1)])
def test_the_launcher_reports_the_steps_own_exit_code(machine, behaviour, code):
    done, run = launch_step(machine, behaviour)
    assert done.returncode == code, done.stderr
    assert not (run / "step.pid").exists()  # removed once the step ends
    if behaviour == "ok":
        assert (run / "output" / "predictions.csv").read_text() == "id,label\nTEST_1,1.10\n"


def test_the_step_gets_none_of_the_launchers_environment(machine):
    done, run = launch_step(machine, "environment")
    names = (run / "output" / "predictions.csv").read_text().split()
    assert done.returncode == 0 and "FAKE_LOG" not in names and {"PATH", "HOME", "VIRTUAL_ENV"} <= set(names)


def test_a_sandbox_that_cannot_start_is_the_machines_fault(machine):
    (machine.bin / "bwrap-fails").write_text("")
    done, _ = launch_step(machine)
    assert done.returncode == 125 and b"uid map" in done.stderr and b"did not start" in done.stderr


def test_a_missing_environment_is_the_machines_fault(machine):
    (machine.root / "env" / "bin" / "python").unlink()
    done, _ = launch_step(machine)
    assert done.returncode == 125 and b"is missing" in done.stderr


@pytest.mark.parametrize("behaviour, isolation", [("flood", True), ("flood-exit", True), ("flood", False)])
def test_the_launcher_stops_a_step_whose_output_passes_its_limit(machine, behaviour, isolation):
    # Watched on the GPU machine, so the worker does not ask its size over SSH every few seconds.
    started = time.monotonic()
    done, run = launch_step(machine, behaviour, isolation=isolation, max_output=1000)
    assert done.returncode == sandbox.OUTPUT_OVER == launch.OUTPUT_OVER and b"output passed 1000 bytes" in done.stderr
    assert time.monotonic() - started < 20
    assert subprocess.run(["pgrep", "-f", str(run)], capture_output=True).returncode == 1  # nothing left running
    (run / "output" / "flood.bin").unlink()
    assert launch_step(machine, "ok", isolation=isolation, max_output=1000)[0].returncode == 0


def test_the_launchers_own_timer_stops_the_step(machine):
    started = time.monotonic()
    done, run = launch_step(machine, "sleep", seconds=2)
    assert done.returncode == 137 and time.monotonic() - started < 20
    assert subprocess.run(["pgrep", "-f", str(run)], capture_output=True).returncode == 1  # nothing left running


def _user_scopes():
    if os.name == "nt" or not shutil.which("systemd-run"):
        return False
    return subprocess.run(["systemd-run", "--user", "--scope", "--quiet", "true"], capture_output=True).returncode == 0


@pytest.mark.skipif(not _user_scopes(), reason="needs systemd-run --user")
def test_limits_put_the_step_in_a_scope_that_still_reports_its_start(machine, monkeypatch):
    monkeypatch.setattr(sandbox, "LIMITS", "cgroup")
    done, run = launch_step(machine, "cgroup")
    assert done.returncode == 0, done.stderr  # 125 would mean the start byte was lost on the way
    assert ".scope" in (run / "output" / "predictions.csv").read_text()


def test_stop_kills_a_launcher_but_never_another_process(tmp_path):
    if os.name == "nt":
        pytest.skip("reads /proc")
    sleeper = [sys.executable, "-c", "import time; time.sleep(60)"]
    launcher, other = subprocess.Popen([*sleeper, sandbox.MARKER]), subprocess.Popen(sleeper)
    try:
        (tmp_path / "a.pid").write_text(str(launcher.pid))
        (tmp_path / "b.pid").write_text(str(other.pid))
        (tmp_path / "c.pid").write_text("12x")
        files = [str(tmp_path / name) for name in ("a.pid", "b.pid", "c.pid", "missing.pid")]
        subprocess.run(["sh", "-c", sandbox.STOP, "sh", *files], check=True, timeout=10)
        assert launcher.wait(timeout=5) == -9 and other.poll() is None
    finally:
        launcher.kill()
        other.kill()


def run_with(machine, behaviour, evaluator=None, requirements=""):
    path = machine.tmp / "code.zip"
    path.write_bytes(make_zip({"inference.py": INFERENCE, "train.py": "", "requirements.txt": requirements,
                               "model/weights.bin": b"\x00" * 16, "behave.txt": behaviour}))
    if evaluator is None:
        evaluator = SandboxEvaluator()
        evaluator._verified = load_target()  # as if it passed its checks
    return evaluator.run(types.SimpleNamespace(id=7), path, lambda: None)


def test_a_submission_runs_in_a_sandbox_and_comes_back(machine):
    outcome = run_with(machine, "ok")
    assert outcome.ok and outcome.predictions == b"id,label\nTEST_1,1.10\n"
    sandboxes = machine.sandboxes.read_text().splitlines()
    assert len(sandboxes) == 1 and "--unshare-all" in sandboxes[0] and "--share-net" not in sandboxes[0]
    assert list(machine.work.glob("submission-*")) == []  # removed on the GPU machine
    assert list((machine.tmp / "here").glob("submission-*")) == []  # and here


def test_requirements_are_installed_into_the_run_directory_first(machine):
    outcome = run_with(machine, "ok", requirements="numpy\n")
    assert outcome.ok and "installed from requirements.txt (image wheels): numpy" in outcome.log
    install, infer = machine.sandboxes.read_text().splitlines()
    assert "install_packages.py offline /deps/venv numpy" in install and " /submission " not in install and " /input " not in install
    assert re.search(r"--ro-bind \S+/deps /deps", infer)


def test_without_isolation_a_whole_run_installs_scores_and_cleans_up(machine):
    evaluator = SandboxEvaluator()
    evaluator.configure(types.SimpleNamespace(eval_isolation=False))
    evaluator._verified = load_target()
    outcome = run_with(machine, "ok", evaluator, requirements="numpy\n")
    assert outcome.ok and outcome.predictions == b"id,label\nTEST_1,1.10\n"
    assert "installed from requirements.txt (image wheels): numpy" in outcome.log
    assert not machine.sandboxes.exists() and list(machine.work.glob("submission-*")) == []


@pytest.mark.parametrize("behaviour, message", [("3", "(종료 코드 3)"), ("255", "(종료 코드 1)")])
def test_a_failing_submission_is_the_teams_error(machine, behaviour, message):
    outcome = run_with(machine, behaviour)
    assert outcome.failure_code == "runtime_error" and outcome.message.endswith(message)


def test_a_sandbox_that_cannot_start_is_a_server_error_and_is_checked_again(machine):
    (machine.bin / "bwrap-fails").write_text("")
    evaluator = SandboxEvaluator()
    evaluator._verified = load_target()
    outcome = run_with(machine, "ok", evaluator)
    assert outcome.failure_code == "system_error" and "uid map" in outcome.log
    assert evaluator._verified is None


def test_output_past_the_limit_is_the_teams_error_without_polling_over_ssh(machine, monkeypatch):
    monkeypatch.setattr(local, "MAX_OUTPUT_BYTES", 1000)
    started = time.monotonic()
    outcome = run_with(machine, "flood")
    assert outcome.failure_code == "output_invalid" and "output passed 1000 bytes" in outcome.log
    assert time.monotonic() - started < 20
    assert "du -sb" not in (machine.tmp / "calls.log").read_text()


def test_a_timeout_kills_the_sandbox(machine, monkeypatch):
    monkeypatch.setattr(local, "INFERENCE_TIMEOUT_SECONDS", 2)
    started = time.monotonic()
    outcome = run_with(machine, "sleep")
    assert outcome.failure_code == "timeout" and time.monotonic() - started < 15
    assert subprocess.run(["pgrep", "-f", str(machine.work)], capture_output=True).returncode == 1


@pytest.fixture
def real_machine(machine, monkeypatch, tmp_path):
    if not REAL_BWRAP:
        pytest.skip("needs bwrap and unprivileged user namespaces")
    (machine.bin / "bwrap").unlink()  # the real one, further along PATH
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "id_ed25519").write_text("secret")
    monkeypatch.setenv("HOME", str(home))
    return machine


def test_a_real_sandbox_shows_no_network_no_home_and_the_input(real_machine):
    done, _ = launch_step(real_machine, mode="probe", seconds=60, command=sandbox.PROBE_COMMAND)
    report = json.loads(done.stdout.decode().split("probe=", 1)[1])
    assert report["network"] == "blocked" and report["ssh_visible"] is False and report["input"] is True


def test_a_real_sandbox_keeps_the_submission_read_only_and_the_machine_out_of_sight(real_machine):
    done, run = launch_step(real_machine, "look")
    assert done.returncode == 0, done.stderr
    wrote, *top = (run / "output" / "predictions.csv").read_text().split()
    assert wrote == "read-only" and not (run / "submission" / "written.txt").exists()
    assert {"submission", "input", "output", "usr", "tmp"} <= set(top) and not {"root", "var", "mnt", "srv"} & set(top)


def _memory_delegated():
    if not _user_scopes():
        return False
    uid = os.getuid()
    controllers = f"/sys/fs/cgroup/user.slice/user-{uid}.slice/user@{uid}.service/cgroup.controllers"
    try:
        return "memory" in open(controllers).read().split()
    except OSError:
        return False


@pytest.mark.skipif(not _memory_delegated(), reason="needs systemd-run --user with the memory controller")
def test_a_real_scope_stops_a_step_that_uses_too_much_memory(real_machine, monkeypatch):
    monkeypatch.setattr(sandbox, "LIMITS", "cgroup")
    monkeypatch.setattr(local, "MEMORY", "128m")
    outcome = run_with(real_machine, "memory")
    assert outcome.failure_code == "out_of_memory", outcome.log


def test_every_check_runs_on_a_real_machine(real_machine, monkeypatch):
    monkeypatch.setattr(sandbox, "LIMITS", "cgroup" if _memory_delegated() else "none")
    monkeypatch.setattr(remote_module, "MIN_FREE_GB", 0)
    monkeypatch.setenv("EVAL_WORK_HOST_DIR", str(real_machine.work))
    for name in ("key", "known"):
        (real_machine.tmp / name).write_text("x")
    checks, facts = sandbox.examine(load_target())
    # The test machine's environment has no torch, which the probe must notice; everything else passes.
    problems = failed(checks)
    assert list(problems) == ["sandbox_env"] and "torch" in problems["sandbox_env"].reason
    assert {"bwrap", "environment", "input", "work_dir", "disk"} <= {c.name for c in checks if c.ok}
    assert re.fullmatch(r"\d+\.\d+\.\d+", facts["python"]) and facts["lock"] == "abc"


def test_a_real_run_comes_back(real_machine):
    outcome = run_with(real_machine, "ok", requirements="numpy\n")
    assert outcome.ok and outcome.predictions == b"id,label\nTEST_1,1.10\n"
