"""Starts one step of a submission in a bubblewrap sandbox, ON THE GPU MACHINE.

The worker (sandbox.py) sends this file's text over SSH and runs it there with the scoring
environment's Python, `python -I -S -c <this text> <spec as JSON>`, so the machine keeps no
copy of it. It uses the standard library only and must still run on Python 3.8. The words
admin-eval-sandbox mark its command line: only a process showing them is ever killed by pid.

Steps (spec["mode"]):
  install-offline, install-online   install_packages.py fills <run>/deps. No submission and
                                    no evaluation input; only install-online has network.
  infer                             the submission's command: /submission and /input read
                                    only, /output writable, the GPUs, no network.
  probe                             a short check program in the infer sandbox.

Every sandbox sees /usr, a few files of /etc, the scoring environment and the Python it was
made from, all read only, plus the directories of its step at fixed paths and a private
/tmp. It gets new user, pid, ipc, uts, net (but install-online) and cgroup namespaces, no
capabilities, a session of its own and a clean environment. With spec["limits"],
`systemd-run --user --scope` puts it in a cgroup with memory, CPU and process limits.

Without isolation (spec["isolation"] false, for a machine that forbids user namespaces)
there is no sandbox: the step runs directly, with /submission, /input, /output and /deps in
its command rewritten to the run directory's. It still gets a clean environment, and when
this launcher runs as root, it runs as spec["run_uid"], an unprivileged user of its own
with spec["tasks"] processes at most, so it cannot change the scoring environment or
another run; every process of that user is killed when the step ends. It can reach the
network and read whatever that user may read.

Exit status: the step's own, but 125 when the sandbox could not start (the machine's
fault, never the team's), 137 when this launcher's timer stopped it and 124 when the
files under <run>/output passed spec["max_output"] bytes (looked at every second and once
more at the end, here, so the worker need not ask over SSH). A step that itself exits with
124, 125 or 255 is reported as 1, so it cannot pass for any of these or for a dropped SSH
link. Killing this launcher kills the whole sandbox with it.
"""
import glob
import json
import os
import posixpath
import select
import shutil
import signal
import stat
import subprocess
import sys
import time

try:
    import ctypes
    LIBC = ctypes.CDLL(None, use_errno=True)
except Exception:  # no ctypes, or not Linux (tests import this file anywhere)
    LIBC = None

FAULT, KILLED, OUTPUT_OVER = 125, 137, 124
PR_SET_PDEATHSIG, PR_SET_NO_NEW_PRIVS = 1, 38
# Without isolation: the account name the step sees, so nothing looks its uid up.
RUN_USER = "admin-eval-run"
BASE_PATH = "/usr/local/bin:/usr/bin:/bin"
# Top-level directories: links into /usr on merged-/usr systems, otherwise real directories.
TOP = ("bin", "sbin", "lib", "lib32", "lib64", "libx32")
# /etc files the dynamic loader, Python and pip may read. Missing ones are skipped.
ETC = ("ld.so.cache", "ld.so.conf", "ld.so.conf.d", "alternatives", "localtime", "passwd", "group", "nsswitch.conf")
# Only for install-online: name resolution and certificates.
NET_ETC = ("resolv.conf", "hosts", "host.conf", "gai.conf", "ssl", "ca-certificates", "pki")
# The sandbox writes one byte to this descriptor, closes it and becomes the step's command.
# The byte proves it started: every error of bwrap itself comes before it.
MARK_FD = 9
STARTED = f'printf 1 >&{MARK_FD}; exec {MARK_FD}>&-; exec "$@"'


def fail(message):
    sys.stderr.write(f"sandbox: {message}\n")
    sys.exit(FAULT)


def is_within(path, parent):
    return path == parent or path.startswith(parent.rstrip("/") + "/")


def python_prefix(python):
    """Prefix of the interpreter a virtualenv's python links to: /usr, or a Python of its own."""
    return posixpath.dirname(posixpath.dirname(os.path.realpath(python)))


def unnormalised(spec):
    for name in ("root", "run", "input"):
        path = spec[name]
        if not posixpath.isabs(path) or posixpath.normpath(path) != path:
            return f"{name} must be an absolute, normalised path, not {path!r}"
    return None


def unsafe(spec, prefix, home):
    """Why the sandbox would see more than it should, or None."""
    problem = unnormalised(spec)
    if problem:
        return problem
    places = {"root": spec["root"], "run": spec["run"], "input": spec["input"]}
    for name, path in places.items():
        if is_within(path, "/usr"):
            return f"{name} ({path}) is inside /usr, which every sandbox sees"
    if prefix == "/" or any(path and is_within(path, prefix) for path in (home, *places.values())):
        return (f"the scoring environment's Python lives in {prefix}, which holds {home} or the scoring "
                "directories; make the environment with a Python of its own (setup-server.sh)")
    return None


