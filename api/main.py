"""
api/main.py
-----------
FastAPI application entry point for Phase 6 -- Web Foundation.

Responsibilities:
  - Initialise SQLite DB on startup (calls init_db() from data/database.py)
  - Configure CORS for React frontend (Phase 7) and Streamlit (current)
  - Register all routers under their route prefixes
  - Mount JWT auth middleware (token validation via api/dependencies.py)
  - Expose OpenAPI docs at /docs (Swagger) and /redoc

Route groups:
  /auth/              -- OTP request, verify, refresh, logout
  /clients/           -- client CRUD (advisor-only) + investor self-view
  /goals/             -- goal CRUD + planning computation
  /holdings/          -- holdings CRUD + statement upload
  /portfolio/         -- analytics: summary, XIRR, sector, overlap, stock exposure
  /optimiser/         -- CVXPY optimiser + constraint parsing (advisor-only)
  /recommendations/   -- fund recommendations per goal
  /reports/           -- report lifecycle: generate, approve, dispatch, stream
  /funds/             -- fund screener, factsheet, NAV history (read-only, all roles)
  /agents/            -- agent run log + approval queue (advisor/admin)
  /admin/             -- user management, role changes, audit log (admin-only)

Run:
  PYTHONPATH=/Users/manavgupta/financial_advisor uvicorn api.main:app --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from data.database import init_db
from api.routers import (
    auth, clients, goals, holdings, portfolio,
    optimiser, recommendations, reports, funds, agents, admin,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("api.main")


# ---------------------------------------------------------------------------
# Lifespan -- runs on startup and shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting MF Advisory API -- Phase 6")
    init_db()
    logger.info("Database initialised")
    yield
    logger.info("MF Advisory API shutting down")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="MF Advisory Platform API",
    description=(
        "Backend API for the Indian Mutual Fund Advisory Platform. "
        "Serves the Streamlit advisor UI (Phase 5), React investor app (Phase 7), "
        "and React advisor web app (Phase 8). "
        "All engines (risk, goal, recommendation, performance, overlap, optimiser) "
        "are wrapped as REST endpoints with JWT auth and role-based access control."
    ),
    version="6.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ---------------------------------------------------------------------------
# CORS -- allow Streamlit (localhost:8501) and React dev server (localhost:3000)
# In production, restrict origins to the actual deployed domain.
# ---------------------------------------------------------------------------

ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8501",
    "http://localhost:8080",
    "https://your-production-domain.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(auth.router)
app.include_router(clients.router)
app.include_router(goals.router)
app.include_router(holdings.router)
app.include_router(portfolio.router)
app.include_router(optimiser.router)
app.include_router(recommendations.router)
app.include_router(reports.router)
app.include_router(funds.router)
app.include_router(agents.router)
app.include_router(admin.router)


# ---------------------------------------------------------------------------
# Health check + root
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def root():
    return {
        "service": "MF Advisory Platform API",
        "phase": "6 -- Web Foundation",
        "docs": "/docs",
        "status": "running",
    }


@app.get("/health", tags=["health"])
def health_check():
    """Liveness probe -- returns 200 if the API is running."""
    from config.settings import DATABASE_PATH
    import os
    db_ok = os.path.exists(DATABASE_PATH)
    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "ok" if db_ok else "not found",
        "database_path": DATABASE_PATH,
    }


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error("Unhandled exception: %s %s -- %s", request.method, request.url, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred. Check server logs."},
    )
