"""Full real-PostgreSQL flow in a disposable database, including the concurrent team limit.

Run: docker compose exec -T -w /srv/apps/api api python /srv/scripts/postgres_smoke.py
Creates and removes only a uniquely named test database; never touches competition data.
"""
import io,os,sys,uuid,subprocess,tempfile,zipfile
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
test_url=base.rsplit('/',1)[0]+'/'+test_name
os.environ['DATABASE_URL']=test_url
os.environ['EVALUATOR']='mock';os.environ['MOCK_DELAY_SECONDS']='0'
os.environ['SUBMISSION_DIR']=tempfile.mkdtemp(prefix='smoke-submissions-')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'apps/api'))
HEADERS={'X-Requested-With':'ADMIN-Challenge'}

def code_zip(marker=''):
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as archive:
        for name,content in {'inference.py':'print(1)\n','train.py':'print(0)\n','requirements.txt':'\n','model/weights.bin':'weights'+marker}.items(): archive.writestr(name,content)
    return buffer.getvalue()

try:
    # Upgrade path: a prototype database with one account and one CSV submission.
    subprocess.run(['alembic','upgrade','0001'],check=True)
    with psycopg.connect(test_url.replace('postgresql+psycopg://','postgresql://'),autocommit=True) as old:
        old.execute("INSERT INTO teams (id,name,created_at) VALUES (900,'Prototype team',now())")
        old.execute("INSERT INTO users (id,email,password_hash,display_name,team_id,role,banned,created_at) VALUES (900,'old@example.com','x','Old',900,'USER',false,now())")
        old.execute("INSERT INTO competitions (id,title) VALUES (1,'t')")
        old.execute("INSERT INTO competition_settings (id,is_open,daily_limit,frozen,finalized) VALUES (1,false,5,false,false)")
        old.execute("INSERT INTO submissions (user_id,team_id,filename,public_score,private_score,status,created_at) VALUES (900,900,'old.csv',0.5,0.5,'success',now())")
    # A ZIP submission recorded by the 0002 schema must get a file record in 0003.
    subprocess.run(['alembic','upgrade','0002'],check=True)
    with psycopg.connect(test_url.replace('postgresql+psycopg://','postgresql://'),autocommit=True) as old:
        old.execute("INSERT INTO submissions (id,user_id,team_id,filename,status,failure_code,storage_key,sha256,size_bytes,counted,attempts,created_at) VALUES (901,900,900,'old.zip','failed','runtime_error','0123456789abcdef0123456789abcdef',repeat('a',64),1234,true,1,now())")
    subprocess.run(['alembic','upgrade','head'],check=True)
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import SessionLocal,engine
    from app.models import User,Team,Settings,Submission,SubmissionFile
    from app.security import hasher
    from app.evaluators.mock import MockEvaluator
    from app.worker import process_one,recover_stale
    from sqlalchemy import select,text
    with SessionLocal() as db:
        migrated=db.scalar(select(User).where(User.id==900)); old_row=db.scalar(select(Submission).where(Submission.filename=='old.csv'))
        moved=db.get(Submission,901).file
        assert (moved.team_id,moved.uploaded_by,moved.original_filename,moved.storage_key,moved.size_bytes)==(900,900,'old.zip','0123456789abcdef0123456789abcdef',1234)
        db.execute(text("SELECT setval(pg_get_serial_sequence('submissions','id'),1000)"))
        assert migrated.username=='old@example.com' and db.get(Settings,1).team_submission_limit==10
        assert (old_row.status,old_row.evaluator,old_row.counted,old_row.file)==('succeeded','csv',True,None)
        db.execute(text("SELECT setval(pg_get_serial_sequence('teams','id'),1000)"));db.execute(text("SELECT setval(pg_get_serial_sequence('users','id'),1000)"))
        team=Team(name='Test organizers');db.add(team);db.flush()
        db.add(User(username='test-admin',password_hash=hasher.hash('Test-Admin-Password-42'),display_name='Test Admin',team_id=team.id,role='ADMIN'));db.commit()
    with TestClient(app,base_url="https://testserver",headers=HEADERS) as client:
        assert client.post('/api/auth/register',json={'username':'x','password':'y'}).status_code in (404,405)
        assert client.post('/api/auth/login',json={'username':'test-admin','password':'Test-Admin-Password-42'}).status_code==200
        organizer_cookie=client.cookies.get('admin_session')
        team_id=client.post('/api/admin/teams',json={'name':'Integration Test Team'}).json()['id']
        accounts=[client.post('/api/admin/users',json={'team_id':team_id}).json() for _ in range(2)]
        assert len({a['username'] for a in accounts})==2 and all(len(a['username'])==10 for a in accounts)
        window={'start_time':(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(),'end_time':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}
        assert client.patch('/api/admin/competition',json={'is_open':True,'team_submission_limit':1,**window}).status_code==200
        cookies=[]
        for account in accounts:
            with TestClient(app,base_url="https://testserver",headers=HEADERS) as session:
                assert session.post('/api/auth/login',json={'username':account['username'],'password':account['temporary_password']}).status_code==200
                cookies.append(session.cookies.get('admin_session'))
        assert client.cookies.set('admin_session',cookies[0]) is None and client.get('/api/admin/teams').status_code==403
        # Two accounts of the same team submit at the same moment: exactly one is accepted.
        def concurrent_submission(index):
            with TestClient(app,base_url="https://testserver",headers=HEADERS) as parallel:
                parallel.cookies.set('admin_session',cookies[index])
                return parallel.post('/api/submissions',content=code_zip(str(index)),headers={'X-Filename':'code.zip','Content-Type':'application/zip'})
        with ThreadPoolExecutor(max_workers=2) as pool: responses=list(pool.map(concurrent_submission,range(2)))
        assert sorted(r.status_code for r in responses)==[202,429],[r.text for r in responses]
        accepted=next(r.json() for r in responses if r.status_code==202)
        assert accepted['status']=='queued' and accepted['remaining']==0 and 'private_score' not in accepted
        with SessionLocal() as db:
            assert recover_stale(db)==0
            scored=process_one(db,MockEvaluator(),'smoke-worker')
            assert scored.id==accepted['id'] and scored.status=='succeeded' and process_one(db,MockEvaluator(),'smoke-worker') is None
            stored=db.scalar(select(SubmissionFile).where(SubmissionFile.submission_id==accepted['id']));assert (stored.submission_id,stored.team_id,stored.sha256)==(accepted['id'],scored.team_id,accepted['sha256'])
        history=client.get('/api/submissions/me').json()
        assert len(history['entries'])==1 and history['used']==1 and history['entries'][0]['public_score'] is not None
        board=client.get('/api/leaderboard').json()['entries']
        # Teams without a score sit after the ranking with rank None, so rank tells the two apart.
        assert [e['team'] for e in board if e['rank']]==['Integration Test Team'],board  # the prototype CSV score is not ranked
        assert all(e['score'] is None and e['submissions']==0 for e in board if e['rank'] is None),board
        assert client.get('/api/leaderboard?board=final').status_code==403
        client.cookies.set('admin_session',organizer_cookie)
        assert client.get('/api/admin/overview').json()['queue']=={'queued':0,'running':0,'succeeded':2,'failed':1}
        assert client.patch('/api/admin/competition',json={'is_open':False}).status_code==200
        assert client.post('/api/admin/leaderboard/finalize').status_code==200
        assert len([e for e in client.get('/api/leaderboard?board=final').json()['entries'] if e['rank']])==1
        assert client.patch('/api/admin/competition',json={'is_open':True}).status_code==409
        assert len(client.get('/api/admin/audit').json())>=6
        assert client.get('/openapi.json').status_code==200
        print('PASS: PostgreSQL 0001->0003 migration with prototype data, file records, issued accounts, ZIP intake, concurrent team limit, queue worker, leaderboard, private-score protection, close/finalize, audit log and OpenAPI.')
        print('Mock public score:',history['entries'][0]['public_score'])
    engine.dispose()
    # The rollback path documented for operators must work too.
    with psycopg.connect(test_url.replace('postgresql+psycopg://','postgresql://'),autocommit=True) as cleanup:
        cleanup.execute("DELETE FROM leaderboard_entries");cleanup.execute("DELETE FROM submission_files");cleanup.execute("DELETE FROM submissions");cleanup.execute("DELETE FROM users WHERE id<>900")
    with psycopg.connect(test_url.replace('postgresql+psycopg://','postgresql://'),autocommit=True) as cleanup:
        cleanup.execute("INSERT INTO submissions (id,user_id,team_id,filename,status,counted,attempts,created_at) VALUES (902,900,900,'kept.zip','queued',true,0,now())")
        cleanup.execute("INSERT INTO submission_files (team_id,submission_id,uploaded_by,original_filename,storage_key,sha256,size_bytes,created_at) VALUES (900,902,900,'kept.zip','fedcba9876543210fedcba9876543210',repeat('b',64),4321,now())")
    subprocess.run(['alembic','downgrade','0002'],check=True)
    with psycopg.connect(test_url.replace('postgresql+psycopg://','postgresql://'),autocommit=True) as check:
        assert check.execute("SELECT storage_key,size_bytes FROM submissions WHERE id=902").fetchone()==('fedcba9876543210fedcba9876543210',4321)
    subprocess.run(['alembic','downgrade','0001'],check=True)
    subprocess.run(['alembic','upgrade','head'],check=True)
    print('PASS: downgrade to 0001 and upgrade again.')
finally:
    admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(test_name)))
    admin.close()
