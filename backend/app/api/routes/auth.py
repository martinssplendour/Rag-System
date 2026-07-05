"""POST /auth/register, POST /auth/login.

Thin controllers -- all logic lives in app.services.auth_service. Neither
route depends on get_workspace_id (that would be circular: these are how
you obtain the credential get_workspace_id later verifies).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session, get_settings
from app.core.config import Settings
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    payload: RegisterRequest,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    return await auth_service.register(
        session=session, settings=settings, email=payload.email, password=payload.password
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    return await auth_service.login(
        session=session, settings=settings, email=payload.email, password=payload.password
    )
