import os,tempfile
from pathlib import Path
from datetime import datetime,timezone,timedelta
os.environ.setdefault("SECRET_KEY","test-only-secret-with-more-than-thirty-two-characters")
os.environ.setdefault("DATABASE_URL","sqlite://")
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
