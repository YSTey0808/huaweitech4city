"""POST /report -- the human-feedback entrypoint, forwarded by
supabase/functions/report-message (thin proxy, same auth + membership
checks as score-message). Verifies the shared secret, then delegates to
report_service."""

from fastapi import APIRouter, Header, HTTPException, Request

from ...core.config import get_settings
from ...core.supabase_client import get_supabase
from ...schemas.report import ReportRequest
from ...services.report_service import report_message_request

router = APIRouter(tags=["Internal"])


@router.post("/report")
async def report(request: Request, body: ReportRequest, x_backend_secret: str = Header(default="")):
    settings = get_settings()
    if x_backend_secret != settings.backend_shared_secret:
        raise HTTPException(status_code=401, detail="invalid backend secret")

    return report_message_request(
        conversation_id=body.conversation_id,
        msg_id=body.msg_id,
        reason=body.reason,
        supabase=get_supabase(),
        embed_model=request.app.state.embed_model,
        model=request.app.state.model,
        embedding_store=request.app.state.embedding_store,
        model_version=request.app.state.model_version,
        claim=body.claim,
    )
