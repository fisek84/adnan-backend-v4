from pydantic import BaseModel

class AICommand(BaseModel):
    text: str

