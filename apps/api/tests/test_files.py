import hashlib
import json

from sqlalchemy import select

from app import files, storage
from app.evaluators.mock import MockEvaluator
from app.models import AuditLog, Submission, SubmissionFile
from app.worker import process_one
from conftest import add_account, login, make_zip, upload

MOCK = MockEvaluator()


def mock_zip(**controls):
    return make_zip(extra={"mock.json": json.dumps(controls)})


def test_upload_writes_a_file_record_sharing_team_and_submission(client, db, participant):
    content = make_zip()
    body = upload(client, content, name="first model.zip").json()
    stored = db.scalar(select(SubmissionFile))
    assert (stored.team_id, stored.submission_id, stored.uploaded_by) == (participant["team_id"], body["id"], participant["id"])
    assert (stored.original_filename, stored.size_bytes) == ("first model.zip", len(content))
    assert stored.sha256 == hashlib.sha256(content).hexdigest() and stored.deleted_at is None
    assert storage.path_for(stored.storage_key).read_bytes() == content
    # The submission still reports its file details, now read through the file record.
    assert (body["sha256"], body["size_bytes"], body["file_deleted"]) == (stored.sha256, len(content), False)
    assert db.get(Submission, body["id"]).file.id == stored.id
    # A refused upload leaves neither a submission nor a file record.
    assert upload(client, b"not a zip").status_code == 422
    assert len(db.scalars(select(SubmissionFile)).all()) == 1


def test_team_storage_usage_and_listing(client, db, participant, organizer):
    first = make_zip()
    upload(client, first)
    mate = add_account(db, participant["team_name"], "teammate")
    other = add_account(db, "Other team", "otherteam")
    login(client, mate)
    second = make_zip(extra={"model/extra.bin": b"x" * 500})
    upload(client, second)
    login(client, other)
    upload(client, first)
    assert client.get("/api/admin/files").status_code == 403

    client.cookies.set("admin_session", organizer)
    listing = client.get("/api/admin/files").json()
    assert len(listing["files"]) == 3 and listing["total_bytes"] == 2 * len(first) + len(second)
    usage = {team["team"]: (team["files"], team["storage_bytes"]) for team in listing["teams"]}
    assert usage == {"Protein Learners": (2, len(first) + len(second)), "Other team": (1, len(first))}
    assert {f["uploaded_by"] for f in listing["files"]} == {"teamlearner", "teammate", "otherteam"}
    only = client.get(f"/api/admin/files?team_id={other['team_id']}").json()["files"]
    assert [f["team"] for f in only] == ["Other team"]
    teams = {team["name"]: team for team in client.get("/api/admin/teams").json()}
    assert (teams["Protein Learners"]["files"], teams["Protein Learners"]["storage_bytes"]) == (2, len(first) + len(second))
    assert teams["Organizers"]["storage_bytes"] == 0


def test_only_organizers_download_and_it_is_logged(client, db, participant, organizer):
    content = make_zip()
    body = upload(client, content, name="모델 v1.zip").json()
    file_id = db.scalar(select(SubmissionFile.id))
    assert client.get(f"/api/admin/files/{file_id}/download").status_code == 403
    client.cookies.set("admin_session", organizer)
    response = client.get(f"/api/admin/files/{file_id}/download")
    assert response.status_code == 200 and response.content == content
    assert response.headers["content-type"] == "application/zip"
    assert f"team{participant['team_id']}-submission{body['id']}" in response.headers["content-disposition"]
    assert db.scalar(select(SubmissionFile.original_filename)) == "모델 v1.zip"
    assert client.get("/api/admin/files/9999/download").status_code == 404
    log = db.scalar(select(AuditLog).where(AuditLog.action == "file.download"))
    assert log.actor == "organizer" and log.target == f"file:{file_id}"


