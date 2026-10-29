import json
import uuid
from datetime import timedelta

import pandas as pd
import pytest
from sqlalchemy import select

from app.evaluators.base import Evaluator, Outcome
from app.evaluators.mock import MockEvaluator
from app.leaderboard import rebuild
from app.models import LeaderboardEntry, Settings, Submission, SubmissionFile, Team, User, Worker, now
from app.worker import process_one, recover_stale
from conftest import add_account, login, make_zip, upload
from test_api import HIDDEN_FIELDS, PARTICIPANT_PATHS

MOCK = MockEvaluator()


def mock_zip(**controls):
    return make_zip(extra={"mock.json": json.dumps(controls)})


def scored(db, user, public, private, seconds=0, evaluator="mock", zip_bytes=None):
    stamp = now() + timedelta(seconds=seconds)
    row = Submission(user_id=user["id"], team_id=user["team_id"], filename="code.zip", status="succeeded",
                     public_score=public, private_score=private, evaluator=evaluator, created_at=stamp, finished_at=stamp)
    if zip_bytes is not None:
        row.file = SubmissionFile(team_id=user["team_id"], uploaded_by=user["id"], original_filename="code.zip",
                                  storage_key=uuid.uuid4().hex, sha256="0" * 64, size_bytes=zip_bytes, created_at=stamp)
    db.add(row)
    db.flush()
    return row


def test_worker_scores_queue_in_order_and_updates_leaderboard(client, db, participant):
    first = upload(client, mock_zip(public=0.5, private=0.9)).json()
    second = upload(client, mock_zip(public=0.7, private=0.1)).json()
    assert (first["queue_position"], second["queue_position"]) == (1, 2)
    assert client.get("/api/leaderboard").json()["entries"] == []

    done = process_one(db, MOCK, "worker-a")
    assert done.id == first["id"] and done.status == "succeeded" and done.evaluator == "mock"
    assert done.started_at and done.finished_at and done.attempts == 1
    history = {entry["id"]: entry for entry in client.get("/api/submissions/me").json()["entries"]}
    assert history[first["id"]]["public_score"] == 0.5 and history[first["id"]]["queue_position"] is None
    assert history[second["id"]]["status"] == "queued" and history[second["id"]]["queue_position"] == 1

    assert process_one(db, MOCK, "worker-a").id == second["id"]
    assert process_one(db, MOCK, "worker-a") is None
    entry = client.get("/api/leaderboard").json()["entries"][0]
    assert entry["team"] == participant["team_name"] and entry["score"] == 0.7 and entry["submissions"] == 2
    assert db.scalar(select(LeaderboardEntry.submission_id).where(LeaderboardEntry.board == "public")) == second["id"]
    for path in PARTICIPANT_PATHS + [f"/api/submissions/{first['id']}"]:
        response = client.get(path)
        assert response.status_code == 200
        for field in HIDDEN_FIELDS:
            assert field not in response.text
    worker = db.get(Worker, "worker-a")
    assert worker.ready and worker.evaluator == "mock"


@pytest.mark.parametrize("code", ["timeout", "runtime_error", "out_of_memory", "output_missing", "output_invalid"])
def test_failures_are_recorded_and_count_by_default(client, db, participant, code):
    submitted = upload(client, mock_zip(fail=code)).json()
    row = process_one(db, MOCK, "worker-a")
    assert (row.status, row.failure_code, row.counted) == ("failed", code, True)
    assert row.public_score is None and row.finished_at
    seen = client.get(f"/api/submissions/{submitted['id']}").json()
    assert seen["failure_code"] == code and seen["error_message"] and "mock" not in seen["error_message"]
    assert client.get("/api/submissions/me").json()["used"] == 1
    assert client.get("/api/leaderboard").json()["entries"] == []


