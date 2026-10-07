FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MPLCONFIGDIR=/tmp/matplotlib
WORKDIR /srv
COPY apps/api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY apps/api /srv/apps/api
COPY scripts /srv/scripts
RUN useradd --create-home --uid 10001 challenge \
    && mkdir -p /srv/data /srv/submissions /srv/eval-work \
    && chown -R challenge:challenge /srv
WORKDIR /srv/apps/api

# Scoring worker: same code, separate process. The docker CLI is only used when
# EVALUATOR=docker (see docker-compose.evaluator.yml); the API image never has it.
FROM base AS worker
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker
USER challenge
CMD ["python","-m","app.worker"]

FROM base AS api
USER challenge
EXPOSE 8000
CMD ["sh","-c","alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers"]
