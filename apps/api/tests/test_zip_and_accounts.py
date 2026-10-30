import io
import stat
import subprocess
import sys
import zipfile

import pytest
from sqlalchemy import select

from app import zipcheck
from app.accounts import generate_sheet, sync_sheet
from app.evaluators import docker as docker_evaluator
from app.models import AuditLog, Submission, Team, User
from app.security import verify
from app.zipcheck import ZipRejected
from conftest import make_zip

VALID = {"inference.py": "x", "train.py": "x", "requirements.txt": "numpy\n", "model/w.bin": "x"}


def write(tmp_path, content):
    path = tmp_path / "code.zip"
    path.write_bytes(content)
    return path


def raw_zip(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for info, content in entries:
            archive.writestr(info, content)
    return buffer.getvalue()


def test_valid_zip_is_measured(tmp_path):
    report = zipcheck.inspect(write(tmp_path, make_zip({**VALID, "model/sub/extra.bin": b"12345"})))
    assert report == {"entries": 5, "unpacked_bytes": 3 + 6 + 5, "packages": ["numpy"]}


@pytest.mark.parametrize("files", [
    {"inference.py": "x", "train.py": "x", "requirements.txt": "x"},                     # no model directory
    {"inference.py": "x", "train.py": "x", "requirements.txt": "x", "model": "a file"},  # model is a file
    {"src/inference.py": "x", "train.py": "x", "requirements.txt": "x", "model/w": "x"},
    {"inference.py": "x", "requirements.txt": "x", "model/w": "x"},                      # no train.py
    {**VALID, "/etc/passwd": "x"},
    {**VALID, "C:/Windows/x": "x"},
    {**VALID, "model/../../x": "x"},
    {**VALID, "a\\..\\..\\x": "x"},
])
def test_structure_and_path_rules(tmp_path, files):
    with pytest.raises(ZipRejected):
        zipcheck.inspect(write(tmp_path, make_zip(files)))


def test_symlinks_duplicates_and_limits(tmp_path):
    link = zipfile.ZipInfo("model/link")
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    base = [(zipfile.ZipInfo(name), content) for name, content in VALID.items()]
    with pytest.raises(ZipRejected, match="심볼릭"):
        zipcheck.inspect(write(tmp_path, raw_zip(base + [(link, "/etc/passwd")])))
    with pytest.warns(UserWarning):
        duplicated = raw_zip(base + [(zipfile.ZipInfo("inference.py"), "again")])
    with pytest.raises(ZipRejected, match="두 번"):
        zipcheck.inspect(write(tmp_path, duplicated))
    path = write(tmp_path, make_zip({**VALID, "model/big.bin": b"0" * 5000}))
    with pytest.raises(ZipRejected, match="전체 크기"):
        zipcheck.inspect(path, max_total=4000)
    with pytest.raises(ZipRejected, match="너무 많습니다"):
        zipcheck.inspect(path, max_entries=3)
    # The limit is enforced on real bytes while unpacking, not only on the header.
    with pytest.raises(ZipRejected, match="전체 크기"):
        zipcheck.safe_extract(path, tmp_path / "out", max_total=4000)


def test_safe_extract_writes_only_inside_destination(tmp_path):
    destination = tmp_path / "out"
    written = zipcheck.safe_extract(write(tmp_path, make_zip({**VALID, "model/sub/deep.bin": b"abc"})), destination)
    assert written == 12
    assert sorted(p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()) == [
        "inference.py", "model/sub/deep.bin", "model/w.bin", "requirements.txt", "train.py"]
    assert (destination / "model/sub/deep.bin").read_bytes() == b"abc"


def test_container_is_isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(docker_evaluator, "WORK_DIR", tmp_path)
    monkeypatch.setattr(docker_evaluator, "WORK_HOST_DIR", tmp_path)
    monkeypatch.setattr(docker_evaluator, "INPUT_HOST_DIR", "/srv/eval-input")
    command = docker_evaluator.build_command("admin-eval-1", tmp_path / "s" / "submission", tmp_path / "s" / "output")
    joined = " ".join(command)
    for flag in ["--network none", "--read-only", "--user 65534:65534", "--cap-drop ALL", "no-new-privileges",
                 "--pids-limit", "--memory", "--cpus", "/srv/eval-input:/input:ro", "/submission:ro", "/output:rw"]:
        assert flag in joined
    assert "docker.sock" not in joined and "labels" not in joined and "DATABASE_URL" not in joined
    assert command[command.index("timeout") + 2] == "615"  # in-container timer: 10 minutes plus grace
    timer = command.index("timeout")
    assert command[timer + 3:timer + 7] == ["sh", "-c", docker_evaluator.STEP_EXIT, "sh"]
    assert command[timer + 7:] == docker_evaluator.COMMAND.split()


@pytest.mark.parametrize("exit_code, reported", [(0, 0), (3, 3), (125, 1), (255, 1)])
def test_submission_cannot_exit_like_docker_or_ssh(exit_code, reported):
    # 125 (docker) and 255 (ssh) mean a server fault, which is not counted against the team.
    done = subprocess.run(["sh", "-c", docker_evaluator.STEP_EXIT, "sh",
                           sys.executable, "-c", f"import sys; sys.exit({exit_code})"])
    assert done.returncode == reported


def test_a_killed_submission_keeps_its_exit_code():
    # 137 is still the OOM killer, not a plain failure.
    done = subprocess.run(["sh", "-c", docker_evaluator.STEP_EXIT, "sh",
                           sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"])
    assert done.returncode == 137


def test_generated_sheet_has_ten_character_ids(db):
    lines = generate_sheet(10).strip().splitlines()
    assert lines[0] == "team_name,username,password,display_name" and len(lines) == 11
    usernames = [line.split(",")[1] for line in lines[1:]]
    assert len(set(usernames)) == 10 and all(len(u) == 10 and u.isalnum() and u == u.lower() for u in usernames)
    assert all(len(line.split(",")[2]) == 12 for line in lines[1:])


def test_account_sheet_is_the_editable_source_of_truth(db):
    sheet = "team_name,username,password,display_name\nTeam 01,abcdefgh23,First-Pass-123,Team 01\nTeam 02,zyxwvuts45,Second-Pass-123,Team 02\n"
    assert sync_sheet(db, sheet) == {"created": 2, "updated": 0, "unchanged": 0, "blocked": 0, "renamed_teams": 0}
    db.commit()
    first = db.scalar(select(User).where(User.username == "abcdefgh23"))
    assert verify("First-Pass-123", first.password_hash) and "First-Pass-123" not in first.password_hash
    db.add(Submission(user_id=first.id, team_id=first.team_id, filename="code.zip", status="queued"))
    assert sync_sheet(db, sheet)["unchanged"] == 2

    # Edit the sheet: new password and a real team name for the first account.
    edited = sheet.replace("First-Pass-123", "Changed-Pass-456").replace("Team 01,abc", "단백질팀,abc")
    summary = sync_sheet(db, edited)
    db.commit()
    assert (summary["updated"], summary["renamed_teams"]) == (1, 1)
    assert verify("Changed-Pass-456", first.password_hash) and not verify("First-Pass-123", first.password_hash)
    assert db.get(Team, first.team_id).name == "단백질팀"
    assert db.scalar(select(Submission.team_id)) == first.team_id  # submissions stayed with the team

    only_first = "\n".join(edited.splitlines()[:2]) + "\n"
    assert sync_sheet(db, only_first)["blocked"] == 0
    assert sync_sheet(db, only_first, exclusive=True)["blocked"] == 1
    assert db.scalar(select(User).where(User.username == "zyxwvuts45")).banned is True
    assert sync_sheet(db, edited)["updated"] == 1  # listing the account again unblocks it
    log = db.scalars(select(AuditLog).where(AuditLog.action == "accounts.sync")).all()
    assert log and all("Pass" not in (entry.detail or "") for entry in log)


def test_sheet_team_names_match_like_sign_in(db):
    sync_sheet(db, "team_name,username,password\nTeam 01,abcdefgh23,First-Pass-123\n")
    team_id = db.scalar(select(User.team_id).where(User.username == "abcdefgh23"))
    # A second account spelled with other case or spacing joins the same team, whose
    # sign-in name takes the sheet's spelling.
    summary = sync_sheet(db, "team_name,username,password\nTEAM  01,zyxwvuts45,Second-Pass-123\n")
    assert (summary["created"], summary["renamed_teams"]) == (1, 1)
    assert db.scalar(select(User.team_id).where(User.username == "zyxwvuts45")) == team_id
    assert [team.name for team in db.scalars(select(Team))] == ["TEAM  01"]


@pytest.mark.parametrize("sheet", [
    "username,password\nabcdefgh23,First-Pass-123\n",
    # One team spelled two ways would make its sign-in name flip on every sync.
    "team_name,username,password\nTeam 01,abcdefgh23,First-Pass-123\nteam 01,zyxwvuts45,Other-Pass-123\n",
    "team_name,username,password\nTeam 01,ab,First-Pass-123\n",
    "team_name,username,password\nTeam 01,abcdefgh23,short\n",
    "team_name,username,password\nTeam 01,abcdefgh23,First-Pass-123\nTeam 02,abcdefgh23,Other-Pass-123\n",
])
def test_bad_sheets_are_rejected(db, sheet):
    with pytest.raises(ValueError):
        sync_sheet(db, sheet)
