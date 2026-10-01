from contextlib import asynccontextmanager
from datetime import datetime,timezone,timedelta
import json,re
from pathlib import Path
from fastapi import FastAPI,Depends,HTTPException,Request,Response,UploadFile,File
from fastapi.responses import FileResponse,JSONResponse
from sqlalchemy import select,func
from sqlalchemy.exc import IntegrityError
from .config import DATA_DIR,COOKIE_SECURE,APP_ORIGIN,MAX_UPLOAD_BYTES
from .db import get_db,SessionLocal
from .models import User,Team,Competition,Settings,Submission,now
from .schemas import Register,Login,SettingsPatch,BanPatch
from .security import current_user,admin_user,hasher,verify,token_for,rate_limit,DUMMY_HASH
from .dataset import metadata,answers
from .scoring.validator import validate,SubmissionError
from .scoring.scorer import score
from .leaderboard import rebuild,listing

@asynccontextmanager
async def lifespan(app):
    with SessionLocal() as db:
        if not db.get(Competition,1):
            db.add(Competition(id=1));db.flush();db.add(Settings(id=1));db.commit()
    yield
app=FastAPI(title="ADMIN Protein Challenge API",version="1.0.0",lifespan=lifespan)

@app.middleware("http")
async def protection(request,call_next):
    if request.method in {"POST","PATCH","DELETE","PUT"}:
        if request.headers.get("x-requested-with")!="ADMIN-Challenge":
            return JSONResponse({"detail":"Missing CSRF protection header"},status_code=403)
        origin=request.headers.get("origin")
        if origin and origin!=APP_ORIGIN:
            return JSONResponse({"detail":"Origin rejected"},status_code=403)
        try: length=int(request.headers.get("content-length","0"))
        except ValueError: return JSONResponse({"detail":"Invalid Content-Length"},status_code=400)
        if length>MAX_UPLOAD_BYTES+65536:
            return JSONResponse({"detail":"최대 업로드 크기는 2 MB입니다."},status_code=413)
    response=await call_next(request)
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["Cache-Control"]="no-store"
    response.headers["X-Frame-Options"]="DENY"
    return response

def utc(t): return t.replace(tzinfo=timezone.utc) if t and t.tzinfo is None else t

def dataset_available(settings, stamp=None):
    stamp = stamp or now()
    return bool(settings and settings.is_open and not settings.finalized
                and settings.start_time and settings.end_time
                and utc(settings.start_time) <= stamp < utc(settings.end_time))

def user_view(user,db):
    return {"id":user.id,"email":user.email,"display_name":user.display_name,"team_name":db.get(Team,user.team_id).name,"role":user.role}

def session(response,user): response.set_cookie("admin_session",token_for(user),httponly=True,secure=COOKIE_SECURE,samesite="lax",max_age=43200,path="/")

def settings_view(s):
    return {"is_open":s.is_open,"start_time":s.start_time,"end_time":s.end_time,"daily_limit":s.daily_limit,"frozen":s.frozen,"finalized":s.finalized}

@app.get("/api/health")
def health(db=Depends(get_db)):
    db.execute(select(1));return {"status":"ok","dataset_ready":metadata() is not None and (DATA_DIR/"private/labels.csv").exists()}

@app.post("/api/auth/register",status_code=201)
def register(body:Register,request:Request,response:Response,db=Depends(get_db)):
    rate_limit(db,"auth:"+request.client.host,10)
    user=User(email=str(body.email).lower(),password_hash=hasher.hash(body.password),display_name=body.display_name)
    try:
        team=Team(name=body.team_name);db.add(team);db.flush();user.team_id=team.id;db.add(user);db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,"이미 사용 중인 이메일 또는 팀 이름입니다.")
    session(response,user);return user_view(user,db)

@app.post("/api/auth/login")
def login(body:Login,request:Request,response:Response,db=Depends(get_db)):
    rate_limit(db,"auth:"+request.client.host,10)
    user=db.scalar(select(User).where(User.email==str(body.email).lower()))
    valid=verify(body.password,user.password_hash if user else DUMMY_HASH)
    if not user or not valid or user.banned: raise HTTPException(401,"이메일 또는 비밀번호를 확인하세요.")
    session(response,user);return user_view(user,db)

@app.post("/api/auth/logout")
def logout(response:Response): response.delete_cookie("admin_session",path="/");return {"ok":True}
@app.get("/api/auth/me")
def me(user=Depends(current_user),db=Depends(get_db)): return user_view(user,db)

