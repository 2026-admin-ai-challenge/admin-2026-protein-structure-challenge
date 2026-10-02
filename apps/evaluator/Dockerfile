# Fixed image in which every submission's inference runs. DRAFT: the package list must be
# agreed with the data team (Q2, Q6). Participants cannot install anything at scoring time:
# the container has no network, so whatever a model needs has to be listed here.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
USER 65534:65534
WORKDIR /submission
