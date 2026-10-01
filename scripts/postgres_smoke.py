"""Full real-PostgreSQL flow in a disposable database, including concurrent quota.
Run: docker compose exec -w /srv/apps/api api python /srv/scripts/postgres_smoke.py
Creates and removes only a uniquely named test database; never touches competition data.
"""
import os,sys,uuid,subprocess
from datetime import datetime,timezone,timedelta
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import psycopg
from psycopg import sql
base=os.environ['DATABASE_URL']
pg_url=base.replace('postgresql+psycopg://','postgresql://')
test_name='challenge_test_'+uuid.uuid4().hex[:12]
admin=psycopg.connect(pg_url,autocommit=True)
admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(test_name)))
os.environ['DATABASE_URL']=base.rsplit('/',1)[0]+'/'+test_name
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'apps/api'))
try:
    subprocess.run(['alembic','upgrade','head'],check=True)
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import SessionLocal,engine
    from app.models import User,Team
    from app.security import hasher
    from sqlalchemy import select
    with TestClient(app,base_url="https://testserver",headers={'X-Requested-With':'ADMIN-Challenge'}) as client:
        details={'email':'integration@example.com','password':'Integration-Test-Password-42','display_name':'Integration Test','team_name':'Integration Test Team'}
        assert client.post('/api/auth/register',json=details).status_code==201
        participant_cookie=client.cookies.get('admin_session')
        assert client.get('/api/admin/users').status_code==403
        # Organizer account is created inside the disposable database only.
        with SessionLocal() as db:
            team=Team(name='Test organizers');db.add(team);db.flush()
            db.add(User(email='test-admin@example.com',password_hash=hasher.hash('Test-Admin-Password-42'),display_name='Test Admin',team_id=team.id,role='ADMIN'));db.commit()
        assert client.post('/api/auth/login',json={'email':'test-admin@example.com','password':'Test-Admin-Password-42'}).status_code==200
        organizer_cookie=client.cookies.get('admin_session')
        assert client.patch('/api/admin/competition',json={'is_open':True,'daily_limit':1,'start_time':(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(),'end_time':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}).status_code==200
        # Download public files through the actual route, validate CSV end to end.
        for kind in ['train','test','sample-submission','train-structures','test-structures','train-features','test-features','validation-split','starter-kit']:
            response=client.get('/api/datasets/'+kind,headers={'Range':'bytes=0-31'})
            assert response.status_code==206
        submission=client.get('/api/datasets/sample-submission').content
        if os.getenv('SMOKE_SUBMISSION_FILE'): submission=Path(os.environ['SMOKE_SUBMISSION_FILE']).read_bytes()
        def concurrent_submission(_):
            with TestClient(app,base_url="https://testserver",headers={'X-Requested-With':'ADMIN-Challenge'}) as parallel:
                parallel.cookies.set('admin_session',participant_cookie)
                return parallel.post('/api/submissions',files={'file':('submission.csv',submission,'text/csv')})
        with ThreadPoolExecutor(max_workers=2) as pool: responses=list(pool.map(concurrent_submission,range(2)))
        assert sorted(r.status_code for r in responses)==[200,429],[r.text for r in responses]
        success=next(r.json() for r in responses if r.status_code==200)
        assert success['status']=='success' and 'private_score' not in success
        client.cookies.set('admin_session',participant_cookie)
        history=client.get('/api/submissions/me').json()
        assert len(history['entries'])==1 and history['used_today']==1
        assert len(client.get('/api/leaderboard').json()['entries'])==1
        assert client.get('/api/leaderboard?board=final').status_code==403
        client.cookies.set('admin_session',organizer_cookie)
        assert client.patch('/api/admin/competition',json={'is_open':False}).status_code==200
        assert client.post('/api/admin/leaderboard/finalize').status_code==200
        final=client.get('/api/leaderboard?board=final').json()
        assert len(final['entries'])==1
        assert client.patch('/api/admin/competition',json={'is_open':True}).status_code==409
        assert client.get('/openapi.json').status_code==200
        print('PASS: PostgreSQL migrations, registration/login, downloads, CSV scoring, concurrent daily quota, public/private access, close/finalize and OpenAPI.')
        print('Public baseline score:',success['public_score'])
    engine.dispose()
finally:
    admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(test_name)))
    admin.close()
