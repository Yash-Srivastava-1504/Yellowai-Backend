"""
Manah Backend — Auth Router
POST /api/auth/signup
POST /api/auth/login
POST /api/auth/refresh
POST /api/auth/logout
"""
from typing import Annotated, Optional

import aiosqlite
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from jose import JWTError

from auth import schemas, service
from database import get_db

router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.post("/signup", response_model=schemas.AuthResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    body: schemas.SignupRequest,
    response: Response,
    db: Annotated[aiosqlite.Connection, Depends(get_db)],
):
    """Register a new user account."""
    existing = await service.get_user_by_email(db, body.email)
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    password_hash = service.hash_password(body.password)
    display_name = body.name or body.email.split("@")[0]
    user_id = await service.create_user(db, body.email, password_hash, display_name)

    user = await service.get_user_by_id(db, user_id)
    access_token = service.create_access_token(user_id, user["email"])
    refresh_token = service.create_refresh_token(user_id)
    await service.store_refresh_token(db, user_id, refresh_token)
    await service.log_action(db, user_id, "signup")

    _set_refresh_cookie(response, refresh_token)
    return schemas.AuthResponse(
        token=access_token,
        refreshToken=refresh_token,
        user=schemas.UserOut(**{k: user[k] for k in ("id", "name", "email", "language", "tone", "avatar")}),
    )


@router.post("/login", response_model=schemas.AuthResponse)
async def login(
    body: schemas.LoginRequest,
    response: Response,
    db: Annotated[aiosqlite.Connection, Depends(get_db)],
):
    """Authenticate with email + password."""
    user = await service.get_user_by_email(db, body.email)
    if not user or not service.verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    await db.execute("UPDATE users SET last_login = datetime('now') WHERE id = ?", (user["id"],))
    await db.commit()

    access_token = service.create_access_token(user["id"], user["email"])
    refresh_token = service.create_refresh_token(user["id"])
    await service.store_refresh_token(db, user["id"], refresh_token)
    await service.log_action(db, user["id"], "login")

    _set_refresh_cookie(response, refresh_token)
    return schemas.AuthResponse(
        token=access_token,
        refreshToken=refresh_token,
        user=schemas.UserOut(**{k: user[k] for k in ("id", "name", "email", "language", "tone", "avatar")}),
    )


@router.post("/refresh", response_model=schemas.RefreshResponse)
async def refresh(
    body: schemas.RefreshRequest,
    db: Annotated[aiosqlite.Connection, Depends(get_db)],
    refreshToken: Annotated[Optional[str], Cookie()] = None,
):
    """Issue a new access token using a valid refresh token."""
    incoming_token = body.refreshToken or refreshToken
    if not incoming_token:
        raise HTTPException(status_code=401, detail="Refresh token required")

    try:
        decoded = service.decode_refresh_token(incoming_token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    stored = await service.get_stored_refresh_token(db, incoming_token, decoded["id"])
    if not stored:
        raise HTTPException(status_code=401, detail="Refresh token has been revoked or expired")

    user = await service.get_user_by_id(db, decoded["id"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    new_access_token = service.create_access_token(user["id"], user["email"])
    return schemas.RefreshResponse(token=new_access_token)


@router.post("/logout", response_model=schemas.MessageResponse)
async def logout(
    body: schemas.RefreshRequest,
    response: Response,
    db: Annotated[aiosqlite.Connection, Depends(get_db)],
    refreshToken: Annotated[Optional[str], Cookie()] = None,
):
    """Revoke refresh token and clear cookie."""
    token = body.refreshToken or refreshToken
    if token:
        await service.revoke_refresh_token(db, token)
    response.delete_cookie("refreshToken")
    return schemas.MessageResponse(message="Logged out successfully")


# ── Cookie helper ──────────────────────────────────────────────────────────────

def _set_refresh_cookie(response: Response, token: str) -> None:
    from config import get_settings
    settings = get_settings()
    response.set_cookie(
        key="refreshToken",
        value=token,
        httponly=True,
        secure=settings.is_production,
        samesite="strict",
        max_age=settings.JWT_REFRESH_EXPIRES_IN,
    )
