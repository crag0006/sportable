"""``POST /api/v1/assistant`` (contract v0.3 section 8): parse, call the service, return."""

from fastapi import APIRouter

from app.api.deps import Assistant
from app.schemas.assistant import AssistantRequest, AssistantResponse

router = APIRouter(tags=["Assistant"])


@router.post(
    "/assistant",
    response_model=AssistantResponse,
    response_model_exclude_none=True,
    summary="Ask the access assistant one question",
    responses={
        200: {
            "description": "Always 200 once the body validates; `kind` says what happened "
            "(answer, results, clarify, no_information, capability, unavailable)."
        }
    },
)
def ask(body: AssistantRequest, assistant: Assistant) -> AssistantResponse:
    """One stateless turn. The server stores nothing and logs counts only (section 8.8)."""
    return assistant.ask(body)
