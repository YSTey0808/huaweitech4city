"""Request/response models for the public partner API (POST /v1/analyze).

Unlike the internal /score and /report schemas, these are a PUBLISHED
CONTRACT -- a partner writes code against them and we cannot silently change
field names. They also carry the full response shape (the internal routes
return a bare dict), because FastAPI turns `response_model` into the response
schema at /docs, and that generated page is the partner-facing API reference.

Adding an optional field is safe. Renaming or removing one is a breaking
change and needs a new path prefix (/v2/...), not an edit here.
"""

from pydantic import BaseModel, Field, field_validator

# Bounds the per-call cost: every /v1/analyze request is one Anthropic call
# whose prompt contains every message in the window (pipeline/gnn/llm_stage.py
# judges from the full window, not a GNN-selected top-k). The internal path
# uses a window of 10 (scoring_service.WINDOW_SIZE); partners get more room
# since they choose their own window, but not unbounded room.
MAX_PARTNER_WINDOW = 50


class PartnerMessage(BaseModel):
    """One message in the partner's conversation, in the pipeline's canonical
    shape (see pipeline/inference.py's module docstring). This mirrors what
    message_mapper.supabase_row_to_pipeline_message() produces for our own
    rows -- partners just hand us the canonical shape directly."""

    message_id: str = Field(description="Your identifier for this message. Echoed back in evidence. Unique within the request.")
    sender_id: str = Field(description="Your identifier for the author. Used to build same-speaker graph edges; any stable opaque string works.")
    text: str = Field(description="The message content, as sent. Code-mixed Singlish/Manglish/Mandarin is expected and supported.")
    timestamp: float | None = Field(default=None, description="Unix epoch seconds. Optional -- array order is used when omitted.")
    reply_to_message_id: str | None = Field(default=None, description="message_id this replies to, if your product has threading.")


class AnalyzeRequest(BaseModel):
    conversation_id: str | None = Field(
        default=None,
        description="Your thread identifier. Purely a correlation handle -- echoed back untouched, never stored.",
    )
    messages: list[PartnerMessage] = Field(
        description=f"Chronological, oldest first. 1-{MAX_PARTNER_WINDOW} messages.",
    )

    @field_validator("messages")
    @classmethod
    def messages_within_bounds(cls, v: list) -> list:
        if not v:
            raise ValueError("messages must not be empty")
        if len(v) > MAX_PARTNER_WINDOW:
            raise ValueError(f"messages must contain at most {MAX_PARTNER_WINDOW} items")
        return v

    @field_validator("messages")
    @classmethod
    def message_ids_unique(cls, v: list) -> list:
        # Not cosmetic: embed_conversations() returns a message_id -> vector
        # dict, so duplicate ids would silently collapse into one embedding
        # and the graph would be built with the wrong node count. Reject at
        # the boundary rather than scoring something the caller didn't send.
        ids = [m.message_id for m in v]
        if len(set(ids)) != len(ids):
            raise ValueError("message_id values must be unique within a request")
        return v


class EvidenceMessage(BaseModel):
    message_id: str = Field(description="Your original message_id, unchanged.")
    text: str = Field(description="The message text that drove the verdict.")
    score: float = Field(description="This message's contribution to the conversation verdict. A ranking signal, not a standalone probability.")
    tags: list[str] = Field(default_factory=list, description="Harm categories the model attached, e.g. ['grooming'].")


class AnalyzeResponse(BaseModel):
    conversation_id: str | None = Field(description="Echoed from the request.")
    conversation_label: str = Field(description="'safe' or 'harmful'.")
    conversation_confidence: float = Field(description="Model confidence in the label, 0-1.")
    severity: str | None = Field(default=None, description="Severity when harmful, e.g. 'low' | 'medium' | 'high'. Null when safe.")
    top_evidence_messages: list[EvidenceMessage] = Field(
        default_factory=list,
        description="The specific messages behind the verdict. Empty when safe.",
    )
    gentle_alert_text: str | None = Field(
        default=None,
        description="A non-alarming, user-facing explanation you can surface directly in your UI. Null when safe.",
    )
    model_version: str = Field(description="Embedding model backing this verdict. Changes here can shift scores.")
