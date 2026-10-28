#!/bin/sh
# Makes the scoring environment of EVALUATOR=sandbox on the GPU machine: what the image
# built by the Dockerfile next to this file is for EVALUATOR=docker and remote. Run it once
# as the SSH account the worker uses, from a copy of apps/evaluator:
#
#   scp -r apps/evaluator evaluator@gpu-server:admin-eval-setup
#   ssh evaluator@gpu-server
#   sh admin-eval-setup/setup-server.sh --root "$HOME/admin-eval" \
#       --python /usr/bin/python3.12 --torch-index https://download.pytorch.org/whl/cu126
#
# It needs no root, writes nothing outside --root and changes no system setting. bwrap and
# unprivileged user namespaces are the server owner's to provide; the worker checks them.
#
#   <root>/env/        virtualenv with requirements.txt, the base packages (read only)
#   <root>/eval/       install_packages.py (read only)
#   <root>/wheels/     wheels of requirements-competition.lock.txt (read only)
#   <root>/pip-cache/  downloads kept between online installs
#   <root>/work/       submissions while they run: EVAL_REMOTE_WORK_DIR
#   <root>/input/      the evaluation input, copied by hand: EVAL_REMOTE_INPUT_DIR
#   <root>/VERSION     what the worker checks
#
# --python       CPython 3.12, as in the image: under /usr, or a Python of its own (without
#                root, `uv python install 3.12` gives one). Not one whose prefix holds the
#                home directory: every sandbox sees that prefix.
# --torch-index  where the CUDA build of torch comes from. It must support the driver and
#                the GPU (a P100 needs a build that still has sm_60); the worker's check
#                proves it by computing on the GPU inside a sandbox.
# --wheels-from  a directory of wheels prepared elsewhere (Linux x86_64, Python 3.12), for a
#                machine without internet. Otherwise they are downloaded.
set -eu

die() {
  echo "setup-server: $*" >&2
  exit 1
}

here=$(cd "$(dirname "$0")" && pwd)
root= python= torch_index= wheels_from=
while [ $# -gt 0 ]; do
  case "$1" in
    --root) root=${2:?--root needs a value}; shift 2 ;;
    --python) python=${2:?--python needs a value}; shift 2 ;;
    --torch-index) torch_index=${2:?--torch-index needs a value}; shift 2 ;;
    --wheels-from) wheels_from=${2:?--wheels-from needs a value}; shift 2 ;;
    -h|--help) sed -n '2,/^set -eu/p' "$0" | sed '$d'; exit 0 ;;
    *) die "unknown option $1 (see --help)" ;;
  esac
done

