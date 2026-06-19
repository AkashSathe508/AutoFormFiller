"""AutoFormFiller FastAPI Application Entry Point."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from app.core.config import settings
from app.api.v1 import auth, profiles, documents, forms, applications


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    import asyncio

    # Startup
    print(f"Starting AutoFormFiller API (env={settings.APP_ENV})")

    # Seed canonical field embeddings in a background thread (idempotent ON CONFLICT DO UPDATE)
    # This ensures pgvector has data before the first prefill task runs.
    async def _seed_embeddings_async():
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: __import__(
                    "ai_services.form_understanding_agent.field_seeder",
                    fromlist=["seed_field_embeddings"],
                ).seed_field_embeddings(settings.DATABASE_SYNC_URL),
            )
            print("✓ Field embeddings seeded/verified.")
        except Exception as exc:
            # Non-fatal — embedding stage degrades gracefully to LLM fallback
            print(f"⚠ Field embedding seed skipped: {exc}")

    asyncio.create_task(_seed_embeddings_async())

    yield
    # Shutdown
    print("Shutting down AutoFormFiller API")


app = FastAPI(
    title="AutoFormFiller API",
    description="AI-powered Indian government form pre-fill platform",
    version="1.0.0",
    docs_url="/docs" if settings.APP_ENV != "production" else None,
    redoc_url="/redoc" if settings.APP_ENV != "production" else None,
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics
Instrumentator().instrument(app).expose(app, endpoint="/metrics")

# API routers
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(profiles.router, prefix="/api/v1/profiles", tags=["Profiles"])
app.include_router(documents.router, prefix="/api/v1/documents", tags=["Documents"])
app.include_router(forms.router, prefix="/api/v1/forms", tags=["Forms"])
app.include_router(applications.router, prefix="/api/v1/applications", tags=["Applications"])


@app.get("/health")
async def health_check():
    """Health check endpoint for Docker Compose and load balancers."""
    return {"status": "ok", "service": "autoformfiller-api", "version": "1.0.0"}


@app.get("/")
async def root():
    return {"message": "AutoFormFiller API", "docs": "/docs"}
