"""POST /v1/analyze -- the public partner API.

The one endpoint another company calls. Unlike /score and /report (which are
internal, secret-gated, and assume the conversation already lives in our
Supabase), this takes the messages inline and returns the verdict in the
response body, so a partner integrates by making one HTTP call from their own
backend. See docs/public_api.md.

Server-to-server only. The API key is a server credential and must never be
put in a browser -- CORS in app/main.py is not widened for this route, so a
browser fetch from an unlisted origin fails by design.
"""

import time

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from ...core.supabase_client import get_supabase
from ...schemas.public_api import AnalyzeRequest, AnalyzeResponse
from ...services.api_key_service import log_usage, verify_api_key
from ...services.public_scoring_service import analyze_messages
from ...services.rate_limiter import check_rate_limit

router = APIRouter(prefix="/v1", tags=["Public API"])


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    summary="Analyze a conversation for harm patterns",
    responses={
        401: {"description": "Missing or invalid X-API-Key."},
        422: {"description": "Malformed body — empty/oversized `messages`, or duplicate `message_id`s."},
        429: {"description": "Rate limit exceeded. See the Retry-After header."},
    },
)
async def analyze(
    request: Request,
    body: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    x_api_key: str = Header(default="", description="Your partner API key."),
) -> AnalyzeResponse:
    """
    Send a conversation, get back a harm verdict — no account, no data
    migration, no model to host.

    Detects cyberbullying, grooming and scam patterns in code-mixed
    Singlish/Manglish/Mandarin chat. Every message you send is judged in
    context: the model reads the conversation as a graph (who replied to
    whom, who spoke when), not as isolated strings, so it catches escalation
    patterns that per-message filters miss.

    Your messages are scored in memory and discarded. We log only call
    metadata — timestamp, message count, resulting label — never message
    text and never sender identifiers.

    Authenticate with your key in the `X-API-Key` header.
    """
    supabase = get_supabase()

    key_row = verify_api_key(supabase, x_api_key)
    if key_row is None:
        raise HTTPException(status_code=401, detail="invalid or inactive API key")

    retry_after = check_rate_limit(key_row["id"], key_row["rate_limit_per_min"])
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail=f"rate limit of {key_row['rate_limit_per_min']} requests/min exceeded",
            headers={"Retry-After": str(retry_after)},
        )

    started = time.monotonic()
    response = analyze_messages(
        messages=[m.model_dump() for m in body.messages],
        conversation_id=body.conversation_id,
        supabase=supabase,
        embed_model=request.app.state.embed_model,
        model=request.app.state.model,
        model_version=request.app.state.model_version,
    )
    latency_ms = int((time.monotonic() - started) * 1000)

    # Metadata only, and off the response path -- a logging failure must
    # never turn a served verdict into an error (see log_usage).
    background_tasks.add_task(
        log_usage,
        supabase,
        key_row["id"],
        len(body.messages),
        response["conversation_label"],
        latency_ms,
    )

    return AnalyzeResponse(**response)
