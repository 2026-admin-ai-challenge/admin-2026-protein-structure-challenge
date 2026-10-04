import io
import json
import os
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

os.environ.setdefault("SECRET_KEY", "test-only-secret-with-more-than-thirty-two-characters")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ["EVALUATOR"] = "mock"
os.environ["MOCK_DELAY_SECONDS"] = "0"
_scratch = tempfile.TemporaryDirectory(prefix="admin-api-test-")
_data_dir = Path(_scratch.name) / "data"
os.environ["DATA_DIR"] = str(_data_dir)
os.environ["SUBMISSION_DIR"] = str(Path(_scratch.name) / "submissions")
os.environ["EVAL_WORK_DIR"] = str(Path(_scratch.name) / "eval-work")
public = _data_dir / "public"
private = _data_dir / "private"
public.mkdir(parents=True)
private.mkdir()
(public / "metadata.json").write_text(json.dumps({
    "version": "test-1", "labels": ["1.10", "3.40"],
    "files": {"train.csv": {"rows": 2, "bytes": 1}, "test.csv": {"rows": 4, "bytes": 1}},
}))
(public / "train.csv").write_text("id,sequence,label\nTRAIN_1,AAAA,1.10\nTRAIN_2,CCCC,3.40\n")
# Evaluation input left over from the CSV prototype. It must never be downloadable.
(public / "test.csv").write_text("id,sequence\nTEST_1,AAAA\nTEST_2,CCCC\nTEST_3,GGGG\nTEST_4,TTTT\n")
(public / "test_features.csv").write_text("id,value\n")
(private / "labels.csv").write_text("id,label,partition\nTEST_1,1.10,public\nTEST_2,3.40,public\nTEST_3,1.10,private\nTEST_4,3.40,private\n")
for filename in ["train_features.csv", "validation_split.csv"]:
    (public / filename).write_text("id,value\n")
for filename in ["class_distribution.png", "sequence_length_distribution.png"]:
    (public / filename).write_bytes(b"placeholder image")
for filename in ["train_structures.zip", "test_structures.zip", "starter_kit.zip"]:
    with zipfile.ZipFile(public / filename, "w"):
        pass
with zipfile.ZipFile(public / "baseline_code.zip", "w") as archive:
    for filename in ["baseline.py", "structure_features.py", "README.md", "structure-format.md", "requirements.txt"]:
        archive.writestr(filename, "# Test-only code archive\n")
    archive.writestr("baseline.ipynb", json.dumps({"cells": [{"cell_type": "code", "outputs": []}]}))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.accounts import create_user
from app.db import Base, get_db
from app.main import app
from app.models import Competition, Settings, Team, User
from app.security import hasher, token_for

HEADERS = {"X-Requested-With": "ADMIN-Challenge"}


def make_zip(files=None, extra=None):
    """A valid submission ZIP by default; pass `files` to replace its contents."""
    if files is None:
        files = {"inference.py": "print('predict')\n", "train.py": "print('train')\n", "requirements.txt": "numpy\n",
                 "model/weights.bin": b"\x00" * 16}
    files = {**files, **(extra or {})}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def upload(client, content=None, name="code.zip"):
    # The browser URL-encodes the file name, which is how non-ASCII names travel in a header.
    return client.post("/api/submissions", content=make_zip() if content is None else content,
                       headers={"X-Filename": quote(name), "Content-Type": "application/zip"})


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        session.add(Competition(id=1))
        session.flush()
        stamp = datetime.now(timezone.utc)
        session.add(Settings(id=1, is_open=True, start_time=stamp - timedelta(hours=1), end_time=stamp + timedelta(hours=1),
                             dataset_version="test-1"))
        session.commit()
        yield session
    engine.dispose()


@pytest.fixture
def client(db):
    def override():
        yield db
    app.dependency_overrides[get_db] = override
    c = TestClient(app, headers=HEADERS)
    yield c
    c.close()
    app.dependency_overrides.clear()


def add_account(db, team_name, username, password="Temp-Password-42"):
    team = db.query(Team).filter_by(name=team_name).first()
    if not team:
        team = Team(name=team_name)
        db.add(team)
        db.flush()
    user, _ = create_user(db, team, username, password=password)
    db.commit()
    return {"id": user.id, "username": username, "password": password, "team_id": team.id, "team_name": team_name}


def login(client, account):
    response = client.post("/api/auth/login", json={"username": account["username"], "password": account["password"]})
    assert response.status_code == 200, response.text
    return client.cookies.get("admin_session")


@pytest.fixture
def participant(client, db):
    """An organizer-issued team account, already logged in on `client`."""
    account = add_account(db, "Protein Learners", "teamlearner")
    login(client, account)
    return account


@pytest.fixture
def organizer(db):
    team = Team(name="Organizers")
    db.add(team)
    db.flush()
    user = User(username="organizer", password_hash=hasher.hash("longpassword123"), display_name="Organizer", team_id=team.id, role="ADMIN")
    db.add(user)
    db.commit()
    return token_for(user)
