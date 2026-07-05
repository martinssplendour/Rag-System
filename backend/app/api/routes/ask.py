from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_evidence_assistant_service, get_workspace_id
from app.rag.llm_providers import (
    LLMProviderConfigurationError,
    LLMProviderError,
)
from app.schemas.answers import AskRequest, AskResponse
from app.services.evidence_assistant_service import EvidenceAssistantService

router = APIRouter(tags=["ask"])


@router.post("/ask", response_model=AskResponse)
async def ask(
    payload: AskRequest,
    workspace_id: str = Depends(get_workspace_id),
    service: EvidenceAssistantService = Depends(get_evidence_assistant_service),
) -> AskResponse:
    try:
        return await service.ask(
            question=payload.question,
            workspace_id=str(workspace_id),
            country=payload.country,
            document_ids=payload.document_ids,
        )
    except LLMProviderConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "LLM_PROVIDER_CONFIGURATION_ERROR",
                "message": "The answer provider is not configured correctly.",
            },
        ) from exc
    except LLMProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "UPSTREAM_PROVIDER_ERROR",
                "message": "The answer provider failed safely.",
            },
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "ASK_PIPELINE_CONFIGURATION_ERROR",
                "message": "The ask pipeline is not configured correctly.",
            },
        ) from exc