[ -n "$root" ] || die "--root is required, for example --root \"\$HOME/admin-eval\""
[ -n "$torch_index" ] || die "--torch-index is required, for example https://download.pytorch.org/whl/cu126"
case "$root" in
  /*) ;;
  *) die "--root must be an absolute path" ;;
esac
root=${root%/}
case "$root" in
  /usr|/usr/*) die "--root must not be inside /usr: every sandbox sees /usr" ;;
esac
[ "$root" != "${HOME%/}" ] || die "--root must be a directory of its own, not the home directory"

for file in Dockerfile requirements.txt requirements-competition.lock.txt install_packages.py; do
  [ -f "$here/$file" ] || die "$here/$file is missing: run this from a copy of apps/evaluator"
done
# The installer's version, as the image's label says (INSTALLER_VERSION in apps/api/app/evaluators/docker.py).
installer=$(sed -n 's/^LABEL admin-eval.installer="\(.*\)"$/\1/p' "$here/Dockerfile")
[ -n "$installer" ] || die "no admin-eval.installer label in $here/Dockerfile"

python=${python:-$(command -v python3.12 || true)}
[ -n "$python" ] && [ -x "$python" ] || die "no python3.12 found; pass --python (for example one made by UV_PYTHON_INSTALL_DIR=/srv/admin-eval-python uv python install 3.12)"
version=$("$python" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
[ "$version" = 3.12 ] || die "$python is Python $version; the scoring image uses 3.12"
prefix=$(dirname "$(dirname "$("$python" -c 'import os, sys; print(os.path.realpath(sys.executable))')")")
case "$prefix" in
  /usr|/usr/*) ;;
  /) die "$python lives in /, which every sandbox would then see; use a Python of its own" ;;
  *)
    case "${HOME%/}/" in "$prefix"/*) die "$python lives in $prefix, which holds the home directory; use a Python of its own" ;; esac
    case "$root/" in "$prefix"/*) die "$python lives in $prefix, which holds $root; use a Python outside it or in its own directory" ;; esac
    ;;
esac

# As root, steps without isolation run as an unprivileged user (EVAL_SANDBOX_RUN_UID), which
# must reach <root> and the Python: no directory on the way may be closed to others (/root is).
if [ "$(id -u)" = 0 ]; then
  for place in "$root" "$prefix"; do
    dir=$place
    while [ "$dir" != / ]; do
      dir=$(dirname "$dir")
      [ -d "$dir" ] || continue
      [ $(( $(stat -c %a "$dir") % 2 )) -eq 1 ] || die "$dir is closed to other users, so a step without isolation could not reach $place.
  Put --root and the Python elsewhere, for example --root /srv/admin-eval and a Python made by
  UV_PYTHON_INSTALL_DIR=/srv/admin-eval-python uv python install 3.12"
    done
  done
fi

if [ -e "$root/env" ]; then
  die "$root/env already exists. To make it again, while nothing is being scored:
  chmod -R u+w $root/env $root/eval $root/wheels && rm -rf $root/env $root/eval $root/wheels $root/VERSION"
fi
command -v bwrap >/dev/null 2>&1 || echo "warning: bwrap is not installed; the server owner must install bubblewrap before scoring"

# Others may not list <root> or <root>/work, but the user a step runs as without isolation
# (EVAL_SANDBOX_RUN_UID, when this account is root) must read the environment and the input.
umask 022
mkdir -p "$root/eval" "$root/wheels" "$root/pip-cache" "$root/work" "$root/input"
chmod 711 "$root" "$root/work"
chmod 700 "$root/pip-cache"

echo "1/4 scoring environment $root/env ($("$python" -V 2>&1))"
"$python" -m venv "$root/env"

echo "2/4 wheels of the competition lock"
if [ -n "$wheels_from" ]; then
  cp "$wheels_from"/*.whl "$root/wheels/"
else
  # As in the Dockerfile: xgboost-cpu is the same module without the nvidia-nccl dependency.
  sed 's/^xgboost==/xgboost-cpu==/' "$here/requirements-competition.lock.txt" > "$root/wheels.txt"
  "$root/env/bin/python" -m pip download --disable-pip-version-check --no-cache-dir --retries 10 --timeout 120 \
    --only-binary :all: --extra-index-url "$torch_index" --dest "$root/wheels" -r "$root/wheels.txt"
  rm -f "$root/wheels.txt"
fi

echo "3/4 base packages"
"$root/env/bin/python" -m pip install --disable-pip-version-check --no-cache-dir --no-index \
  --find-links "$root/wheels" -r "$here/requirements.txt"
cp "$here/install_packages.py" "$root/eval/"

echo "4/4 VERSION"
{
  echo "installer=$installer"
  echo "lock=$(sha256sum "$here/requirements-competition.lock.txt" | cut -c1-64)"
  echo "torch_index=$torch_index"
  echo "python=$("$root/env/bin/python" -c 'import platform; print(platform.python_version())')"
  echo "created=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$root/VERSION"
chmod -R a-w "$root/env" "$root/eval" "$root/wheels" "$root/VERSION"

cat <<EOF
Done: $root
Next:
  1. Copy the evaluation input (no labels) into $root/input, readable by others:
     test.csv, test_features.csv, test_structures.zip, then chmod -R a+rX $root/input
  2. In the web server's .env:
     EVAL_REMOTE_EVALUATOR=sandbox
     EVAL_SANDBOX_ROOT=$root
     EVAL_REMOTE_WORK_DIR=$root/work
     EVAL_REMOTE_INPUT_DIR=$root/input
     EVAL_GPUS=0            (nvidia-smi's index; empty for CPU only)
  3. On the web server, check everything before the first submission:
     docker compose -f docker-compose.yml -f docker-compose.remote.yml exec worker python -m app.evaluators.sandbox
EOF