def test_zip_violations_found_by_the_worker_never_use_an_attempt(client, db, participant):
    upload(client, mock_zip(fail="zip_invalid"))
    assert client.get("/api/submissions/me").json()["used"] == 1  # held while it waits
    row = process_one(db, MOCK, "worker-a")
    assert (row.status, row.failure_code, row.counted) == ("failed", "zip_invalid", False)
    assert client.get("/api/submissions/me").json()["used"] == 0


def test_failed_attempts_are_returned_when_policy_says_so(client, db, participant):
    db.get(Settings, 1).count_failed = False
    db.commit()
    upload(client, mock_zip(fail="runtime_error"))
    assert client.get("/api/submissions/me").json()["used"] == 1  # held while it waits
    assert process_one(db, MOCK, "worker-a").counted is False
    assert client.get("/api/submissions/me").json()["used"] == 0


def test_server_faults_never_use_an_attempt_and_can_be_requeued(client, db, participant, organizer):
    class Broken(Evaluator):
        name = "mock"

        def run(self, submission, zip_path, tick):
            raise RuntimeError("disk on fire")

    submitted = upload(client).json()
    row = process_one(db, Broken(), "worker-a")
    assert (row.status, row.failure_code, row.counted) == ("failed", "system_error", False)
    assert "disk on fire" in row.log_tail and "disk on fire" not in row.error_message
    assert client.get("/api/submissions/me").json()["used"] == 0
    assert client.post(f"/api/admin/submissions/{submitted['id']}/requeue").status_code == 403

    participant_session = client.cookies.get("admin_session")
    client.cookies.set("admin_session", organizer)
    detail = client.get(f"/api/admin/submissions/{submitted['id']}").json()
    assert "disk on fire" in detail["log_tail"] and detail["file_present"] is True
    overview = client.get("/api/admin/overview").json()
    assert overview["queue"]["failed"] == 1 and overview["failures"] == {"system_error": 1} and overview["evaluator"] == "mock"
    assert [s["id"] for s in client.get("/api/admin/submissions?status=failed&failure_code=system_error").json()] == [submitted["id"]]
    assert client.get("/api/admin/submissions?status=succeeded").json() == []
    assert len(client.get("/api/admin/submissions?q=Protein").json()) == 1
    assert client.post(f"/api/admin/submissions/{submitted['id']}/requeue").status_code == 200
    assert client.post(f"/api/admin/submissions/{submitted['id']}/requeue").status_code == 409
    assert process_one(db, MOCK, "worker-a").status == "succeeded"

    client.cookies.set("admin_session", participant_session)
    assert client.get("/api/submissions/me").json()["used"] == 1
    client.cookies.set("admin_session", organizer)
    assert client.patch(f"/api/admin/submissions/{submitted['id']}", json={"counted": False}).json()["used"] == 0
    actions = {entry["action"] for entry in client.get("/api/admin/audit").json()}
    assert {"submission.requeue", "submission.counted"} <= actions


def test_requeue_keeps_an_attempt_the_organizer_gave_back(client, db, participant, organizer):
    submitted = upload(client, mock_zip(fail="runtime_error")).json()
    assert process_one(db, MOCK, "worker-a").counted is True
    client.cookies.set("admin_session", organizer)
    assert client.patch(f"/api/admin/submissions/{submitted['id']}", json={"counted": False}).json()["used"] == 0
    assert client.post(f"/api/admin/submissions/{submitted['id']}/requeue").status_code == 200
    db.expire_all()
    assert db.get(Submission, submitted["id"]).counted is False
    assert process_one(db, MOCK, "worker-a").counted is False
    assert client.get("/api/admin/teams").json()[0]["used"] == 0


