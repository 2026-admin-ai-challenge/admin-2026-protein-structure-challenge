import json
from datetime import timedelta
from pathlib import Path
import pytest
from sqlalchemy import select
from app.models import User,Settings,Submission,Team,now
from app.config import DATA_DIR
from app.leaderboard import rebuild

def payload(): return (DATA_DIR/"public/sample_submission.csv").read_bytes()
def post(client,content=None,name="submission.csv"):
    return client.post('/api/submissions',files={"file":(name,content if content is not None else payload(),"text/csv")})
def test_auth_security(client,db,participant):
    stored=db.get(User,participant["id"])
    assert stored.password_hash.startswith('$argon2')
    assert 'password' not in json.dumps(client.get('/api/auth/me').json())
    assert client.get('/api/admin/users').status_code==403
    client.post('/api/auth/logout')
    assert client.get('/api/auth/me').status_code==401
    assert client.post('/api/auth/login',json={"email":"participant@example.com","password":"WrongPassword123"}).status_code==401
    assert client.post('/api/auth/login',json={"email":"participant@example.com","password":"VeryStrongPassword123"}).status_code==200
    cookie=client.cookies.get('admin_session');assert cookie

def test_submission_daily_limit_atomic_gate(client,db,participant):
    s=db.get(Settings,1);s.daily_limit=2;db.commit()
    assert post(client).json()['status']=='success'
    assert post(client,b'id,label\n').json()['status']=='invalid'
    assert post(client).status_code==429
    assert client.get('/api/submissions/me').json()['used_today']==2

def test_private_exposure_and_finalization(client,db,participant,organizer):
    r=post(client);assert r.status_code==200,r.text
    for path in ['/api/competition','/api/submissions/me','/api/leaderboard']:
        response=client.get(path);assert response.status_code==200
        for forbidden in ['private_score','partition','predictions','domain_id','homologous_superfamily']:
            assert forbidden not in response.text
    assert 'private_score' not in r.text
    assert client.get('/api/leaderboard?board=final').status_code==403
    assert client.get('/api/datasets/labels').status_code==404
    client.cookies.set('admin_session',organizer)
    assert client.get('/api/admin/submissions').json()[0]['private_score'] is not None
    assert client.post('/api/admin/leaderboard/finalize').status_code==409
    assert client.patch('/api/admin/competition',json={'is_open':False}).status_code==200
    assert client.post('/api/admin/leaderboard/finalize').status_code==200
    assert len(client.get('/api/leaderboard?board=final').json()['entries'])==1
    assert client.patch('/api/admin/competition',json={'is_open':True}).status_code==409
    assert post(client).status_code==403

def test_freeze_and_recalculate(client,db,participant,organizer):
    s=db.get(Settings,1);s.frozen=True;db.commit()
    assert post(client).json()['status']=='success'
    assert client.get('/api/leaderboard').json()['entries']==[]
    client.cookies.set('admin_session',organizer)
    assert client.patch('/api/admin/competition',json={'frozen':False}).status_code==200
    before=client.get('/api/leaderboard').json()['entries'][0]['score']
    assert client.post('/api/admin/leaderboard/recalculate').status_code==200
    assert client.get('/api/leaderboard').json()['entries'][0]['score']==before

def test_ban(client,db,participant,organizer):
    post(client);cookie=client.cookies.get('admin_session')
    client.cookies.set('admin_session',organizer)
    assert client.patch('/api/admin/users/'+str(participant['id']),json={'banned':True}).status_code==200
    assert client.get('/api/leaderboard').json()['entries']==[]
    client.cookies.set('admin_session',cookie)
    assert client.get('/api/auth/me').status_code==403

def test_time_gate_and_upload_size(client,db,participant):
    s=db.get(Settings,1);s.start_time=now()+timedelta(days=1);db.commit()
    assert post(client).status_code==403
    s.start_time=now()-timedelta(days=2);s.end_time=now()-timedelta(days=1);db.commit()
    assert post(client).status_code==403
    assert post(client,b'x'*(2*1024*1024+65537)).status_code==413

