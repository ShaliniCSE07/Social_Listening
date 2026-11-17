"""FastAPI service main entrypoint."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import load_config
from src.service.models import HealthResponse
from src.service.processing_gateway import mount_processing_routes
from src.service.routes.config import router as config_router
from src.service.routes.processing import router as processing_router
from src.service.routes.runs import plan_router, router as runs_router

app = FastAPI(
    title="Social Listening Collection Service",
    description="Thin FastAPI service layer for social media listening collection pipelines.",
    version="1.0.0",
)

# CORS: allow only http://localhost:3000 (from config value), never "*"
cors_origins = load_config().get("cors_origins", ["http://localhost:3000"])
if isinstance(cors_origins, str):
    cors_origins = [cors_origins]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config_router)
app.include_router(plan_router)
app.include_router(processing_router)
app.include_router(runs_router)

# Serve the processing API (Member 2: /process, /runs/{id}/records, rerun) from
# this same backend so the processing dashboard works alongside collection.
# Skipped, with a logged reason, when processing cannot load (e.g. no MongoDB
# driver or SOCL_AUTHOR_PEPPER unset); collection keeps working either way.
mount_processing_routes(app)


@app.get("/health", response_model=HealthResponse, tags=["health"])
def health_check() -> HealthResponse:
    """Service health check endpoint."""
    return HealthResponse(status="ok")

