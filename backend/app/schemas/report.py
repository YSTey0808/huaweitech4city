from pydantic import BaseModel, field_validator


class ReportRequest(BaseModel):
    conversation_id: str
    msg_id: str
    reason: str

    @field_validator("reason")
    @classmethod
    def reason_not_blank(cls, v: str) -> str:
        # Mirrors the DB check constraint (migration 008) so a blank reason
        # fails fast at the API boundary instead of deep in the pipeline.
        if not v.strip():
            raise ValueError("reason must not be blank")
        return v.strip()