def test_restart_recovers_running_submissions(client, db, participant):
    submitted = upload(client).json()
    row = db.get(Submission, submitted["id"])
    row.status, row.worker_id, row.attempts = "running", "dead-worker", 1
    row.started_at = row.heartbeat_at = now() - timedelta(minutes=30)
    db.commit()
    assert process_one(db, MOCK, "worker-b") is None  # still owned by the dead worker
    assert recover_stale(db) == 1 and db.get(Submission, submitted["id"]).status == "queued"
    done = process_one(db, MOCK, "worker-b")
    assert done.status == "succeeded" and done.attempts == 2 and done.worker_id == "worker-b"

    # A submission that keeps killing workers is given up on, without using an attempt.
    again = upload(client).json()
    row = db.get(Submission, again["id"])
    row.status, row.attempts, row.heartbeat_at = "running", 3, now() - timedelta(minutes=30)
    db.commit()
    recover_stale(db)
    row = db.get(Submission, again["id"])
    assert (row.status, row.failure_code, row.counted) == ("failed", "system_error", False)


def test_result_of_a_worker_that_lost_its_job_is_dropped(client, db, participant):
    submitted = upload(client).json()

    class Slow(Evaluator):
        name = "mock"

        def run(self, submission, zip_path, tick):
            # While this worker was busy, the job was taken back and given to another one.
            db.get(Submission, submitted["id"]).worker_id = "worker-b"
            db.commit()
            return Outcome(ok=True, scores={"public": 0.99, "private": 0.99})

    assert process_one(db, Slow(), "worker-a") is None
    row = db.get(Submission, submitted["id"])
    assert row.status == "running" and row.public_score is None


class Picking(Evaluator):
    """Like a GPU machine with EVAL_GPU_PICK=free: `free` are its nearly empty GPUs."""
    name = "mock"
    picks_gpus = True

    def __init__(self, free):
        self.free, self.asked, self.ran = free, [], []

    def free_gpus(self, held=()):
        self.asked.append(set(held))
        return [index for index in self.free if index not in held]

    def run(self, submission, zip_path, tick):
        self.ran.append(submission.gpu)
        return Outcome(ok=True, scores={"public": 0.5, "private": 0.5})


def test_each_run_gets_a_gpu_no_running_submission_holds(client, db, participant):
    evaluator = Picking(["3", "5"])
    assert process_one(db, evaluator, "worker-b") is None and evaluator.asked == []  # empty queue: the machine is not asked
    first, second = upload(client).json(), upload(client).json()
    # A slot that died mid-run still holds its GPU until recover_stale gives the submission back.
    row = db.get(Submission, first["id"])
    row.status, row.worker_id, row.gpu, row.attempts = "running", "worker-a", "3", 1
    row.started_at = row.heartbeat_at = now() - timedelta(minutes=30)
    db.commit()
    done = process_one(db, evaluator, "worker-b")
    assert done.id == second["id"] and done.gpu == "5" and evaluator.ran == ["5"] and evaluator.asked == [{"3"}]
    assert recover_stale(db) == 1 and db.get(Submission, first["id"]).gpu is None
    assert process_one(db, evaluator, "worker-b").gpu == "3"


def test_a_gpu_taken_meanwhile_is_not_handed_out_again(client, db, participant):
    class Stale(Picking):
        def free_gpus(self, held=()):
            return ["3"]  # read before another slot took GPU 3

    running, waiting = upload(client).json(), upload(client).json()
    row = db.get(Submission, running["id"])
    row.status, row.worker_id, row.gpu, row.heartbeat_at = "running", "worker-a", "3", now()
    db.commit()
    assert process_one(db, Stale([]), "worker-b") is None
    assert db.get(Submission, waiting["id"]).status == "queued"


