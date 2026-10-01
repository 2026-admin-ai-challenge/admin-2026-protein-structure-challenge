import os,tempfile,json,zipfile
from pathlib import Path
from datetime import datetime,timezone,timedelta
os.environ.setdefault("SECRET_KEY","test-only-secret-with-more-than-thirty-two-characters")
os.environ.setdefault("DATABASE_URL","sqlite://")
_test_data=tempfile.TemporaryDirectory(prefix="admin-api-test-")
_data_dir=Path(_test_data.name)
os.environ["DATA_DIR"]=str(_data_dir)
public=_data_dir/"public";private=_data_dir/"private"
public.mkdir();private.mkdir()
(public/"metadata.json").write_text(json.dumps({"labels":["1.10","3.40"]}))
(public/"train.csv").write_text("id,sequence,label\nTRAIN_1,AAAA,1.10\nTRAIN_2,CCCC,3.40\n")
(public/"test.csv").write_text("id,sequence\nTEST_1,AAAA\nTEST_2,CCCC\nTEST_3,GGGG\nTEST_4,TTTT\n")
(public/"sample_submission.csv").write_text("id,label\nTEST_1,1.10\nTEST_2,1.10\nTEST_3,1.10\nTEST_4,1.10\n")
(private/"labels.csv").write_text("id,label,partition\nTEST_1,1.10,public\nTEST_2,3.40,public\nTEST_3,1.10,private\nTEST_4,3.40,private\n")
for filename in ["train_features.csv","test_features.csv","validation_split.csv"]:
    (public/filename).write_text("id,value\n")
for filename in ["class_distribution.png","sequence_length_distribution.png"]:
    (public/filename).write_bytes(b"placeholder image")
for filename in ["train_structures.zip","test_structures.zip","starter_kit.zip"]:
    with zipfile.ZipFile(public/filename,"w"):
        pass
with zipfile.ZipFile(public/"baseline_code.zip","w") as archive:
    for filename in ["baseline.py","structure_features.py","README.md","structure-format.md","requirements.txt"]:
        archive.writestr(filename,"# Test-only code archive\n")
    archive.writestr("baseline.ipynb",json.dumps({"cells":[{"cell_type":"code","outputs":[]}] }))
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from app.db import Base,get_db
from app.models import Competition,Settings,User,Team
from app.main import app
from app.security import hasher,token_for

@pytest.fixture
def db():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine,expire_on_commit=False)() as session:
        session.add(Competition(id=1));session.flush();session.add(Settings(id=1,is_open=True,start_time=datetime.now(timezone.utc)-timedelta(hours=1),end_time=datetime.now(timezone.utc)+timedelta(hours=1)));session.commit()
        yield session
    engine.dispose()

@pytest.fixture
def client(db):
    def override(): yield db
    app.dependency_overrides[get_db]=override
    c=TestClient(app,headers={"X-Requested-With":"ADMIN-Challenge"})
    yield c
    c.close();app.dependency_overrides.clear()

@pytest.fixture
def participant(client):
    r=client.post('/api/auth/register',json={"email":"participant@example.com","password":"VeryStrongPassword123","display_name":"Participant","team_name":"Protein Learners"})
    assert r.status_code==201,r.text
    return r.json()

@pytest.fixture
def organizer(db):
    team=Team(name="Organizers");db.add(team);db.flush()
    user=User(email="organizer@example.com",password_hash=hasher.hash("longpassword123"),display_name="Organizer",team_id=team.id,role="ADMIN");db.add(user);db.commit()
    return token_for(user)
