# Fixed image in which every submission's inference runs. DRAFT: the package list must be
# agreed with the data team (Q2, Q6). Participants cannot install anything at scoring time:
# the container has no network, so whatever a model needs has to be listed here.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# OpenMP runtime: LightGBM needs libgomp.so.1, which the slim image does not include.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --retries 10 --timeout 120 -r /tmp/requirements.txt
USER 65534:65534
WORKDIR /submission
