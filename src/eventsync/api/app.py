from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from eventsync.api.routes import router
from eventsync.config import DEFAULT, REPO_ROOT, Settings
from eventsync.store import build_store

WEB_DIR = REPO_ROOT / "web"


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def create_app(settings: Settings = DEFAULT, web_dir: Path = WEB_DIR) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store = build_store(settings)
        yield

    app = FastAPI(title="Event Sync Service", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings

    @app.exception_handler(RequestValidationError)
    async def on_validation(_: Request, exc: RequestValidationError):
        return _error(422, "validation_error", "; ".join(e.get("msg", "") for e in exc.errors()) or "invalid request")

    @app.exception_handler(HTTPException)
    async def on_http(_: Request, exc: HTTPException):
        d = exc.detail
        if isinstance(d, dict) and "code" in d:
            return _error(exc.status_code, d["code"], d.get("message", ""))
        return _error(exc.status_code, "error", str(d))

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    app.include_router(router)
    if web_dir.exists():
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
    return app


app = create_app()
