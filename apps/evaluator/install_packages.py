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

Without Docker (EVALUATOR=sandbox) the same script runs from the scoring environment, a
virtualenv on the GPU machine made by setup-server.sh. ADMIN_EVAL_WHEELS and
ADMIN_EVAL_TORCH_INDEX then name its wheels and its CUDA build of torch, and the new
environment sees the scoring environment's packages through a .pth file instead.
"""
import os
import re
import shutil
import site
import subprocess
import sys
import venv

WHEELS = os.getenv("ADMIN_EVAL_WHEELS", "/opt/wheels")
# Builds of torch, torchvision and torchaudio: CPU ones in the image. Their `+cpu` versions
# sort above the plain PyPI ones, which would pull in gigabytes of CUDA libraries.
TORCH_INDEX = os.getenv("ADMIN_EVAL_TORCH_INDEX", "https://download.pytorch.org/whl/cpu")
# The image holds xgboost-cpu: the same `xgboost` module without the ~300 MB nvidia-nccl
# GPU dependency. Offline, `xgboost` means that wheel.
XGBOOST = re.compile(r"^xgboost(?=[\[<>=!~]|$)", re.IGNORECASE)


def create(target):
    if sys.prefix == sys.base_prefix:
        venv.EnvBuilder(system_site_packages=True, symlinks=True).create(target)
        return
    # Run from a virtualenv, whose packages "system site-packages" would not include: they
    # are added after the new environment's own, which therefore win, as in the image.
    venv.EnvBuilder(symlinks=True).create(target)
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    with open(os.path.join(target, "lib", version, "site-packages", "admin-eval-base.pth"), "w") as pth:
        pth.write("\n".join(site.getsitepackages()) + "\n")


def main():
    mode, target, requirements = sys.argv[1], sys.argv[2], sys.argv[3:]
    if not os.path.exists(os.path.join(target, "pyvenv.cfg")):
        create(target)
    if mode == "offline":
        sources = ["--no-index", "--find-links", WHEELS]
        requirements = [XGBOOST.sub("xgboost-cpu", item) for item in requirements]
    else:
        sources = ["--find-links", WHEELS, "--extra-index-url", TORCH_INDEX]
    # --no-compile: pip would byte-compile every .py file it unpacks, which was most of the time
    # of a large install (49-57 s down to 13-15 s for the whole lock on the GPU machine). The
    # inference container cannot write .pyc files, so those packages are compiled in memory at
    # each import instead: about 3 s more per run for the heaviest set. The base packages are
    # installed with pip's default and keep their .pyc files.
    # Downloads go next to the environment, on disk: /tmp is a small tmpfs held in memory.
    scratch = os.path.join(os.path.dirname(target), "tmp")
    os.makedirs(scratch, exist_ok=True)
    try:
        code = subprocess.call([
            f"{target}/bin/python", "-m", "pip", "install", *sources, "--only-binary", ":all:",
            "--disable-pip-version-check", "--no-warn-script-location", "--progress-bar", "off",
            "--no-compile", *requirements,
        ], env={**os.environ, "TMPDIR": scratch})
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    sys.exit(code)


if __name__ == "__main__":
    main()
