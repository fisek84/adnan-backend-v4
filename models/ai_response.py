from pydantic import BaseModel

class AIResponse(BaseModel):
    result: str

