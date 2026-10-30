from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .config import APP_ORIGIN, MAX_JSON_BYTES, MAX_ZIP_BYTES
from .db import SessionLocal
from .errors import ApiError
from .models import Competition, Settings
from .routers import admin, auth, awards, public, submissions


@asynccontextmanager
async def lifespan(app):
    with SessionLocal() as db:
        if not db.get(Competition, 1):
            db.add(Competition(id=1))
            db.flush()
            db.add(Settings(id=1))
            db.commit()
    yield


app = FastAPI(title="ADMIN Protein Challenge API", version="2.0.0", lifespan=lifespan)


@app.exception_handler(ApiError)
async def api_error(request, error):
    return JSONResponse({"detail": error.detail, "code": error.code}, status_code=error.status_code)


@app.middleware("http")
async def protection(request, call_next):
    if request.method in {"POST", "PATCH", "DELETE", "PUT"}:
        if request.headers.get("x-requested-with") != "ADMIN-Challenge":
            return JSONResponse({"detail": "Missing CSRF protection header"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != APP_ORIGIN:
            return JSONResponse({"detail": "Origin rejected"}, status_code=403)
        try:
            length = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"detail": "Invalid Content-Length", "code": "bad_request"}, status_code=400)
        # Only the ZIP upload may be large; it also counts bytes while streaming.
        upload = request.method == "POST" and request.url.path == "/api/submissions"
        if length > (MAX_ZIP_BYTES if upload else MAX_JSON_BYTES):
            message = f"ZIP 파일은 최대 {MAX_ZIP_BYTES // (1024 * 1024)} MB입니다." if upload else "요청 본문이 너무 큽니다."
            return JSONResponse({"detail": message, "code": "zip_too_large" if upload else "too_large"}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Frame-Options"] = "DENY"
    return response


for module in (auth, public, submissions, admin, awards):
    app.include_router(module.router)
