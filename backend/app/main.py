"""FastAPI app entrypoint. Loads the embedding model + trained GNN once at
startup (see the lifespan handler below) so neither is reloaded per
request -- loading a sentence-transformers model and a checkpoint is
expensive enough that doing it per /score call would make every message
send slow."""

import sys
from contextlib import asynccontextmanager
from pathlib import Path

import torch
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes.public_api import router as public_api_router
from .api.routes.report import router as report_router
from .api.routes.score import router as score_router
from .core.config import get_settings
from .services.embedding_store import LocalEmbeddingStore

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


@app.get("/health")
async def health():
    """Unauthenticated liveness probe — for platform health checks and the
    keep-alive ping that keeps a free HF Space from sleeping. POST /score can't
    serve this purpose: it requires the shared secret and does real work (an
    Anthropic call), so it's neither free nor safe to ping."""
    return {"status": "ok"}
