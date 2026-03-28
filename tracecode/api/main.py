"""
api/main.py — FastAPI application factory.

The app:
  - Mounts REST routes at /api/*
  - Serves the built Next.js static export from ui/out/ at /*
  - Falls back to ui/out/index.html for SPA-style client-side routing

Usage (from CLI):
    tracecode serve [--port 7842]

Usage (from uvicorn directly, for development):
    uvicorn tracecode.api.main:app --reload --port 7842
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from tracecode.api.routes import router

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path to the Next.js static export
# ---------------------------------------------------------------------------

# Installed package: ui/out is shipped alongside the Python package.
# During development the repo layout is: <repo-root>/ui/out/
_REPO_ROOT = Path(__file__).parent.parent.parent
UI_OUT = _REPO_ROOT / "ui" / "out"


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    app = FastAPI(
        title="Tracecode",
        description="Personal AI coding session quality engine",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url=None,
    )

    # Allow Next.js dev server (port 3000) to call the API during development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # REST API
    app.include_router(router, prefix="/api")

    # Static UI — only mount if the build exists
    if UI_OUT.exists() and UI_OUT.is_dir():
        # Mount assets (JS, CSS, images) — Next.js puts them in /_next/
        app.mount("/", StaticFiles(directory=str(UI_OUT), html=True), name="ui")
    else:
        # Development fallback: tell the user to start the Next.js dev server
        @app.get("/")
        async def ui_not_built():
            return {
                "message": "UI not built yet.",
                "hint": "Run `cd ui && npm run build` or start the dev server with `npm run dev` on port 3000.",
                "api_docs": "/api/docs",
            }

    return app


# Module-level app instance for uvicorn
app = create_app()
