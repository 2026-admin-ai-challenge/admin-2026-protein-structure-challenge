import os
from pathlib import Path
DATA_DIR=Path(os.getenv("DATA_DIR",str(Path(__file__).resolve().parents[3]/"data")))
DATABASE_URL=os.getenv("DATABASE_URL","postgresql+psycopg://admin:admin@localhost:5432/challenge")
SECRET_KEY=os.environ.get("SECRET_KEY","")
if len(SECRET_KEY)<32: raise RuntimeError("SECRET_KEY must contain at least 32 characters")
COOKIE_SECURE=os.getenv("COOKIE_SECURE","false").lower()=="true"
APP_ORIGIN=os.getenv("APP_ORIGIN","http://localhost:3000")
MAX_UPLOAD_BYTES=2*1024*1024
