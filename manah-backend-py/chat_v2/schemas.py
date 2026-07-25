"""
ChatBot Platform — Chat v2 Schemas
"""
from typing import Optional
from pydantic import BaseModel, Field


class MessageItem(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    project_id: str = Field(..., description="UUID of the project to chat with")
    messages: list[MessageItem] = Field(..., min_length=1)