@app.get("/api/competition")
def competition(db=Depends(get_db)):
    settings=db.get(Settings,1)
    return {"title":db.get(Competition,1).title,"settings":settings_view(settings),"dataset_available":dataset_available(settings),"dataset":metadata() if dataset_available(settings) else None,"participants":db.scalar(select(func.count(User.id)).where(User.role=="USER",User.banned.is_(False))),"submissions":db.scalar(select(func.count(Submission.id)).where(Submission.status=="success"))}

@app.get("/api/resources/baseline")
def public_baseline():
    # Code-only archive; event data and the data-bearing starter kit stay gated.
    path=DATA_DIR/"public/baseline_code.zip"
    if not path.exists(): raise HTTPException(503,"베이스라인을 준비 중입니다.")
    return FileResponse(path,filename="baseline_code.zip",media_type="application/zip")

@app.get("/api/datasets/{kind}")
def download_dataset(kind:str,db=Depends(get_db)):
    files={"train":"train.csv","test":"test.csv","sample-submission":"sample_submission.csv","class-distribution":"class_distribution.png","length-distribution":"sequence_length_distribution.png","train-structures":"train_structures.zip","test-structures":"test_structures.zip","train-features":"train_features.csv","test-features":"test_features.csv","validation-split":"validation_split.csv","starter-kit":"starter_kit.zip"}
    if kind not in files: raise HTTPException(404,"파일을 찾을 수 없습니다.")
    if not dataset_available(db.get(Settings,1)):
        raise HTTPException(403,"데이터셋은 대회 시작부터 종료 시각까지만 공개됩니다.")
    path=DATA_DIR/"public"/files[kind]
    if not path.exists(): raise HTTPException(503,"데이터셋을 준비 중입니다.")
    return FileResponse(path,filename=files[kind],media_type={".csv":"text/csv",".png":"image/png",".zip":"application/zip"}[path.suffix])

@app.get("/api/leaderboard")
def leaderboard(board:str="public",db=Depends(get_db)):
    if board not in {"public","final"}: raise HTTPException(400,"Unknown board")
    s=db.get(Settings,1)
    if board=="final" and not s.finalized: raise HTTPException(403,"최종 순위는 대회 종료 후 공개됩니다.")
    return {"board":board,"frozen":s.frozen,"entries":listing(db,"private" if board=="final" else "public")}

def submission_view(row):
    return {"id":row.id,"filename":row.filename,"public_score":row.public_score,"status":row.status,"error_message":row.error_message,"created_at":row.created_at}

@app.get("/api/submissions/me")
def mine(user=Depends(current_user),db=Depends(get_db)):
    rows=db.scalars(select(Submission).where(Submission.user_id==user.id).order_by(Submission.id.desc())).all()
    today=now().date();used=sum(utc(s.created_at).date()==today for s in rows)
    return {"entries":[submission_view(row) for row in rows],"used_today":used,"daily_limit":db.get(Settings,1).daily_limit}

@app.post("/api/submissions")
def submit(file:UploadFile=File(...),user=Depends(current_user),db=Depends(get_db)):
    rate_limit(db,"upload:"+str(user.id),10)
    # Serialize the gate and scoring with settings updates/finalization across workers.
    s=db.scalar(select(Settings).where(Settings.id==1).with_for_update())
    locked_user=db.scalar(select(User).where(User.id==user.id).with_for_update().execution_options(populate_existing=True))
    if locked_user.banned: raise HTTPException(403,"계정에 접근할 수 없습니다.")
    stamp=now()
    if not dataset_available(s,stamp):
        raise HTTPException(403,"현재 제출 기간이 아닙니다.")
    start=stamp.replace(hour=0,minute=0,second=0,microsecond=0)
    used=db.scalar(select(func.count(Submission.id)).where(Submission.user_id==user.id,Submission.created_at>=start))
    if used>=s.daily_limit: raise HTTPException(429,"오늘 제출 횟수를 모두 사용했습니다. UTC 00:00에 초기화됩니다.")
    labels,classes=answers()
    old_best=db.scalar(select(func.max(Submission.public_score)).where(Submission.user_id==user.id,Submission.status=="success"))
    filename=Path((file.filename or "submission.csv").replace("\\","/")).name[:120]
    row=Submission(user_id=user.id,team_id=user.team_id,filename=filename,status="invalid",created_at=stamp)
    try:
        if not filename.lower().endswith(".csv"): raise SubmissionError("CSV 파일만 제출할 수 있습니다.")
        content=file.file.read(MAX_UPLOAD_BYTES+1)
        if len(content)>MAX_UPLOAD_BYTES: raise SubmissionError("최대 업로드 크기는 2 MB입니다.")
        predictions=validate(content,labels.id.tolist(),classes)
        scores=score(labels,predictions,classes)
        row.public_score=scores["public"];row.private_score=scores["private"];row.status="success"
        row.predictions=json.dumps(predictions)
    except SubmissionError as e: row.error_message=str(e)
    db.add(row);db.flush()
    if row.status=="success" and not s.frozen: rebuild(db)
    db.commit()
    return {**submission_view(row),"previous_best":old_best,"remaining":s.daily_limit-used-1}