def test_delete_rules_and_record(client, db, participant, organizer):
    best = upload(client, mock_zip(public=0.9, private=0.9)).json()
    worse = upload(client, mock_zip(public=0.2, private=0.2)).json()
    waiting = upload(client, mock_zip(public=0.5)).json()
    process_one(db, MOCK, "worker-a")
    process_one(db, MOCK, "worker-a")
    ids = {row.submission_id: row.id for row in db.scalars(select(SubmissionFile))}
    session = client.cookies.get("admin_session")
    assert client.post(f"/api/admin/files/{ids[worse['id']]}/delete", json={"reason": "cleanup"}).status_code == 403

    client.cookies.set("admin_session", organizer)
    listed = {s["id"]: s for s in client.get("/api/admin/submissions").json()}
    assert listed[best["id"]]["on_leaderboard"] is True and listed[worse["id"]]["on_leaderboard"] is False
    assert listed[worse["id"]]["file_id"] == ids[worse["id"]]
    # The file behind the team's leaderboard score and a file still waiting to be scored are protected.
    blocked = client.post(f"/api/admin/files/{ids[best['id']]}/delete", json={"reason": "cleanup"})
    assert blocked.status_code == 409 and "순위" in blocked.json()["detail"]
    assert client.post(f"/api/admin/files/{ids[waiting['id']]}/delete", json={"reason": "cleanup"}).status_code == 409
    assert client.post(f"/api/admin/files/{ids[worse['id']]}/delete", json={"reason": " "}).status_code == 422

    stored = db.get(SubmissionFile, ids[worse["id"]])
    path = storage.path_for(stored.storage_key)
    assert path.exists()
    assert client.post(f"/api/admin/files/{stored.id}/delete", json={"reason": "디스크 정리"}).status_code == 200
    db.refresh(stored)
    assert not path.exists() and stored.deleted_at and (stored.deleted_by, stored.delete_reason) == ("organizer", "디스크 정리")
    assert client.post(f"/api/admin/files/{stored.id}/delete", json={"reason": "again"}).status_code == 409
    assert client.get(f"/api/admin/files/{stored.id}/download").status_code == 410
    detail = client.get(f"/api/admin/submissions/{worse['id']}").json()
    assert detail["file_deleted"] is True and detail["file_present"] is False and detail["file_delete_reason"] == "디스크 정리"
    # The score and the record stay; only the bytes are gone, and usage drops.
    assert detail["public_score"] == 0.2 and detail["sha256"] == stored.sha256
    usage = client.get("/api/admin/files").json()
    assert usage["teams"][0]["files"] == 2 and len(usage["files"]) == 3
    assert db.scalar(select(AuditLog).where(AuditLog.action == "file.delete")).actor == "organizer"

    client.cookies.set("admin_session", session)
    mine = {s["id"]: s for s in client.get("/api/submissions/me").json()["entries"]}
    assert mine[worse["id"]]["file_deleted"] is True and mine[worse["id"]]["public_score"] == 0.2
    assert client.get("/api/submissions/me").json()["used"] == 3  # deleting a file does not return an attempt


def test_deleted_file_cannot_be_scored_again(client, db, participant, organizer):
    failed = upload(client, mock_zip(fail="runtime_error")).json()
    process_one(db, MOCK, "worker-a")
    file_id = db.scalar(select(SubmissionFile.id))
    client.cookies.set("admin_session", organizer)
    assert client.post(f"/api/admin/files/{file_id}/delete", json={"reason": "잘못 올린 파일"}).status_code == 200
    again = client.post(f"/api/admin/submissions/{failed['id']}/requeue")
    assert again.status_code == 409 and "ZIP" in again.json()["detail"]


def test_verify_finds_missing_changed_and_orphan_files(client, db, participant, organizer, tmp_path, monkeypatch):
    # A storage directory of its own: other tests' ZIPs would otherwise count as orphans.
    monkeypatch.setattr(storage, "SUBMISSION_DIR", tmp_path)
    monkeypatch.setattr(files, "SUBMISSION_DIR", tmp_path)
    for marker in ["a", "b", "c"]:
        upload(client, make_zip(extra={"model/marker.txt": marker}))
    process_one(db, MOCK, "worker-a")
    process_one(db, MOCK, "worker-a")
    process_one(db, MOCK, "worker-a")
    client.cookies.set("admin_session", organizer)
    clean = client.post("/api/admin/files/verify").json()
    assert clean["ok"] is True and clean["checked"] == 3

    records = db.scalars(select(SubmissionFile).order_by(SubmissionFile.id)).all()
    storage.path_for(records[0].storage_key).unlink()                      # lost from disk
    with open(storage.path_for(records[1].storage_key), "ab") as tampered:  # changed on disk
        tampered.write(b"extra")
    orphan = storage.path_for("ffeeddccbbaa00112233445566778899")
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_bytes(b"left behind")
    try:
        report = client.post("/api/admin/files/verify").json()
        assert report["ok"] is False and report["checked"] == 3
        assert [m["file_id"] for m in report["missing"]] == [records[0].id]
        assert [m["submission_id"] for m in report["size_mismatch"]] == [records[1].submission_id]
        assert report["orphans"] == ["ff/ffeeddccbbaa00112233445566778899.zip"]
        hashed = files.check(db, with_hashes=True)
        assert hashed["hash_mismatch"] == [] and len(hashed["size_mismatch"]) == 1  # size is checked first
        log = db.scalars(select(AuditLog).where(AuditLog.action == "file.verify")).all()
        assert [entry.ok for entry in log] == [True, False]
    finally:
        orphan.unlink()
