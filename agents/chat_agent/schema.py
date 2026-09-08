from pydantic import BaseModel
from typing import List, Dict, Optional

class ChatInput(BaseModel):
    query: str
    history: List[Dict[str, str]] = []

class ChatOutput(BaseModel):
    response: str
