"""POST/GET /documents.

Thin controllers: parse/validate transport-level input, delegate entirely
to document_service, map the ORM result to a response model. No business
logic, no persistence calls, no third-party SDK details live here -- see
senior-project-pack modularity checklist, layer boundaries.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_db_session,
    get_settings,
    get_storage_provider,
    get_workspace_id,
    require_admin_upload,
)
from app.core.config import Settings
from app.schemas.documents import (
    DocumentListResponse,
    DocumentResponse,
    to_document_list_item,
    to_document_response,
)
from app.services import document_service
from app.storage.base import StorageProvider

router = APIRouter(tags=["documents"])


@router.post("/documents", response_model=DocumentResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_document(
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
    title: str | None = Form(default=None),
    country: str | None = Form(default=None),
    country_code: str | None = Form(default=None),
    language: str | None = Form(default=None),
    therapy_area: str | None = Form(default=None),
    technology_type: str | None = Form(default=None),
    assessment_body: str | None = Form(default=None),
    session: AsyncSession = Depends(get_db_session),
    workspace_id: str = Depends(get_workspace_id),
    storage: StorageProvider = Depends(get_storage_provider),
    settings: Settings = Depends(get_settings),
    _admin: None = Depends(require_admin_upload),
) -> DocumentResponse:
    document = await document_service.create_document(
        session=session,
        workspace_id=workspace_id,
        storage=storage,
        settings=settings,
        file=file,
        text=text,
        title=title,
        country=country,
        country_code=country_code,
        language=language,
        therapy_area=therapy_area,
        technology_type=technology_type,
        assessment_body=assessment_body,
    )
    return to_document_response(document)


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    session: AsyncSession = Depends(get_db_session),
    workspace_id: str = Depends(get_workspace_id),
) -> DocumentListResponse:
    documents = await document_service.list_documents(session=session, workspace_id=workspace_id)
    items = [to_document_list_item(doc) for doc in documents]
    return DocumentListResponse(items=items, total=len(items))
