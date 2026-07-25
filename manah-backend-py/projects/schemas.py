"""
ChatBot Platform — Projects Schemas
Pydantic models for the projects + prompts API.
"""
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Request schemas ────────────────────────────────────────────────────────────

class CreateProjectRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = Field(default="", max_length=500)
    system_prompt: Optional[str] = Field(default="", description="Initial system prompt for the project")


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)


class SetPromptRequest(BaseModel):
    content: str = Field(..., min_length=1, description="New active system prompt content")


# ── Response schemas ───────────────────────────────────────────────────────────

class PromptOut(BaseModel):
    id: str
    project_id: str
    content: str
    is_active: bool
    created_at: str


class ProjectOut(BaseModel):
    id: str
    user_id: str
    name: str
    description: str
    created_at: str
    updated_at: str
    active_prompt: Optional[PromptOut] = None


class ProjectListOut(BaseModel):
    projects: list[ProjectOut]


class MessageOut(BaseModel):
    message: str
