"""Installs the packages one submission needs into an environment of its own, from the
wheels baked into this image. The worker runs it in the evaluation image, without network:

    python /opt/eval/install_packages.py /deps/venv numpy==2.5.3 transformers==5.18.0 ...

It passes only `name==version` pins taken from the competition lock (app/packages.py),
never text from a submission. The environment also sees the image's base packages
(system site-packages), so pip installs only what is missing. Inference then runs with
its python.
"""
import subprocess
import sys
import venv

WHEELS = "/opt/wheels"
# The wheelhouse holds xgboost-cpu: the same `xgboost` module without the ~300 MB
# nvidia-nccl GPU dependency, which the CPU-only container never uses.
RENAMED = {"xgboost": "xgboost-cpu"}


def main():
    target, pins = sys.argv[1], sys.argv[2:]
    venv.EnvBuilder(system_site_packages=True, symlinks=True).create(target)
    requested = []
    for pin in pins:
        name, _, version = pin.partition("==")
        requested.append(f"{RENAMED.get(name.lower(), name)}=={version}")
    sys.exit(subprocess.call([
        f"{target}/bin/python", "-m", "pip", "install",
        "--no-index", "--find-links", WHEELS, "--only-binary", ":all:",
        "--no-cache-dir", "--disable-pip-version-check", "--no-warn-script-location", "--progress-bar", "off",
        *requested,
    ]))


if __name__ == "__main__":
    main()
