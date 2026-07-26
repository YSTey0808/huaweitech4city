"""Centralized settings, read from environment variables (locally, from
backend/.env; on Render, from the platform's env var UI -- see
docs/backend.md)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = BACKEND_DIR.parent
PIPELINE_DIR = REPO_ROOT / "pipeline"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BACKEND_DIR / ".env"), extra="ignore")

    supabase_url: str
    supabase_service_role_key: str
    anthropic_api_key: str  # read directly by pipeline/gnn/llm_stage.py via os.getenv; kept here so
    # startup fails fast (missing env var) instead of failing deep inside the first LLM call.
    backend_shared_secret: str

    # Comma-separated, not JSON -- simpler to set correctly in Render's env var UI.
    allowed_origins: str = "http://localhost:5173"

    # message_graph_sage_new.pt = trained on the newer, larger dataset (see
    # pipeline/reports/learning_curve/) -- promoted to the served default.
    # message_graph_sage_old.pt = trained on the original dataset (previous production
    # default); kept for comparison/rollback. Swap deliberately here, not as a side
    # effect of a checkpoint file rename.
    checkpoint_path: Path = PIPELINE_DIR / "checkpoints" / "message_graph_sage_new.pt"
    embedding_db_path: Path = BACKEND_DIR / "data" / "embeddings.sqlite3"

    score_window_size: int = 10  # last-N messages considered, matches the original mock's window

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
