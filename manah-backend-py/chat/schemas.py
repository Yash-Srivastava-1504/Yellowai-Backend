"""
Manah Backend — Chat Schemas (Pydantic v2)
"""
from typing import Optional
from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    title: Optional[str] = "New Conversation"


class SessionOut(BaseModel):
    sessionId: int
    title: str
    createdAt: str


class SessionListItem(BaseModel):
    id: int
    title: str
    created_at: str
    last_message_at: Optional[str] = None
    lastMessage: Optional[str] = None


class SessionsResponse(BaseModel):
    sessions: list[SessionListItem]


class MessageItem(BaseModel):
    id: int
    sender: str
    text: str
    created_at: str


class HistoryResponse(BaseModel):
    sessionId: int
    title: str
    messages: list[MessageItem]


class SendMessageRequest(BaseModel):
    sessionId: int
    message: str = Field(..., min_length=1)


class SendMessageResponse(BaseModel):
    reply: str
    sessionId: int


class SummarizeRequest(BaseModel):
    sessionId: int


class SummarizeResponse(BaseModel):
    summary: str
    updatedAt: Optional[str] = None