@app.get("/api/admin/users")
def users(admin=Depends(admin_user),db=Depends(get_db)):
    return [{**user_view(u,db),"banned":u.banned,"submissions":db.scalar(select(func.count(Submission.id)).where(Submission.user_id==u.id))} for u in db.scalars(select(User).order_by(User.id))]

@app.patch("/api/admin/users/{id}")
def ban(id:int,body:BanPatch,admin=Depends(admin_user),db=Depends(get_db)):
    s=db.scalar(select(Settings).where(Settings.id==1).with_for_update())
    if s.finalized: raise HTTPException(409,"최종 순위 공개 후에는 계정 상태를 변경할 수 없습니다.")
    u=db.get(User,id)
    if not u: raise HTTPException(404,"사용자가 없습니다.")
    if u.role=="ADMIN": raise HTTPException(400,"관리자 계정은 차단할 수 없습니다.")
    u.banned=body.banned;db.flush()
    if not s.frozen: rebuild(db)
    db.commit();return {"ok":True}

@app.get("/api/admin/submissions")
def all_submissions(admin=Depends(admin_user),db=Depends(get_db)):
    return [{**submission_view(r),"private_score":r.private_score,"team":team,"user":name} for r,team,name in db.execute(select(Submission,Team.name,User.display_name).join(Team,Team.id==Submission.team_id).join(User,User.id==Submission.user_id).order_by(Submission.id.desc()))]

@app.patch("/api/admin/competition")
def update_competition(body:SettingsPatch,admin=Depends(admin_user),db=Depends(get_db)):
    s=db.scalar(select(Settings).where(Settings.id==1).with_for_update())
    if s.finalized: raise HTTPException(409,"최종 순위가 이미 공개되었습니다.")
    values=body.model_dump(exclude_unset=True)
    if any(values.get(k,"absent") is None for k in ["is_open","daily_limit","frozen"]): raise HTTPException(422,"설정값은 null일 수 없습니다.")
    start=values.get("start_time",s.start_time);end=values.get("end_time",s.end_time)
    if start and end and utc(start)>=utc(end): raise HTTPException(422,"종료 시간은 시작 시간 이후여야 합니다.")
    if values.get("is_open",s.is_open):
        if not start or not end: raise HTTPException(422,"대회를 열기 전에 시작·종료 시각을 모두 설정하세요.")
        answers()
    was_frozen=s.frozen
    for key,value in values.items(): setattr(s,key,value)
    if was_frozen and not s.frozen: rebuild(db)
    db.commit();return settings_view(s)

@app.post("/api/admin/leaderboard/recalculate")
def recalculate(admin=Depends(admin_user),db=Depends(get_db)):
    s=db.scalar(select(Settings).where(Settings.id==1).with_for_update())
    if s.finalized or s.frozen: raise HTTPException(409,"순위 동결을 해제한 후 재계산하세요. 최종 공개 후에는 변경할 수 없습니다.")
    labels,classes=answers()
    for row in db.scalars(select(Submission).where(Submission.status=="success")):
        scores=score(labels,json.loads(row.predictions),classes);row.public_score=scores["public"];row.private_score=scores["private"]
    db.flush();rebuild(db);db.commit();return {"ok":True}

@app.post("/api/admin/leaderboard/finalize")
def finalize(admin=Depends(admin_user),db=Depends(get_db)):
    s=db.scalar(select(Settings).where(Settings.id==1).with_for_update())
    if s.finalized: return {"ok":True}
    if s.is_open: raise HTTPException(409,"먼저 대회를 닫아 주세요.")
    rebuild(db);rebuild(db,"private");s.finalized=True;s.frozen=True;db.commit();return {"ok":True}
