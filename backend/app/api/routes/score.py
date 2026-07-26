"""POST /score -- the one HTTP entrypoint supabase/functions/score-message
(the thin proxy) forwards to. Verifies the shared secret, then delegates
everything else to scoring_service."""

from fastapi import APIRouter, Header, HTTPException, Request

from ...core.config import get_settings
from ...core.supabase_client import get_supabase
from ...schemas.score import ScoreRequest
from ...services.scoring_service import score_conversation_request

router = APIRouter()


@router.post("/score")
async def score(request: Request, body: ScoreRequest, x_backend_secret: str = Header(default="")):
    settings = get_settings()
    if x_backend_secret != settings.backend_shared_secret:
        raise HTTPException(status_code=401, detail="invalid backend secret")

    return score_conversation_request(
        conversation_id=body.conversation_id,
        supabase=get_supabase(),
        embed_model=request.app.state.embed_model,
        model=request.app.state.model,
        embedding_store=request.app.state.embedding_store,
        model_version=request.app.state.model_version,
    )