def test_the_admin_page_says_why_the_queue_waits_for_a_gpu(client, db, participant, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app import worker

    class Busy(Picking):
        def free_gpus(self, held=()):
            self.gpu_note = "비어 있는 GPU가 없어 채점을 기다립니다"
            return []

    submitted = upload(client).json()
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    monkeypatch.setattr(worker, "get_evaluator", lambda: Busy([]))
    worker.run_forever(once=True)
    assert db.scalars(select(Worker)).one().detail == "ready\n비어 있는 GPU가 없어 채점을 기다립니다"
    assert db.get(Submission, submitted["id"]).status == "queued"


def test_only_waiting_submissions_have_a_place_in_line(client, db, participant):
    running, waiting = upload(client).json(), upload(client).json()
    row = db.get(Submission, running["id"])
    row.status, row.worker_id = "running", "worker-a"
    db.commit()
    entries = {entry["id"]: entry for entry in client.get("/api/submissions/me").json()["entries"]}
    assert entries[running["id"]]["queue_position"] is None and entries[waiting["id"]]["queue_position"] == 1


def test_slots_are_threads_of_their_own_and_one_that_stops_starts_again(monkeypatch):
    import threading
    from app import worker

    threads, runs, release = [], [], threading.Event()

    class Recorded(threading.Thread):
        def start(self):
            threads.append(self)
            super().start()

    def run_forever(worker_id, run_uid):
        runs.append((worker_id, run_uid))
        if not (worker_id == "gpu-box-2" and runs.count(("gpu-box-2", 64001)) == 1):  # slot 2's first thread stops at once
            release.wait(5)

    def sleep(seconds):
        if len(threads) == 3:
            threads[1].join(5)
        else:
            raise SystemExit(0)  # the container is stopped

    monkeypatch.setattr(worker.threading, "Thread", Recorded)
    monkeypatch.setattr(worker, "run_forever", run_forever)
    monkeypatch.setattr(worker.time, "sleep", sleep)
    monkeypatch.setattr(worker.signal, "signal", lambda *args: None)
    monkeypatch.setenv("WORKER_NAME", "gpu-box")
    monkeypatch.setenv("EVAL_SANDBOX_RUN_UID", "64000")
    try:
        with pytest.raises(SystemExit):
            worker.run_slots(3)
    finally:
        release.set()
    for thread in threads:
        thread.join(5)
    assert [thread.name for thread in threads] == ["slot-1", "slot-2", "slot-3", "slot-2"]
    assert all(thread.daemon for thread in threads)  # they end with the process
    assert sorted(runs) == [("gpu-box-1", 64000), ("gpu-box-2", 64001), ("gpu-box-2", 64001), ("gpu-box-3", 64002)]


def test_a_slot_reports_under_its_own_name_and_its_evaluator_runs_as_its_own_user(db, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app import worker

    evaluator = MockEvaluator()
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    monkeypatch.setattr(worker, "get_evaluator", lambda: evaluator)
    worker.run_forever(once=True, worker_id="gpu-box-3", run_uid=64002)
    assert evaluator.run_uid == 64002 and db.scalars(select(Worker.id)).all() == ["gpu-box-3"]


def test_the_worker_hands_the_settings_to_its_evaluator_before_each_check(db, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app import worker

    seen = []

    class Watching(Evaluator):
        name = "mock"

        def configure(self, settings):
            seen.append(settings.eval_isolation)

        def ready(self):
            return False, "waiting"

    db.get(Settings, 1).eval_isolation = False
    db.commit()
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    monkeypatch.setattr(worker, "get_evaluator", Watching)
    worker.run_forever(once=True)
    assert seen == [False] and db.scalars(select(Worker)).one().detail == "waiting"


def test_real_predictions_are_scored_against_hidden_labels(client, db, participant):
    labels = pd.DataFrame({"id": ["T1", "T2", "T3", "T4"], "label": ["a", "b", "a", "b"],
                           "partition": ["public", "public", "private", "private"]})

    def answers():
        return labels, ["a", "b"]

    class Fixed(Evaluator):
        name = "mock"

        def __init__(self, csv):
            self.csv = csv

        def run(self, submission, zip_path, tick):
            tick()
            return Outcome(ok=True, predictions=self.csv, log="container output")

    upload(client)
    good = process_one(db, Fixed(b"id,label\nT4,a\nT1,a\nT2,b\nT3,b\n"), "worker-a", answers)
    assert (good.status, good.public_score, good.private_score) == ("succeeded", 1.0, 0.0)
    assert json.loads(good.predictions) == ["a", "b", "b", "a"]

    upload(client)
    bad = process_one(db, Fixed(b"id,label\nT1,a\nT2,SECRET-SEQUENCE\nT3,b\n"), "worker-a", answers)
    assert (bad.status, bad.failure_code) == ("failed", "output_invalid")
    # The message reports codes and counts only; echoing values could leak hidden evaluation input.
    assert "SECRET" not in bad.error_message and "[E502]" in bad.error_message and "[E401]" in bad.error_message
    assert "SECRET-SEQUENCE" in bad.log_tail and "container output" in bad.log_tail and bad.counted

    upload(client)
    broken = process_one(db, Fixed(b"id,label\nT1,a\nT2,b\nT3,a\nT4,b\n"), "worker-a", lambda: (labels, []))
    assert (broken.status, broken.failure_code, broken.counted) == ("failed", "system_error", False)
    assert "E901" in broken.log_tail


def test_frozen_board_keeps_scoring_but_hides_new_ranks(client, db, participant, organizer):
    db.get(Settings, 1).frozen = True
    db.commit()
    upload(client, mock_zip(public=0.6, private=0.6))
    assert process_one(db, MOCK, "worker-a").public_score == 0.6
    assert client.get("/api/leaderboard").json()["entries"] == []
    client.cookies.set("admin_session", organizer)
    assert client.post("/api/admin/leaderboard/recalculate").status_code == 409
    assert client.patch("/api/admin/competition", json={"frozen": False}).status_code == 200
    assert client.get("/api/leaderboard").json()["entries"][0]["score"] == 0.6
    assert client.post("/api/admin/leaderboard/recalculate").status_code == 200


def test_ban_removes_team_from_board(client, db, participant, organizer):
    upload(client)
    process_one(db, MOCK, "worker-a")
    session = client.cookies.get("admin_session")
    client.cookies.set("admin_session", organizer)
    assert client.patch(f"/api/admin/users/{participant['id']}", json={"banned": True}).status_code == 200
    assert client.get("/api/leaderboard").json()["entries"] == []
    client.cookies.set("admin_session", session)
    assert client.get("/api/auth/me").status_code == 403


def test_ties_go_to_the_earlier_submission_and_teams_appear_once(client, db, participant):
    mate = add_account(db, participant["team_name"], "teammate")
    other = add_account(db, "Other team", "otherteam")
    scored(db, participant, 0.8, 0.5, seconds=5)
    scored(db, other, 0.8, 0.5, seconds=1)
    scored(db, mate, 0.7, 0.5, seconds=2)
    scored(db, other, 0.95, 0.5, seconds=3, evaluator="docker")  # scored by another evaluator: ignored
    rebuild(db)
    db.commit()
    entries = client.get("/api/leaderboard").json()["entries"]
    assert [(e["rank"], e["team"], e["score"], e["submissions"]) for e in entries] == [
        (1, "Other team", 0.8, 1), (2, participant["team_name"], 0.8, 2)]


def test_ties_go_to_the_smaller_zip_then_the_earlier_submission(client, db, participant):
    from app.files import best_public_id
    other = add_account(db, "Other team", "otherteam")
    third = add_account(db, "Third team", "thirdteam")
    scored(db, participant, 0.8, 0.1, seconds=1, zip_bytes=900)
    smaller = scored(db, participant, 0.8, 0.9, seconds=4, zip_bytes=500)  # later, but the smaller ZIP
    scored(db, other, 0.8, 0.5, seconds=0, zip_bytes=700)                  # earliest, but a bigger ZIP
    scored(db, third, 0.8, 0.5, seconds=2, zip_bytes=500)                  # same size, submitted earlier
    rebuild(db)
    db.commit()
    entries = client.get("/api/leaderboard").json()["entries"]
    assert [e["team"] for e in entries] == ["Third team", participant["team_name"], "Other team"]
    # The team's representative submission (kept ZIP, final submission) follows the same rule.
    assert best_public_id(db, participant["team_id"]) == smaller.id
    rebuild(db, "private")
    assert db.scalar(select(LeaderboardEntry.score).where(
        LeaderboardEntry.board == "private", LeaderboardEntry.team_id == participant["team_id"])) == 0.9


def graded(db, user, public, private, grading, **options):
    """A scored submission that took `grading` seconds from running to succeeded."""
    row = scored(db, user, public, private, **options)
    row.started_at = row.finished_at - timedelta(seconds=grading)
    db.flush()
    return row


def test_grading_time_is_shown_but_never_breaks_a_tie(client, db, participant):
    other = add_account(db, "Other team", "otherteam")
    third = add_account(db, "Third team", "thirdteam")
    untimed = add_account(db, "Untimed team", "untimedteam")
    graded(db, participant, 0.8, 0.5, 12.346, seconds=1, zip_bytes=500)
    graded(db, other, 0.8, 0.5, 12.345, seconds=5, zip_bytes=900)  # 1 ms faster, but a bigger ZIP
    graded(db, third, 0.7, 0.4, 1.0, zip_bytes=100)                # the fastest, but lower scores
    scored(db, untimed, 0.8, 0.5, zip_bytes=100)                   # no start time recorded, the smallest ZIP
    rebuild(db)
    rebuild(db, "private")
    db.commit()
    expected = [(1, "Untimed team", None), (2, participant["team_name"], 12.346), (3, "Other team", 12.345),
                (4, "Third team", 1.0)]
    entries = client.get("/api/leaderboard").json()["entries"]
    assert [(e["rank"], e["team"], e["grading_seconds"]) for e in entries] == expected
    # The final board ignores grading time the same way.
    db.get(Settings, 1).finalized = True
    db.commit()
    entries = client.get("/api/leaderboard?board=final").json()["entries"]
    assert [(e["rank"], e["team"], e["grading_seconds"]) for e in entries] == expected


def test_team_keeps_the_smaller_zip_of_its_equal_best_submissions_however_slow(client, db, participant):
    from app.files import best_public_id
    mate = add_account(db, participant["team_name"], "teammate")
    slower = graded(db, participant, 0.8, 0.1, 125.1, seconds=1, zip_bytes=500)
    faster = graded(db, mate, 0.8, 0.9, 12.3, seconds=4, zip_bytes=900)  # graded faster, but a bigger ZIP
    graded(db, participant, 0.7, 0.5, 1.0, seconds=2, zip_bytes=500)     # the fastest, but a lower score
    rebuild(db)
    rebuild(db, "private")
    db.commit()
    assert best_public_id(db, participant["team_id"]) == slower.id
    entry, = client.get("/api/leaderboard").json()["entries"]
    assert (entry["score"], entry["grading_seconds"], entry["submissions"]) == (0.8, 125.1, 3)
    assert db.scalar(select(LeaderboardEntry.score).where(LeaderboardEntry.board == "private")) == 0.1
    history = {s["id"]: s for s in client.get("/api/submissions/me").json()["entries"]}
    assert (history[slower.id]["is_best_public"], history[slower.id]["grading_seconds"]) == (True, 125.1)
    assert (history[faster.id]["is_best_public"], history[faster.id]["grading_seconds"]) == (False, 12.3)


def test_grading_time_covers_running_to_succeeded_only(client, db, participant):
    done = upload(client, mock_zip(public=0.5)).json()
    failed = upload(client, mock_zip(fail="runtime_error")).json()
    assert done["grading_seconds"] is None  # still queued
    process_one(db, MOCK, "worker-a")
    process_one(db, MOCK, "worker-a")
    row = db.get(Submission, done["id"])
    row.created_at, row.started_at = row.finished_at - timedelta(minutes=10), row.finished_at - timedelta(seconds=2.5)
    db.commit()
    history = {s["id"]: s for s in client.get("/api/submissions/me").json()["entries"]}
    assert history[done["id"]]["grading_seconds"] == 2.5  # the ten minutes in the queue are not counted
    assert history[failed["id"]]["status"] == "failed" and history[failed["id"]]["grading_seconds"] is None


@pytest.mark.parametrize("selection,expected", [
    ("best_public", [("Other team", 0.6), ("Protein Learners", 0.3)]),
    ("best_private", [("Protein Learners", 0.9), ("Other team", 0.6)]),
])
def test_final_board_follows_the_configured_rule(client, db, participant, organizer, selection, expected):
    other = add_account(db, "Other team", "otherteam")
    scored(db, participant, 0.8, 0.3)   # best Public of the team
    scored(db, participant, 0.5, 0.9)   # best Private of the team
    scored(db, other, 0.7, 0.6)
    db.commit()
    pending = upload(client).json()
    client.cookies.set("admin_session", organizer)
    assert client.get("/api/leaderboard?board=final").status_code == 403
    assert client.patch("/api/admin/competition", json={"final_selection": selection}).status_code == 200
    assert client.post("/api/admin/leaderboard/finalize").status_code == 409  # still open
    assert client.patch("/api/admin/competition", json={"is_open": False}).status_code == 200
    blocked = client.post("/api/admin/leaderboard/finalize")
    assert blocked.status_code == 409 and "1건" in blocked.json()["detail"]  # a submission is still queued
    assert process_one(db, MockEvaluator(), "worker-a").id == pending["id"]
    db.get(Submission, pending["id"]).public_score = 0.1
    db.get(Submission, pending["id"]).private_score = 0.1
    db.commit()
    assert client.post("/api/admin/leaderboard/finalize").status_code == 200
    final = client.get("/api/leaderboard?board=final").json()["entries"]
    assert [(e["team"], e["score"]) for e in final] == expected
    assert client.patch("/api/admin/competition", json={"is_open": True}).status_code == 409
    assert client.patch(f"/api/admin/users/{participant['id']}", json={"banned": True}).status_code == 409


def test_worker_waits_while_the_contract_and_dataset_disagree(db, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from prediction_validator import load_contract
    from app import worker
    from app.config import PREDICTION_CONTRACT
    from app.scoring.predictions import contract_problem

    expected = load_contract(PREDICTION_CONTRACT).expected_rows
    assert contract_problem([f"TEST_{i:06d}" for i in range(expected)]) is None

    class Docker(Evaluator):
        name = "docker"

    # The test labels have 4 evaluation IDs, not the contract's expected_rows.
    monkeypatch.setattr(worker, "get_evaluator", Docker)
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    monkeypatch.setenv("WORKER_NAME", "contract-check")
    upload_free = db.scalar(select(Submission.id))
    worker.run_forever(once=True)
    row = db.get(Worker, "contract-check")
    assert row.ready is False and "E903" in row.detail and upload_free is None


def test_rescore_reaches_every_real_evaluator(db, participant, monkeypatch):
    from app import dataset, worker

    labels = pd.DataFrame({"id": ["T1", "T2", "T3", "T4"], "label": ["a", "b", "a", "b"],
                           "partition": ["public", "public", "private", "private"]})
    monkeypatch.setattr(dataset, "answers", lambda: (labels, ["a", "b"]))
    monkeypatch.setattr(worker, "EVALUATOR", "sandbox")
    before = scored(db, participant, 0.0, 0.0, evaluator="docker")  # scored before a switch to sandbox
    current = scored(db, participant, 0.0, 0.0, evaluator="sandbox")
    fake = scored(db, participant, 0.9, 0.9)                          # mock: no predictions to rescore
    before.predictions = current.predictions = json.dumps(["a", "b", "a", "b"])
    db.commit()
    assert worker.rescore(db) == 2
    assert (before.public_score, before.private_score) == (1.0, 1.0)
    assert (current.public_score, current.private_score) == (1.0, 1.0)
    assert (fake.public_score, fake.private_score) == (0.9, 0.9)
