# Build from the REPO ROOT (not backend/), e.g.:
#   docker build -f backend/Dockerfile -t huaweitech4city-backend .
# On Render: Root Directory = repo root, Dockerfile Path = backend/Dockerfile.
# The build context must include the sibling pipeline/ directory -- see
# docs/backend.md's "Deployment" section for why Root Directory can't be
# set to backend/ alone.
FROM python:3.11-slim

WORKDIR /app

COPY pipeline/requirements.txt ./pipeline/requirements.txt
COPY backend/requirements.txt ./backend/requirements.txt
# Install CPU-only torch first (the host is CPU-only; the default Linux wheel
# pulls multi-GB CUDA/nvidia deps we never use). Installing it first satisfies
# the unpinned `torch` line in pipeline/requirements.txt so the second install
# skips it. torch_geometric is pure-Python on PyPI and unaffected.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r pipeline/requirements.txt -r backend/requirements.txt

# Bake the ~2.4 GB SEA-LION embedding model into the image so cold starts /
# restarts read it from local disk instead of re-downloading it from the HF hub.
# HF_HOME is an ENV (not a build arg) so the runtime process resolves the same
# cache path. This runs before the code COPYs so the heavy layer stays cached
# across code-only changes.
ENV HF_HOME=/app/hf-cache
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('aisingapore/SEA-LION-ModernBERT-Embedding-600M')"

# Checkpoints are committed to git (a few MB) -- no separate fetch/LFS step
# needed, this COPY brings them into the image directly.
COPY pipeline/ ./pipeline/
COPY backend/ ./backend/

WORKDIR /app/backend
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
