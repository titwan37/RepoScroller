from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from reposcroller.config import settings
from reposcroller.ledger.db import init_db
from reposcroller.api.routes.documents import router as documents_router
from reposcroller.api.routes.crawler import router as crawler_router
from reposcroller.api.routes.chat import router as chat_router
from reposcroller.api.routes.taxonomy import router as taxonomy_router
from reposcroller.api.routes.diagnostics import router as diagnostics_router
from reposcroller.api.routes.sidecar import router as sidecar_router
from reposcroller.api.diagnostics import setup_diagnostic_logging

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure SQLite WAL schema, FTS tables, and live diagnostic handler are initialized
    init_db()
    setup_diagnostic_logging()
    yield
    # Shutdown logic if needed


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        description="Modular multi-tier document ingestion and procedural intelligence engine with ALCOA+ integrity.",
        lifespan=lifespan,
    )

    # Enable CORS for local dashboards (Angular/React/Vue or Rich frontends)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount API routers under /api/v1
    app.include_router(documents_router, prefix="/api/v1")
    app.include_router(crawler_router, prefix="/api/v1")
    app.include_router(chat_router, prefix="/api/v1")
    app.include_router(taxonomy_router, prefix="/api/v1")
    app.include_router(diagnostics_router, prefix="/api/v1")
    app.include_router(sidecar_router, prefix="/api/v1")


    # Mount static assets
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    def serve_dashboard():
        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return {
            "app": settings.APP_NAME,
            "version": "0.1.0",
            "alcoa_compliant": True,
            "dashboard": "static/index.html",
        }

    @app.get("/api/v1/health")
    def api_health():
        return {
            "app": settings.APP_NAME,
            "version": "0.1.0",
            "alcoa_compliant": True,
            "status": "healthy"
        }

    return app


app = create_app()