def test_csrf_and_auth_limits(client):
    assert client.post('/api/auth/logout',headers={'x-requested-with':'bad'}).status_code==403
    assert client.post('/api/auth/logout',headers={'origin':'https://evil.example'}).status_code==403
    for _ in range(10):
        assert client.post('/api/auth/login',json={'email':'no@example.com','password':'NotCorrect123'}).status_code==401
    assert client.post('/api/auth/login',json={'email':'no@example.com','password':'NotCorrect123'}).status_code==429

def test_ranking_ties_and_best_submission(client,db,participant):
    user=db.get(User,participant['id']);team=Team(name='Other team');db.add(team);db.flush()
    other=User(email='other@example.com',password_hash='unused',display_name='Other',team_id=team.id);db.add(other);db.flush()
    stamp=now()
    for u,value,delta in [(user,.8,0),(other,.8,1),(user,.7,2)]:
        db.add(Submission(user_id=u.id,team_id=u.team_id,filename='test.csv',public_score=value,private_score=value,status='success',created_at=stamp+timedelta(seconds=delta)))
    db.flush();rebuild(db);db.commit()
    entries=client.get('/api/leaderboard').json()['entries']
    assert entries[0]['team']==participant['team_name'] and entries[0]['score']==.8 and entries[0]['submissions']==2

@pytest.mark.parametrize('kind',['train','test','sample-submission','class-distribution','length-distribution','train-structures','test-structures','train-features','test-features','validation-split','starter-kit'])
def test_dataset_release_window_is_enforced_server_side(client,db,monkeypatch,kind):
    from datetime import datetime,timezone
    import app.main as main
    stamp=datetime(2026,10,24,0,0,tzinfo=timezone.utc)
    monkeypatch.setattr(main,'now',lambda:stamp)
    s=db.get(Settings,1)
    cases=[
        (True,None,None,False),
        (True,stamp+timedelta(seconds=1),stamp+timedelta(hours=8),False),
        (True,stamp,stamp+timedelta(hours=8),True),
        (True,stamp-timedelta(hours=8),stamp,False),
        (False,stamp-timedelta(hours=1),stamp+timedelta(hours=1),False),
    ]
    for opened,start,end,expected in cases:
        s.is_open=opened;s.start_time=start;s.end_time=end;db.commit()
        response=client.get('/api/datasets/'+kind,headers={'Range':'bytes=0-9','If-None-Match':'anything'})
        assert response.status_code in ([200,206] if expected else [403])
        assert response.headers['cache-control']=='no-store'
        info=client.get('/api/competition').json()
        assert info['dataset_available']==expected
        assert (info['dataset'] is not None)==expected
    s.is_open=True;s.finalized=True;db.commit()
    assert client.get('/api/datasets/'+kind).status_code==403

def test_open_requires_complete_schedule(client,db,organizer):
    s=db.get(Settings,1);s.is_open=False;s.start_time=None;s.end_time=None;db.commit()
    client.cookies.set('admin_session',organizer)
    assert client.patch('/api/admin/competition',json={'is_open':True}).status_code==422
    assert client.patch('/api/admin/competition',json={'is_open':True,'start_time':now().isoformat()}).status_code==422


def test_public_baseline_is_code_only_even_when_competition_closed(client,db):
    import io,zipfile,json
    s=db.get(Settings,1);s.is_open=False;s.start_time=None;s.end_time=None;db.commit()
    response=client.get('/api/resources/baseline')
    assert response.status_code==200 and response.headers['content-type']=='application/zip'
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist())=={'baseline.py','structure_features.py','baseline.ipynb','README.md','structure-format.md','requirements.txt'}
        assert all(not c.get('outputs') for c in json.loads(archive.read('baseline.ipynb'))['cells'])
    for kind in ['train','test','train-structures','test-structures','train-features','test-features','validation-split','starter-kit']:
        assert client.get('/api/datasets/'+kind).status_code==403
    assert client.get('/api/competition').json()['dataset'] is None
    assert client.get('/api/resources/starter-kit').status_code==404
    s.finalized=True;db.commit()
    assert client.get('/api/resources/baseline',headers={'Range':'bytes=0-31'}).status_code==206
