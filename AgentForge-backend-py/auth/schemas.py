"""
Manah Backend — Auth Schemas (Pydantic v2)
"""
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)
    name: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refreshToken: Optional[str] = None  # also read from cookie


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    language: str
    tone: str
    avatar: str


class AuthResponse(BaseModel):
    token: str
    refreshToken: str
    user: UserOut


class RefreshResponse(BaseModel):
    token: str


class MessageResponse(BaseModel):
    message: str