def look(path):
    if os.path.islink(path):
        return "link", os.readlink(path)
    if os.path.isdir(path):
        return "dir", None
    return ("file" if os.path.exists(path) else None), None


def system_mounts(look=look):
    args = ["--ro-bind", "/usr", "/usr"]
    for name in TOP:
        kind, target = look("/" + name)
        if kind == "link":
            args += ["--symlink", target, "/" + name]
        elif kind == "dir":
            args += ["--ro-bind", "/" + name, "/" + name]
    return args


def plan(spec, prefix, look=look, devices=(), home="", bwrap="bwrap"):
    """The argv of one step: [systemd-run ...] env -i VARIABLES bwrap OPTIONS sh -c STARTED sh COMMAND.
    `bwrap` is its full path: `env -i` would look for it in the sandbox's PATH."""
    mode, root, run = spec["mode"], spec["root"], spec["run"]
    env_dir = f"{root}/env"
    python = f"{env_dir}/bin/python"
    online = mode == "install-online"
    args = [bwrap, "--die-with-parent", "--new-session", "--unshare-all", "--cap-drop", "ALL"]
    if online:
        args.append("--share-net")
    # Mounted in this order: the private /tmp first, so a bind below /tmp stays visible over it.
    args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/dev/shm"]
    args += system_mounts(look)
    for name in ETC + (NET_ETC if online else ()):
        args += ["--ro-bind-try", f"/etc/{name}", f"/etc/{name}"]
    args += ["--ro-bind", env_dir, env_dir]
    if not is_within(prefix, "/usr"):
        args += ["--ro-bind", prefix, prefix]
    variables = {"HOME": "/tmp", "TMPDIR": "/tmp", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}

    if mode in ("install-offline", "install-online"):
        args += ["--ro-bind", f"{root}/eval", f"{root}/eval", "--ro-bind", f"{root}/wheels", f"{root}/wheels",
                 "--bind", f"{run}/deps", "/deps"]
        variables.update(PATH=f"{env_dir}/bin:{BASE_PATH}", ADMIN_EVAL_WHEELS=f"{root}/wheels", PIP_DISABLE_PIP_VERSION_CHECK="1")
        if spec.get("torch_index"):
            variables["ADMIN_EVAL_TORCH_INDEX"] = spec["torch_index"]
        if online and spec.get("pip_cache"):
            args += ["--bind", f"{root}/pip-cache", "/pip-cache"]
            variables["PIP_CACHE_DIR"] = "/pip-cache"
        else:
            variables["PIP_NO_CACHE_DIR"] = "1"
        command = [python, f"{root}/eval/install_packages.py", "online" if online else "offline", "/deps/venv", *spec["requirements"]]
        workdir = "/tmp"
    elif mode in ("infer", "probe"):
        if spec["gpus"]:
            # NVML and CUDA read /sys. Every NVIDIA node is shown; CUDA_VISIBLE_DEVICES picks
            # the GPUs, in nvidia-smi's order.
            args += ["--ro-bind-try", "/sys", "/sys"]
            for device in devices:
                args += ["--dev-bind-try", device, device]
            variables["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
            if spec["gpus"] != "all":
                variables["CUDA_VISIBLE_DEVICES"] = spec["gpus"]
        args += ["--ro-bind", f"{run}/submission", "/submission", "--ro-bind", spec["input"], "/input",
                 "--bind", f"{run}/output", "/output"]
        path, virtual = f"{env_dir}/bin:{BASE_PATH}", env_dir
        if spec.get("deps"):
            args += ["--ro-bind", f"{run}/deps", "/deps"]
            path, virtual = f"/deps/venv/bin:{path}", "/deps/venv"
        variables.update(PATH=path, VIRTUAL_ENV=virtual)
        command = list(spec["command"])
        if mode == "probe":
            command.append(f"{home}/.ssh")  # must not be visible inside
        workdir = "/submission"
    else:
        fail(f"unknown step {mode!r}")
    args += ["--chdir", workdir, "/bin/sh", "-c", STARTED, "sh", *command]

    head = ["env", "-i", *(f"{key}={value}" for key, value in sorted(variables.items()))]
    limits = spec.get("limits")
    if limits:
        head = ["systemd-run", "--user", "--scope", "--quiet", "--collect",
                "-p", f"MemoryMax={limits['memory']}", "-p", "MemorySwapMax=0",
                "-p", f"CPUQuota={limits['cpu_percent']}%", "-p", f"TasksMax={limits['tasks']}", "--", *head]
    return head + args


def plan_direct(spec, home=""):
    """(argv, working directory) of one step without isolation: env -i VARIABLES sh -c STARTED
    sh COMMAND, where every sandbox path in COMMAND is replaced by the run directory's."""
    mode, root, run = spec["mode"], spec["root"], spec["run"]
    env_dir = f"{root}/env"
    places = (("/submission", f"{run}/submission"), ("/input", spec["input"]), ("/output", f"{run}/output"), ("/deps", f"{run}/deps"))

    def host(arg):
        option, separator, value = arg.partition("=") if arg.startswith("-") else ("", "", arg)
        for inside, outside in places:
            if value == inside or value.startswith(inside + "/"):
                return option + separator + outside + value[len(inside):]
        return arg

    variables = {"HOME": f"{run}/tmp", "TMPDIR": f"{run}/tmp", "LANG": "C.UTF-8", "USER": RUN_USER, "LOGNAME": RUN_USER,
                 "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
    if mode in ("install-offline", "install-online"):
        # No pip cache: it would be shared with steps that can reach the network.
        variables.update(PATH=f"{env_dir}/bin:{BASE_PATH}", ADMIN_EVAL_WHEELS=f"{root}/wheels", PIP_DISABLE_PIP_VERSION_CHECK="1",
                         PIP_NO_CACHE_DIR="1")
        if spec.get("torch_index"):
            variables["ADMIN_EVAL_TORCH_INDEX"] = spec["torch_index"]
        online = "online" if mode == "install-online" else "offline"
        command = [f"{env_dir}/bin/python", f"{root}/eval/install_packages.py", online, f"{run}/deps/venv", *spec["requirements"]]
        workdir = f"{run}/tmp"
    elif mode in ("infer", "probe"):
        # Every GPU of the machine is visible: CUDA_VISIBLE_DEVICES picks them, or none.
        variables.update(CUDA_DEVICE_ORDER="PCI_BUS_ID", CUDA_VISIBLE_DEVICES="" if not spec["gpus"] else spec["gpus"])
        if spec["gpus"] == "all":
            del variables["CUDA_VISIBLE_DEVICES"]
        path, virtual = f"{env_dir}/bin:{BASE_PATH}", env_dir
        if spec.get("deps"):
            path, virtual = f"{run}/deps/venv/bin:{path}", f"{run}/deps/venv"
        variables.update(PATH=path, VIRTUAL_ENV=virtual)
        command = [host(arg) for arg in spec["command"]]
        if mode == "probe":
            command.append(f"{home}/.ssh")
        workdir = f"{run}/submission"
    else:
        fail(f"unknown step {mode!r}")
    argv = ["env", "-i", *(f"{key}={value}" for key, value in sorted(variables.items())), "/bin/sh", "-c", STARTED, "sh", *command]
    return argv, workdir


def become(uid, tasks):
    """Runs in the child, as root, before the step starts: the step's own user from then on,
    with its process limit, no core files, no way back to privileges, and killed with this launcher."""
    import resource  # Unix only; imported here, before the fork

    def change():
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if tasks:
            resource.setrlimit(resource.RLIMIT_NPROC, (tasks, tasks))
        os.setgroups([])
        os.setgid(uid)
        os.setuid(uid)
        if LIBC is not None:
            LIBC.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)
            # After setuid, which clears the parent-death signal.
            LIBC.prctl(PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0)
    return change


def kill_user(uid):
    """Kills every process of the step's own user, a daemon the step left behind included."""
    for _ in range(5):
        found = False
        for name in os.listdir("/proc"):
            if not name.isdigit():
                continue
            try:
                with open(f"/proc/{name}/status") as status:
                    real = next(int(line.split()[1]) for line in status if line.startswith("Uid:"))
                if real == uid:
                    os.kill(int(name), signal.SIGKILL)
                    found = True
            except (OSError, ValueError, StopIteration):
                pass
        if not found:
            return
        time.sleep(0.2)


def version(root):
    """The key=value lines of <root>/VERSION, written by setup-server.sh."""
    values = {}
    try:
        with open(f"{root}/VERSION", encoding="utf-8") as lines:
            for line in lines:
                key, separator, value = line.partition("=")
                if separator:
                    values[key.strip()] = value.strip()
    except OSError:
        pass
    return values


def die_with_launcher():
    """Runs in the child before bwrap starts: it is killed when this launcher dies."""
    if LIBC is not None:
        LIBC.prctl(PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0)


def marker_pipe():
    """(read end, write end at MARK_FD)."""
    read, write = os.pipe()
    if read == MARK_FD:
        read, old = os.dup(read), read
        os.close(old)
    if write != MARK_FD:
        os.dup2(write, MARK_FD)
        os.close(write)
    return read, MARK_FD


def prepare_direct(spec):
    """(argv, working directory, function run in the child, user to clean up after) without isolation."""
    problem = unnormalised(spec)
    if problem:
        fail(problem)
    run = spec["run"]
    places = [f"{run}/tmp"] + ([f"{run}/deps"] if spec["mode"].startswith("install") else [])
    for place in places:
        os.makedirs(place, exist_ok=True)
    uid = spec.get("run_uid") if os.geteuid() == 0 else None
    if uid is None:
        return (*plan_direct(spec, os.environ.get("HOME", "")), die_with_launcher, None)
    # The step's own user writes only these; the scoring environment and other runs stay root's.
    for place in places + [f"{run}/output"]:
        os.chown(place, uid, uid)
    return (*plan_direct(spec, os.environ.get("HOME", "")), become(uid, spec.get("tasks")), uid)


def directory_size(path):
    """Bytes in the regular files under `path`, links not followed."""
    total = 0
    for top, _, names in os.walk(path):
        for name in names:
            try:
                status = os.lstat(os.path.join(top, name))
            except OSError:
                continue  # removed meanwhile
            if stat.S_ISREG(status.st_mode):
                total += status.st_size
    return total


def wait(process, seconds, output, limit):
    """"done", "timeout" or "output": waits for the step, and with a `limit` looks every
    second whether the files under `output` passed it."""
    deadline = time.monotonic() + seconds
    while True:
        left = deadline - time.monotonic()
        try:
            process.wait(timeout=max(0.0, left if limit is None else min(left, 1.0)))
            return "done"
        except subprocess.TimeoutExpired:
            if time.monotonic() >= deadline:
                return "timeout"
            if directory_size(output) > limit:
                return "output"


def main():
    home, pidfile, uid = os.environ.get("HOME", ""), None, None
    try:
        spec = json.loads(sys.argv[1])
        pidfile = spec.get("pidfile")
        if spec["mode"].startswith("install"):
            spec = {**spec, "torch_index": version(spec["root"]).get("torch_index", ""),
                    "pip_cache": os.path.isdir(f"{spec['root']}/pip-cache")}
        if spec.get("isolation", True):
            prefix = python_prefix(f"{spec['root']}/env/bin/python")
            problem = unsafe(spec, prefix, home)
            if problem:
                fail(problem)
            if spec["mode"].startswith("install"):
                os.makedirs(f"{spec['run']}/deps", exist_ok=True)
            bwrap = shutil.which("bwrap")
            if not bwrap:
                fail("bwrap is not installed")
            devices = sorted(glob.glob("/dev/nvidia*")) if spec["gpus"] else []
            argv, workdir, child = plan(spec, prefix, devices=devices, home=home, bwrap=bwrap), None, die_with_launcher
        else:
            argv, workdir, child, uid = prepare_direct(spec)
        if pidfile:
            with open(pidfile, "w") as handle:
                handle.write(str(os.getpid()))
        read, write = marker_pipe()
        # Without isolation the step gets a process group of its own, killed as a whole at the end.
        direct = workdir is not None
        process = subprocess.Popen(argv, cwd=workdir, stdin=subprocess.DEVNULL, pass_fds=(write,), preexec_fn=child,
                                   start_new_session=direct)
        os.close(write)
    except Exception as error:  # anything here is the machine's or the worker's fault
        fail(f"could not start: {type(error).__name__}: {error}")
    output, limit = f"{spec['run']}/output", spec.get("max_output")
    try:
        stopped = wait(process, spec["seconds"], output, limit)
        if stopped != "done":
            process.kill()
            process.wait()
        if direct:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass  # the group is gone already
        if uid is not None:
            kill_user(uid)
        ready, _, _ = select.select([read], [], [], 5)
        started = bool(ready) and os.read(read, 1) == b"1"
    finally:
        if pidfile:
            try:
                os.remove(pidfile)
            except OSError:
                pass
    if stopped == "timeout":
        sys.exit(KILLED)
    if not started:
        fail(f"the step did not start (exit code {process.returncode}; the message of bwrap or env is above)")
    if limit is not None and (stopped == "output" or directory_size(output) > limit):
        sys.stderr.write(f"sandbox: the output passed {limit} bytes; the step was stopped\n")
        sys.exit(OUTPUT_OVER)
    code = process.returncode if process.returncode >= 0 else 128 - process.returncode
    sys.exit(1 if code in (FAULT, OUTPUT_OVER, 255) else code)


if __name__ == "__main__":
    main()
