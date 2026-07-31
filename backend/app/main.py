"""FastAPI app entrypoint. Loads the embedding model + trained GNN once at
startup (see the lifespan handler below) so neither is reloaded per
request -- loading a sentence-transformers model and a checkpoint is
expensive enough that doing it per /score call would make every message
send slow."""

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import torch
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.routes.public_api import router as public_api_router
from .api.routes.report import router as report_router
from .api.routes.score import router as score_router
from .core.config import get_settings
from .core.supabase_client import get_supabase
from .services.embedding_store import LocalEmbeddingStore

logger = logging.getLogger(__name__)

# pipeline/ is a flat script directory, not a package (embed.py/train.py/gnn/
# import each other as top-level modules) -- see pipeline/inference.py's
# module docstring. Adding it to sys.path keeps that untouched.
PIPELINE_DIR = Path(__file__).resolve().parent.parent.parent / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from embed import DEFAULT_MODEL, load_embedding_model  # noqa: E402
from gnn.conversation_gnn import MessageGraphSAGE  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # gnn/llm_stage.py reads ANTHROPIC_API_KEY from os.environ directly (see
    # config.py's note on the field). Its own module-level load_dotenv() cannot
    # supply it: dotenv's find_dotenv() walks up from the *calling* file, so it
    # searches pipeline/gnn/ -> pipeline/ -> repo root, and backend/.env is on
    # none of those paths. The key therefore only ever reached the pipeline
    # because deploy/backend.service passes uvicorn --env-file -- an invisible
    # dependency on how the process happens to be launched, which is why a plain
    # `uvicorn app.main:app` (locally, or any restart without that flag) made
    # every /score raise "ANTHROPIC_API_KEY not set" while /health stayed green:
    # Settings reads the same file by absolute path, so startup succeeded.
    #
    # Settings is the single source of truth for config, so publish the key from
    # it here and the pipeline works however uvicorn was invoked. setdefault, not
    # assignment: a real environment variable is the more explicit signal and
    # must win over the .env file.
    os.environ.setdefault("ANTHROPIC_API_KEY", settings.anthropic_api_key)

    app.state.embed_model = load_embedding_model(DEFAULT_MODEL)
    app.state.model_version = DEFAULT_MODEL

    model = MessageGraphSAGE()
    model.load_state_dict(torch.load(settings.checkpoint_path, map_location="cpu"))
    model.eval()
    app.state.model = model

    app.state.embedding_store = LocalEmbeddingStore(settings.embedding_db_path)

    yield


app = FastAPI(
    title="Harm Pattern Recognition API",
    lifespan=lifespan,
    description=(
        "Real-time harm-pattern detection (cyberbullying, grooming, scams) for "
        "code-mixed Singlish/Manglish/Mandarin chat.\n\n"
        "**Partners: you only need `POST /v1/analyze`.** Send a conversation, get a "
        "verdict back — no account, no data migration, no model to host. "
        "See `docs/public_api.md`.\n\n"
        "The `Internal` endpoints below are used by our own frontend via its Supabase "
        "Edge Function proxies and are not part of the public contract."
    ),
)

# Deliberately NOT widened for the public API. /v1/analyze is
# server-to-server: an API key belongs on a partner's backend, never in a
# browser where it would be readable by anyone who opens devtools. Keeping
# this origin-restricted means a browser fetch fails by design rather than
# quietly encouraging partners to ship their key to the client.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins_list,
    allow_methods=["POST"],
    allow_headers=["*"],
)

app.include_router(public_api_router)
app.include_router(score_router)
app.include_router(report_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Uvicorn already logs a traceback for anything that escapes a route, but it
    logs no request context and Starlette's default 500 body is plain text. The
    plain-text body is why an exception in /score reaches the browser as an empty
    object: score-message does `res.json().catch(() => ({}))`, so the reason is
    discarded before anyone can read it. Logging the method+path here ties the
    traceback to the endpoint, and the JSON body gives the Edge Function
    something to relay.

    The detail is deliberately opaque. This VM is internet-facing and the same
    handler covers the partner-facing /v1/analyze -- exception text can carry
    connection strings, row contents, or key fragments. The traceback belongs in
    journalctl, not in a response.
    """
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal error"})


@app.get("/health")
async def health():
    """Unauthenticated liveness probe — for platform health checks and the
    keep-alive ping that keeps a free HF Space from sleeping. POST /score can't
    serve this purpose: it requires the shared secret and does real work (an
    Anthropic call), so it's neither free nor safe to ping.

    Deliberately unconditional: this is a *liveness* probe, and deploy/redeploy.sh
    gates a rollback on it. It answers "is the process serving?" and nothing more.
    For "can this process actually score?", see /ready -- the distinction matters,
    because a 200 here says nothing about Anthropic, Supabase, or the model.
    """
    return {"status": "ok"}


@app.get("/ready")
async def ready(request: Request):
    """Readiness: are the things POST /score depends on actually usable?

    Booleans only, no values and no error strings -- this endpoint is
    unauthenticated on an internet-facing host, so it must not become a way to
    read config or probe internal failure messages. `false` is a signal to go
    look at journalctl, not a diagnosis in itself.

    Never returns non-200: a readiness report that fails to render is useless.
    Callers read the body, not the status.
    """
    settings = get_settings()
    state = request.app.state

    # The lifespan handler sets these before uvicorn serves anything, so in
    # practice a false here means the process is serving a partially-built state
    # -- worth knowing about explicitly rather than inferring from a 500.
    checks = {
        "model": getattr(state, "model", None) is not None,
        "embed_model": getattr(state, "embed_model", None) is not None,
        "embedding_store": getattr(state, "embedding_store", None) is not None,
        # Presence, not validity. Verifying the key would mean a billed Anthropic
        # call on every ping -- exactly what /health's docstring warns against.
        # An expired or revoked key still reports true; that case shows up as a
        # 500 from /score with the reason in journalctl.
        "anthropic_key": bool(settings.anthropic_api_key),
        "supabase": False,
    }

    try:
        get_supabase().table("conversations").select("id").limit(1).execute()
        checks["supabase"] = True
    except Exception:
        logger.exception("readiness: supabase check failed")

    return checks
