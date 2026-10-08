"""Verify best-ZIP retention with concurrent PostgreSQL workers in a disposable DB.
Run inside the API container: python /srv/scripts/postgres_retention_smoke.py
Creates and drops only its own uniquely named database. Uses synthetic ZIPs in /tmp.
"""
import io, json, os, sys, tempfile, uuid, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'apps/api'))
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import psycopg
from psycopg import sql

base = os.environ['DATABASE_URL']
name = 'retention_test_' + uuid.uuid4().hex[:12]
admin = psycopg.connect(base.replace('postgresql+psycopg://', 'postgresql://'), autocommit=True)
admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
os.environ['DATABASE_URL'] = base.rsplit('/', 1)[0] + '/' + name
os.environ['SECRET_KEY'] = 'retention-test-only-secret-more-than-thirty-two-characters'
os.environ['EVALUATOR'] = 'mock'
os.environ['ZIP_RETENTION'] = 'best_public'
os.environ['MOCK_DELAY_SECONDS'] = '0'
os.environ['LAUNCH_AT'] = '2000-01-01T00:00:00Z'
os.environ['SUBMISSION_DIR'] = tempfile.mkdtemp(prefix='retention-zips-')

try:
    from fastapi.testclient import TestClient
    from app.db import Base, engine, SessionLocal
    from app.main import app
    from app.models import Settings, Team, SubmissionFile, Submission, now
    from app.accounts import create_user
    from app.evaluators.mock import MockEvaluator
    from app.worker import process_one
    from app import files, storage
    from sqlalchemy import select
    Base.metadata.create_all(engine)
    with TestClient(app, headers={'X-Requested-With': 'ADMIN-Challenge'}) as client:
        with SessionLocal() as db:
            team = Team(name='Retention integration test')
            db.add(team); db.flush()
            create_user(db, team, username='retentiontest', password='local-retention-test-only')
            s = db.get(Settings, 1)
            s.is_open = True; s.start_time = now()-timedelta(hours=1); s.end_time = now()+timedelta(hours=1)
            db.commit()
        assert client.post('/api/auth/login', json={'username':'retentiontest', 'password':'local-retention-test-only'}).status_code == 200
        ids = []
        for score in [0.4, 0.9]:
            content = io.BytesIO()
            with zipfile.ZipFile(content, 'w') as z:
                for path, value in {'inference.py':'print(1)', 'train.py':'# test', 'requirements.txt':'', 'model/weights.bin':'test', 'mock.json':json.dumps({'public':score, 'private':score, 'sleep':0.1})}.items():
                    z.writestr(path, value)
            r = client.post('/api/submissions', content=content.getvalue(), headers={'X-Filename':f'model-{score}.zip','Content-Type':'application/zip'})
            assert r.status_code == 202, r.text
            ids.append(r.json()['id'])
        def run(index):
            with SessionLocal() as db:
                result = process_one(db, MockEvaluator(), f'parallel-{index}')
                return result.id
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert set(pool.map(run, [0,1])) == set(ids)
        with SessionLocal() as db:
            kept = db.scalars(select(SubmissionFile).where(SubmissionFile.deleted_at.is_(None))).all()
            assert [f.submission_id for f in kept] == [ids[1]]
            assert files.check(db, with_hashes=True)['ok']
            assert len(db.scalars(select(Submission)).all()) == 2
        result = client.get('/api/submissions/me').json()
        assert len(result['entries']) == 2 and result['used'] == 2
        assert [s['id'] for s in result['entries'] if s['is_best_public']] == [ids[1]]
        print('PASS: PostgreSQL concurrent scoring keeps only 0.9 ZIP; 0.4 history/score/count retained; file hashes verified')
finally:
    if 'engine' in globals(): engine.dispose()
    admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
    admin.close()
