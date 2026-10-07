"""Installs the packages one submission needs into an environment of its own, in the
evaluation image. The worker runs it at most twice on the same volume:

    python /opt/eval/install_packages.py offline /deps/venv "numpy>=2" "lightgbm==4.7.0" ...
    python /opt/eval/install_packages.py online /deps/venv "numpy>=2" "lightgbm==4.7.0" ...

`offline` runs without network and uses only the wheels baked into the image (the 89
packages of the competition lock), which covers most submissions. Only when it fails does
the worker run `online`, in a container that may reach PyPI; the image's wheels are still
preferred there. Either way only wheels are accepted, so no code of a package runs here:
it runs later in the inference container, which has no network.

The requirements were parsed and re-written by the worker (app/packages.py), never passed
as raw text from the submission. The environment also sees the image's base packages
(system site-packages), so pip installs only what is missing.
"""
import os
import re
import shutil
import subprocess
import sys
import venv

WHEELS = "/opt/wheels"
# CPU builds of torch, torchvision and torchaudio. Their `+cpu` versions sort above the
# plain PyPI ones, which would pull in gigabytes of CUDA libraries.
CPU_INDEX = "https://download.pytorch.org/whl/cpu"
# The image holds xgboost-cpu: the same `xgboost` module without the ~300 MB nvidia-nccl
# GPU dependency. Offline, `xgboost` means that wheel.
XGBOOST = re.compile(r"^xgboost(?=[\[<>=!~]|$)", re.IGNORECASE)


def main():
    mode, target, requirements = sys.argv[1], sys.argv[2], sys.argv[3:]
    if not os.path.exists(os.path.join(target, "pyvenv.cfg")):
        venv.EnvBuilder(system_site_packages=True, symlinks=True).create(target)
    if mode == "offline":
        sources = ["--no-index", "--find-links", WHEELS]
        requirements = [XGBOOST.sub("xgboost-cpu", item) for item in requirements]
    else:
        sources = ["--find-links", WHEELS, "--extra-index-url", CPU_INDEX]
    # Downloads go next to the environment, on disk: /tmp is a small tmpfs held in memory.
    scratch = os.path.join(os.path.dirname(target), "tmp")
    os.makedirs(scratch, exist_ok=True)
    try:
        code = subprocess.call([
            f"{target}/bin/python", "-m", "pip", "install", *sources, "--only-binary", ":all:",
            "--disable-pip-version-check", "--no-warn-script-location", "--progress-bar", "off",
            *requirements,
        ], env={**os.environ, "TMPDIR": scratch})
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    sys.exit(code)


if __name__ == "__main__":
    main()
