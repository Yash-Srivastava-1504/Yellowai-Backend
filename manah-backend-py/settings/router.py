"""
Manah Backend — Settings Router
GET /api/settings  — get user settings
PUT /api/settings  — update user settings
"""
from typing import Annotated, Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth.middleware import CurrentUser, get_current_user
from database import get_db

router = APIRouter(prefix="/api/settings", tags=["Settings"])

VALID_THEMES = {"light", "dark", "system"}
VALID_NOTIF_TIMES = {"morning", "afternoon", "evening", "night"}
VALID_COMPANIONS = {"didi", "bhaiya", "friend"}


# ── Schemas ────────────────────────────────────────────────────────────────────

class SettingsOut(BaseModel):
    theme: str
    notifications: bool
    notifTime: str
    companion: str
    anonymous: bool
    weeklyReport: bool


class SettingsUpdateRequest(BaseModel):
    theme: Optional[str] = None
    notifications: Optional[bool] = None
    notifTime: Optional[str] = None
    companion: Optional[str] = None
    anonymous: Optional[bool] = None
    weeklyReport: Optional[bool] = None


# ── GET /api/settings ──────────────────────────────────────────────────────────

@router.get("", response_model=SettingsOut)
async def get_settings_endpoint(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[aiosqlite.Connection, Depends(get_db)],
):
    await db.execute("INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)", (user.id,))
    await db.commit()

    async with db.execute("SELECT * FROM user_settings WHERE user_id = ?", (user.id,)) as cur:
        row = dict(await cur.fetchone())

    return SettingsOut(
        theme=row["theme"],
        notifications=bool(row["notifications"]),
        notifTime=row["notif_time"],
        companion=row["companion"],
        anonymous=bool(row["anonymous"]),
        weeklyReport=bool(row["weekly_report"]),
    )


# ── PUT /api/settings ──────────────────────────────────────────────────────────

@router.put("", response_model=SettingsOut)
async def update_settings(
    body: SettingsUpdateRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[aiosqlite.Connection, Depends(get_db)],
):
    if body.theme is not None and body.theme not in VALID_THEMES:
        raise HTTPException(status_code=400, detail=f"theme must be one of: {', '.join(VALID_THEMES)}")
    if body.notifTime is not None and body.notifTime not in VALID_NOTIF_TIMES:
        raise HTTPException(status_code=400, detail=f"notifTime must be one of: {', '.join(VALID_NOTIF_TIMES)}")
    if body.companion is not None and body.companion not in VALID_COMPANIONS:
        raise HTTPException(status_code=400, detail=f"companion must be one of: {', '.join(VALID_COMPANIONS)}")

    await db.execute("INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)", (user.id,))

    updates: dict = {}
    if body.theme is not None:         updates["theme"] = body.theme
    if body.notifications is not None: updates["notifications"] = 1 if body.notifications else 0
    if body.notifTime is not None:     updates["notif_time"] = body.notifTime
    if body.companion is not None:     updates["companion"] = body.companion
    if body.anonymous is not None:     updates["anonymous"] = 1 if body.anonymous else 0
    if body.weeklyReport is not None:  updates["weekly_report"] = 1 if body.weeklyReport else 0

    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    await db.execute(
        f"UPDATE user_settings SET {set_clause} WHERE user_id = ?",
        (*updates.values(), user.id),
    )

    # Sync companion → user tone
    if body.companion is not None:
        await db.execute("UPDATE users SET tone = ? WHERE id = ?", (body.companion, user.id))

    await db.commit()

    async with db.execute("SELECT * FROM user_settings WHERE user_id = ?", (user.id,)) as cur:
        row = dict(await cur.fetchone())

    return SettingsOut(
        theme=row["theme"],
        notifications=bool(row["notifications"]),
        notifTime=row["notif_time"],
        companion=row["companion"],
        anonymous=bool(row["anonymous"]),
        weeklyReport=bool(row["weekly_report"]),
    )
