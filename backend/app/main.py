import os
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .api import alerts, auth, langsmith_compat, metrics, otel, projects, sessions, teams, traces, feedback
from .services.ws import router as ws_router
from .config import settings
from .database import Base, SessionLocal, engine
from .services.alerting import background_loop
from .services.retention import retention_loop
from .services.security import ensure_default_admin

app = FastAPI(title="LLMTrace", version="0.7.0", description="LLM monitoring platform for teams")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(traces.router)
app.include_router(sessions.router)
app.include_router(metrics.router)
app.include_router(alerts.router)
app.include_router(feedback.router)
app.include_router(otel.router)
app.include_router(langsmith_compat.router)  # LangSmith 兼容端点：LangChain tracer 零代码直连
app.include_router(teams.router)
app.include_router(ws_router)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        ensure_default_admin(db)
    threading.Thread(target=background_loop, args=(60,), daemon=True).start()
    threading.Thread(target=retention_loop, args=(3600,), daemon=True).start()


@app.get("/api/health")
def health():
    return {"status": "ok"}


_static_dir = settings.static_dir
if _static_dir and os.path.isdir(_static_dir):
    _index_file = os.path.join(_static_dir, "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        """Serve real files from dist; fall back to index.html for SPA routes."""
        candidate = os.path.normpath(os.path.join(_static_dir, full_path))
        if (
            full_path
            and candidate.startswith(os.path.normpath(_static_dir))
            and os.path.isfile(candidate)
        ):
            return FileResponse(candidate)
        return FileResponse(_index_file)
else:
    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse(url=settings.frontend_url)

