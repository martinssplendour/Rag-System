"""Health and readiness endpoints."""

from fastapi import APIRouter, Request
from sqlalchemy import text

from app.api.errors import AppError
from app.schemas.common import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/health/ready", response_model=HealthResponse)
async def get_readiness(request: Request) -> HealthResponse:
    try:
        session_factory = request.app.state.session_factory
        async with session_factory() as session:
            await session.execute(text("select 1"))
        request.app.state.chroma_collection.count()
    except Exception as exc:
        raise AppError("SERVICE_NOT_READY", "The service is not ready.", 503) from exc

    return HealthResponse(status="ready")
