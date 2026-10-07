# Fixed image in which every submission's inference runs, without network:
#   requirements.txt                    base packages, installed for every submission.
#   requirements-competition.lock.txt   the data team's 89 pinned packages, a copy of
#                                       admin-2026-protein-data/runtime/. Only their wheels
#                                       are stored, in /opt/wheels, so most installs need
#                                       no download.
# Before inference the worker runs install_packages.py in this image to install what a
# submission's requirements.txt lists into an environment of its own: from /opt/wheels
# without network first, and from PyPI only when something is missing there.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# OpenMP runtime: LightGBM needs libgomp.so.1, which the slim image does not include.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements-competition.lock.txt requirements.txt /opt/eval/
# Linux wheels, plus the Linux-only dependencies the lock (made on Windows) does not list.
# The CPU index gives torch, torchvision and torchaudio without CUDA. xgboost-cpu is xgboost
# without the ~300 MB nvidia-nccl GPU dependency; install_packages.py maps the name.
RUN sed 's/^xgboost==/xgboost-cpu==/' /opt/eval/requirements-competition.lock.txt > /tmp/wheels.txt \
 && pip download --no-cache-dir --retries 10 --timeout 120 --only-binary :all: \
        --extra-index-url https://download.pytorch.org/whl/cpu --dest /opt/wheels -r /tmp/wheels.txt \
 && rm /tmp/wheels.txt
RUN pip install --no-cache-dir --no-index --find-links /opt/wheels -r /opt/eval/requirements.txt
# Mount points of a submission's package volume and the shared pip download cache. Docker
# gives a new volume the owner of this directory, so the unprivileged install container
# can write to it.
RUN mkdir /deps /pip-cache && chown 65534:65534 /deps /pip-cache
# Last, so changing it does not download the wheels again. The worker checks the label and
# refuses an image without this installer (apps/api/app/evaluators/docker.py).
COPY install_packages.py /opt/eval/
LABEL admin-eval.installer="1"
USER 65534:65534
WORKDIR /submission
