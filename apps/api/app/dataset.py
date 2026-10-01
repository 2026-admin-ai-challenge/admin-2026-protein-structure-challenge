import json
import pandas as pd
from fastapi import HTTPException
from .config import DATA_DIR

def metadata():
    path=DATA_DIR/"public/metadata.json"
    return json.loads(path.read_text()) if path.exists() else None

def answers():
    path=DATA_DIR/"private/labels.csv";meta=metadata()
    if not path.exists() or not meta: raise HTTPException(503,"운영자가 데이터셋을 준비 중입니다.")
    frame=pd.read_csv(path,dtype=str)
    test=pd.read_csv(DATA_DIR/"public/test.csv",dtype=str)
    if not frame.id.is_unique or set(frame.id)!=set(test.id) or set(frame.partition)!={"public","private"}:
        raise RuntimeError("Private dataset integrity check failed")
    if not set(frame.label)<=set(meta["labels"]): raise RuntimeError("Invalid private label")
    return frame,meta["labels"]
