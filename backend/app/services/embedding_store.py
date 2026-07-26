"""
Embedding cache: the node data in the message graph is worth persisting
(a sentence-transformers forward pass per message); the graph's edges are
not (build_message_graph() rebuilds temporal/same_speaker/reply_to edges
fresh from message metadata on every call -- cheap over a small window).
See docs/backend.md's "Graph storage & lifecycle" section for the full
reasoning.

LocalEmbeddingStore (this file, v1) is a SQLite-backed cache, fine for a
single backend instance. It intentionally exposes the same shape a future
SupabaseEmbeddingStore (Postgres/pgvector-backed, v2 -- not built yet)
would, so swapping is a one-line change in whatever wires this up
(currently app/main.py's lifespan handler), not a rewrite of callers.
Keyed by (message_id, model_version) so a future embedding-model change
can't silently reuse stale vectors.
"""

import sqlite3
from pathlib import Path
from typing import Protocol

import numpy as np
import torch


class EmbeddingStore(Protocol):
    def get_or_compute(self, messages: list, embed_model, model_version: str) -> list:
        """Returns `messages` with an "embedding" key attached to each dict,
        computing (and persisting) only the ones not already cached."""
        ...


class LocalEmbeddingStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS message_embeddings (
                message_id TEXT NOT NULL,
                model_version TEXT NOT NULL,
                embedding BLOB NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (message_id, model_version)
            )
            """
        )
        self._conn.commit()

    def _get_cached(self, message_ids: list, model_version: str) -> dict:
        if not message_ids:
            return {}
        placeholders = ",".join("?" for _ in message_ids)
        rows = self._conn.execute(
            f"SELECT message_id, embedding FROM message_embeddings "
            f"WHERE model_version = ? AND message_id IN ({placeholders})",
            [model_version, *message_ids],
        ).fetchall()
        return {
            message_id: torch.from_numpy(np.frombuffer(blob, dtype=np.float32).copy())
            for message_id, blob in rows
        }

    def _put(self, message_id: str, model_version: str, embedding: torch.Tensor) -> None:
        blob = embedding.detach().cpu().numpy().astype(np.float32).tobytes()
        self._conn.execute(
            "INSERT OR REPLACE INTO message_embeddings (message_id, model_version, embedding) VALUES (?, ?, ?)",
            (message_id, model_version, blob),
        )
        self._conn.commit()

    def get_or_compute(self, messages: list, embed_model, model_version: str) -> list:
        cached = self._get_cached([m["message_id"] for m in messages], model_version)

        missing = [m for m in messages if m["message_id"] not in cached]
        if missing:
            from embed import embed_conversations  # pipeline/, on sys.path -- see app/main.py

            fresh = embed_conversations(
                [{"messages": [{"message_id": m["message_id"], "content": m["text"]} for m in missing]}],
                embed_model,
            )
            for message_id, vector in fresh.items():
                self._put(message_id, model_version, vector)
            cached.update(fresh)

        return [{**m, "embedding": cached[m["message_id"]]} for m in messages]
