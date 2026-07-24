"""
Manah Backend — Mood Router
POST /api/mood  — upsert mood entry (one per user per day)
GET  /api/mood  — list moods (last 30 days or date range)
"""
import json
import re
from typing import Annotated, Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from auth.middleware import CurrentUser, get_current_user
from database import get_db

router = APIRouter(prefix="/api/mood", tags=["Mood"])

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ── Schemas ────────────────────────────────────────────────────────────────────

class MoodRequest(BaseModel):
    date: str
    level: int = Field(..., ge=0, le=4)
    note: Optional[str] = None
    tags: Optional[list[str]] = None

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        if not _DATE_RE.match(v):
            raise ValueError("date must be in YYYY-MM-DD format")
        return v


class MoodEntry(BaseModel):
    id: int
    date: str
    level: int
    note: Optional[str]
    tags: list[str]


class MoodsResponse(BaseModel):
    entries: list[MoodEntry]


# ── POST /api/mood ─────────────────────────────────────────────────────────────

@router.post("", response_model=MoodEntry, status_code=201)
async def log_mood(
    body: MoodRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[aiosqlite.Connection, Depends(get_db)],
):
    tags_json = json.dumps(body.tags or [])

    async with db.execute(
        "SELECT id FROM moods WHERE user_id = ? AND date = ?", (user.id, body.date)
    ) as cur:
        existing = await cur.fetchone()

    if existing:
        await db.execute(
            "UPDATE moods SET level = ?, note = ?, tags = ? WHERE id = ?",
            (body.level, body.note, tags_json, existing["id"]),
        )
        entry_id = existing["id"]
    else:
        async with db.execute(
            "INSERT INTO moods (user_id, date, level, note, tags) VALUES (?, ?, ?, ?, ?)",
            (user.id, body.date, body.level, body.note, tags_json),
        ) as cur:
            entry_id = cur.lastrowid

    await db.commit()

    async with db.execute("SELECT * FROM moods WHERE id = ?", (entry_id,)) as cur:
        row = dict(await cur.fetchone())

    return MoodEntry(
        id=row["id"],
        date=row["date"],
        level=row["level"],
        note=row["note"],
        tags=json.loads(row["tags"] or "[]"),
    )


# ── GET /api/mood ──────────────────────────────────────────────────────────────

@router.get("", response_model=MoodsResponse)
async def get_moods(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[aiosqlite.Connection, Depends(get_db)],
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
):
    if start and end:
        if not _DATE_RE.match(start) or not _DATE_RE.match(end):
            raise HTTPException(status_code=400, detail="start and end must be in YYYY-MM-DD format")
        async with db.execute(
            "SELECT id, date, level, note, tags FROM moods WHERE user_id = ? AND date >= ? AND date <= ? ORDER BY date ASC",
            (user.id, start, end),
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
    else:
        async with db.execute(
            "SELECT id, date, level, note, tags FROM moods WHERE user_id = ? ORDER BY date DESC LIMIT 30",
            (user.id,),
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]

    return MoodsResponse(
        entries=[
            MoodEntry(
                id=r["id"],
                date=r["date"],
                level=r["level"],
                note=r["note"],
                tags=json.loads(r["tags"] or "[]"),
            )
            for r in rows
        ]
    )
