from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
# pyrefly: ignore [missing-import]
from backend.config import settings
from backend.ledger.db import init_db
from backend.api.routes.documents import router as documents_router    
from backend.api.routes.crawler import router as crawler_router    
from backend.api.routes.chat import router as chat_router  
from backend.api.routes.taxonomy import router as taxonomy_router
from backend.api.routes.sidecar import router as sidecar_router, rag_router    
from backend.api.routes.authors import router as authors_router
from backend.api.routes.diagnostics import router as diagnostics_router    
from backend.api.routes.actions import router as actions_router
from backend.api.diagnostics import setup_diagnostic_logging

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
STATIC_DIR = FRONTEND_DIR if FRONTEND_DIR.exists() else (Path(__file__).parent / "static")

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
    app.include_router(authors_router, prefix="/api/v1")
    app.include_router(rag_router, prefix="/api/v1")
    app.include_router(actions_router, prefix="/api/v1")

    @app.get("/")
    @app.get("/3d_knowledgegraph_universe")
    @app.get("/universe")
    @app.get("/ledger")
    @app.get("/actions")
    @app.get("/todos")
    @app.get("/graphrag")
    @app.get("/authors")
    @app.get("/chat")
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

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        fav = STATIC_DIR / "favicon.ico"
        if fav.exists():
            return FileResponse(fav, media_type="image/x-icon")
        return Response(status_code=204)

    # Mount static assets for frontend (app.js, style.css, assets)
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="frontend")

    return app


app = create_app()
