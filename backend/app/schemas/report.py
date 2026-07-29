from pydantic import BaseModel, field_validator


class ReportRequest(BaseModel):
    conversation_id: str
    msg_id: str
    reason: str
    # What the reporter asserts (migration 010): 'harmful' = the model
    # missed this; 'safe' = false-positive dispute. Defaults to 'harmful'
    # so pre-claim clients keep working unchanged.
    claim: str = "harmful"

    @field_validator("reason")
    @classmethod
    def reason_not_blank(cls, v: str) -> str:
        # Mirrors the DB check constraint (migration 008) so a blank reason
        # fails fast at the API boundary instead of deep in the pipeline.
        if not v.strip():
            raise ValueError("reason must not be blank")
        return v.strip()

    @field_validator("claim")
    @classmethod
    def claim_known(cls, v: str) -> str:
        # Mirrors migration 010's check constraint.
        if v not in ("harmful", "safe"):
            raise ValueError("claim must be 'harmful' or 'safe'")
        return v
