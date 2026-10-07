"""Scoring worker: a process separate from the web API.

    python -m app.worker            # run forever
    python -m app.worker --once     # score at most one submission, then exit
    python -m app.worker rescore    # recompute scores from stored predictions (docker mode)

It takes queued submissions from the database one at a time, runs the configured
evaluator, scores the predictions against hidden labels and updates the leaderboard.
State lives in the database, so queued work survives restarts of the worker or the server.
"""
import argparse
import json
import logging
import os
import socket
import time
from datetime import timedelta

from sqlalchemy import select, update

from . import storage
from .config import EVALUATOR, WORKER_STALE_SECONDS as STALE_SECONDS
from .db import SessionLocal
from .errors import FAILURES, UNCOUNTED_FAILURES
from .evaluators import get_evaluator
from .evaluators.base import failure
from .leaderboard import rebuild
from .models import Settings, Submission, Worker, now
from .scoring.predictions import OutputRejected, check
from .scoring.scorer import score

log = logging.getLogger("worker")
POLL_SECONDS = float(os.getenv("WORKER_POLL_SECONDS", "2"))
MAX_ATTEMPTS = int(os.getenv("WORKER_MAX_ATTEMPTS", "3"))
HEARTBEAT_SECONDS = 5


def worker_name():
    return os.getenv("WORKER_NAME") or f"{socket.gethostname()}-{os.getpid()}"


def report(db, worker_id, ready, detail, submission_id=None):
    row = db.get(Worker, worker_id)
    if not row:
        row = Worker(id=worker_id, evaluator=EVALUATOR)
        db.add(row)
    row.evaluator, row.ready, row.detail, row.submission_id, row.last_seen = EVALUATOR, ready, detail, submission_id, now()
    db.commit()


def recover_stale(db):
    """Returns submissions abandoned by a dead worker to the queue."""
    cutoff = now() - timedelta(seconds=STALE_SECONDS)
    rows = db.scalars(
        select(Submission).where(Submission.status == "running", Submission.heartbeat_at < cutoff).with_for_update(skip_locked=True)
    ).all()
    for row in rows:
        if row.attempts >= MAX_ATTEMPTS:
            row.status, row.failure_code, row.error_message = "failed", "system_error", FAILURES["system_error"]
            row.counted, row.finished_at = False, now()
            row.log_tail = f"gave up after {row.attempts} interrupted attempts"
        else:
            row.status, row.worker_id = "queued", None
        log.warning("recovered stale submission %s -> %s", row.id, row.status)
    db.commit()
    return len(rows)


def claim(db, worker_id):
    row = db.scalar(
        select(Submission).where(Submission.status == "queued").order_by(Submission.id).limit(1).with_for_update(skip_locked=True)
    )
    if not row:
        db.rollback()
        return None
    stamp = now()
    row.status, row.worker_id, row.attempts = "running", worker_id, row.attempts + 1
    row.started_at, row.heartbeat_at = stamp, stamp
    row.failure_code = row.error_message = row.log_tail = None
    db.commit()
    return row


def grade(outcome, answers):
    """Turns raw predictions into Public/Private scores using hidden labels."""
    labels, classes = answers()
    try:
        predictions, summary = check(outcome.predictions, labels.id.tolist(), classes)
    except OutputRejected as error:
        log = "\n".join(filter(None, [outcome.log, error.detail]))
        if error.operator_fault:  # the checker could not read classes or IDs: not the team's fault
            return failure("system_error", log=log)
        return failure("output_invalid", str(error), log)
    outcome.scores = score(labels, predictions, classes)
    outcome.predictions = json.dumps(predictions).encode()
    outcome.log = "\n".join(filter(None, [outcome.log, summary]))
    return outcome


