from pydantic import BaseModel


class ScoreRequest(BaseModel):
    conversation_id: str
