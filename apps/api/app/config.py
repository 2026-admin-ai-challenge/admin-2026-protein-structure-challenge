import os
from pathlib import Path


def _int(name, default):
    return int(os.getenv(name, str(default)))


REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(os.getenv("DATA_DIR", str(REPO_ROOT / "data")))
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://admin:admin@localhost:5432/challenge")
SECRET_KEY = os.environ.get("SECRET_KEY", "")
if len(SECRET_KEY) < 32:
    raise RuntimeError("SECRET_KEY must contain at least 32 characters")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
if COOKIE_SECURE and SECRET_KEY.startswith("local-development-only"):
    # The development default is written in this repository, so anyone could forge an
    # administrator session with it. HTTPS deployments must set their own SECRET_KEY.
    raise RuntimeError("Set a new random SECRET_KEY in .env before running with COOKIE_SECURE=true")
APP_ORIGIN = os.getenv("APP_ORIGIN", "http://localhost:3000")

# Uploaded ZIPs live outside every web-served path and outside the read-only data mount.
SUBMISSION_DIR = Path(os.getenv("SUBMISSION_DIR", str(REPO_ROOT / "var" / "submissions")))

# Confirmed by organizers: compressed ZIP 500 MB, inference 10 minutes, 10 submissions per team.
MAX_ZIP_BYTES = _int("MAX_ZIP_BYTES", 500 * 1024 * 1024)
INFERENCE_TIMEOUT_SECONDS = _int("INFERENCE_TIMEOUT_SECONDS", 600)
DEFAULT_TEAM_SUBMISSION_LIMIT = _int("TEAM_SUBMISSION_LIMIT", 10)

# PROVISIONAL (Q3): organizers have not fixed the unpacked limits. Change via environment only.
MAX_UNZIPPED_BYTES = _int("MAX_UNZIPPED_BYTES", 2 * 1024**3)
MAX_ZIP_ENTRIES = _int("MAX_ZIP_ENTRIES", 2000)

# PROVISIONAL (Q2): root entries every submission must contain. A trailing slash means directory.
ZIP_REQUIRED = tuple(
    item.strip() for item in os.getenv("ZIP_REQUIRED", "inference.py,requirements.txt,model/").split(",") if item.strip()
)

MAX_JSON_BYTES = 64 * 1024

# "mock" produces fake scores for development. "docker" runs the real isolated inference.
EVALUATOR = os.getenv("EVALUATOR", "mock").lower()
if EVALUATOR not in {"mock", "docker"}:
    raise RuntimeError("EVALUATOR must be 'mock' or 'docker'")