def finish(db, submission_id, worker_id, outcome, evaluator_name):
    settings = db.scalar(select(Settings).where(Settings.id == 1).with_for_update())
    row = db.scalar(select(Submission).where(Submission.id == submission_id).with_for_update().execution_options(populate_existing=True))
    if not row or row.status != "running" or row.worker_id != worker_id:
        db.rollback()  # taken back as stale and handed to another worker; drop this result
        return None
    row.finished_at, row.evaluator, row.log_tail = now(), evaluator_name, (outcome.log or "")[-16000:] or None
    if outcome.ok:
        row.status, row.failure_code, row.error_message = "succeeded", None, None
        row.public_score, row.private_score = outcome.scores["public"], outcome.scores["private"]
        row.predictions = outcome.predictions.decode() if outcome.predictions else None
        db.flush()
        if not settings.frozen and not settings.finalized:
            rebuild(db)
    else:
        row.status, row.failure_code = "failed", outcome.failure_code
        row.error_message = outcome.message or FAILURES.get(outcome.failure_code, FAILURES["system_error"])
        row.public_score = row.private_score = row.predictions = None
        if outcome.failure_code in UNCOUNTED_FAILURES or not settings.count_failed:
            row.counted = False
    db.commit()
    return row


def process_one(db, evaluator, worker_id, answers=None):
    """Scores one queued submission. Returns its row, or None when the queue is empty."""
    row = claim(db, worker_id)
    if not row:
        return None
    submission_id, last = row.id, time.monotonic()
    report(db, worker_id, True, "running", submission_id)

    def tick():
        nonlocal last
        if time.monotonic() - last >= HEARTBEAT_SECONDS:
            last = time.monotonic()
            db.execute(update(Submission).where(Submission.id == submission_id).values(heartbeat_at=now()))
            db.execute(update(Worker).where(Worker.id == worker_id).values(last_seen=now()))
            db.commit()

    try:
        path = storage.path_for(row.storage_key or "")
        if not row.storage_key or not path.exists():
            outcome = failure("system_error", log="stored ZIP is missing")
        else:
            outcome = evaluator.run(row, path, tick)
            if outcome.ok and outcome.scores is None:
                if answers is None:
                    from .dataset import answers
                outcome = grade(outcome, answers)
    except Exception as error:  # keep the worker alive whatever a submission does
        log.exception("submission %s crashed the evaluator", submission_id)
        outcome = failure("system_error", log=f"{type(error).__name__}: {error}")
    result = finish(db, submission_id, worker_id, outcome, evaluator.name)
    log.info("submission %s -> %s", submission_id, result.status if result else "discarded")
    return result


def rescore(db):
    """Recomputes every stored real score from saved predictions, e.g. after labels are corrected."""
    from .dataset import answers

    if EVALUATOR != "docker":
        raise SystemExit("rescore는 EVALUATOR=docker에서만 사용할 수 있습니다. mock 점수에는 예측 파일이 없습니다.")
    labels, classes = answers()
    settings = db.scalar(select(Settings).where(Settings.id == 1).with_for_update())
    if settings.finalized:
        raise SystemExit("최종 순위 공개 후에는 점수를 다시 계산할 수 없습니다.")
    count = 0
    for row in db.scalars(select(Submission).where(Submission.status == "succeeded", Submission.evaluator == "docker", Submission.predictions.is_not(None))):
        scores = score(labels, json.loads(row.predictions), classes)
        row.public_score, row.private_score = scores["public"], scores["private"]
        count += 1
    db.flush()
    if not settings.frozen:
        rebuild(db)
    db.commit()
    return count


def run_forever(once=False):
    worker_id, evaluator = worker_name(), get_evaluator()
    log.info("worker %s started with evaluator=%s", worker_id, evaluator.name)
    labels_checked = evaluator.name != "docker"  # the mock never reads hidden labels
    while True:
        handled = None
        try:
            with SessionLocal() as db:
                ok, detail = evaluator.ready()
                if ok and not labels_checked:
                    try:
                        from .dataset import answers
                        answers()
                        labels_checked = True
                    except Exception as error:
                        ok, detail = False, f"hidden labels unavailable: {error}"
                recover_stale(db)
                handled = process_one(db, evaluator, worker_id) if ok else None
                report(db, worker_id, ok, detail)
                if not ok:
                    log.warning("evaluator not ready: %s", detail)
        except Exception:
            log.exception("worker loop error")
        if once:
            return
        if not handled:
            time.sleep(POLL_SECONDS)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="ADMIN challenge scoring worker")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "rescore"])
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.command == "rescore":
        with SessionLocal() as db:
            print(f"rescored {rescore(db)} submissions")
        return
    run_forever(once=args.once)


if __name__ == "__main__":
    main()
