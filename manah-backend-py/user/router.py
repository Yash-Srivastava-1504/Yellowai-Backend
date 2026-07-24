"""
Manah Backend — User Router
GET    /api/user/me      — get profile
PUT    /api/user/me      — update profile
DELETE /api/user/account — delete account and all data
"""
from typing import Annotated, Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from auth.middleware import CurrentUser, get_current_user
from database import get_db

router = APIRouter(prefix="/api/user", tags=["User"])

VALID_LANGUAGES = {"en", "hi", "hinglish"}
VALID_TONES = {"didi", "bhaiya", "friend"}


# ── Schemas ────────────────────────────────────────────────────────────────────

class UserProfile(BaseModel):
    id: int
    name: str
    email: str
    language: str
    tone: str
    avatar: str
    created_at: str


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    language: Optional[str] = None
    tone: Optional[str] = None
    avatar: Optional[str] = None


class MessageResponse(BaseModel):
    message: str


# ── GET /api/user/me ───────────────────────────────────────────────────────────

@router.get("/me", response_model=UserProfile)
async def get_profile(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[aiosqlite.Connection, Depends(get_db)],
):
    async with db.execute(
        "SELECT id, name, email, language, tone, avatar, created_at FROM users WHERE id = ?",
        (user.id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return UserProfile(**dict(row))


# ── PUT /api/user/me ───────────────────────────────────────────────────────────

@router.put("/me", response_model=UserProfile)
async def update_profile(
    body: UpdateProfileRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[aiosqlite.Connection, Depends(get_db)],
):
    if body.language is not None and body.language not in VALID_LANGUAGES:
        raise HTTPException(status_code=400, detail="Invalid language. Must be en, hi, or hinglish.")
    if body.tone is not None and body.tone not in VALID_TONES:
        raise HTTPException(status_code=400, detail="Invalid tone. Must be didi, bhaiya, or friend.")

    updates: dict = {}
    if body.name is not None:     updates["name"] = body.name
    if body.language is not None: updates["language"] = body.language
    if body.tone is not None:     updates["tone"] = body.tone
    if body.avatar is not None:   updates["avatar"] = body.avatar

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    await db.execute(
        f"UPDATE users SET {set_clause} WHERE id = ?",
        (*updates.values(), user.id),
    )
    await db.commit()

    async with db.execute(
        "SELECT id, name, email, language, tone, avatar, created_at FROM users WHERE id = ?",
        (user.id,),
    ) as cur:
        row = await cur.fetchone()

    return UserProfile(**dict(row))


# ── DELETE /api/user/account ───────────────────────────────────────────────────

@router.delete("/account", response_model=MessageResponse)
async def delete_account(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[aiosqlite.Connection, Depends(get_db)],
    response: Response,
):
    """Cascade-delete user and all associated data (FK ON DELETE CASCADE handles the rest)."""
    await db.execute("DELETE FROM users WHERE id = ?", (user.id,))
    await db.commit()
    response.delete_cookie("refreshToken")
    return MessageResponse(message="Account and all associated data deleted successfully.")
