import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import scheduler
from app.api import admin, assistant, clusters, connect, defense, exports, items, quality, sources, stats
from app.config import get_settings
from app.db import SessionLocal
from app.seed import seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
STATIC = Path(__file__).resolve().parent.parent / "static"

# Windows registry associations can label JS as text/plain, which browsers reject
# for module scripts. Register web MIME types after loading the platform defaults.
mimetypes.init()
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    if s.secret_key in ("change-me-in-env", "replace-with-64-random-characters") or len(s.secret_key) < 32:
        logging.getLogger("pulse").warning("SECRET_KEY is default or short: set a random 64-character value in .env")
    if not s.llm_enabled:
        logging.getLogger("pulse").warning("ANTHROPIC_API_KEY not set: analysis runs in the labelled rules fallback mode")
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="City Alert API", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in get_settings().cors_origins.split(",")],
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    return resp


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    logging.getLogger("pulse").exception("unhandled error on %s", request.url.path)
    return JSONResponse({"detail": "Внутренняя ошибка сервера. Подробности в журнале."}, status_code=500)


for r in (admin.router, connect.router, items.router, clusters.router, stats.router, sources.router, quality.router,
          exports.router, assistant.router, defense.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"ok": True}


# Serve the built frontend (single container in production)
if (STATIC / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Не найдено"}, status_code=404)
        f = STATIC / path
        if path and f.is_file() and STATIC in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(STATIC / "index.html")
