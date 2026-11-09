from __future__ import annotations

from fastapi import FastAPI

from eventsync.config import DEFAULT, Settings


def create_app(settings: Settings = DEFAULT) -> FastAPI:
    app = FastAPI(title="Event Sync Service", version="0.1.0")
    app.state.settings = settings

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    return app


app = create_app()
