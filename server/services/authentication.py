"""Database-backed user registration and credential verification."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.models import User
from .password_hashing import ScryptPasswordHasher


class AuthenticationError(ValueError):
    """Raised when credentials or registration data violate the auth contract."""


class AuthenticationService:
    def __init__(self) -> None:
        self._passwords = ScryptPasswordHasher()

    async def authenticate(
        self,
        session: AsyncSession,
        *,
        username: str,
        password: str,
    ) -> User:
        normalized = username.strip()
        if not password or len(password) > 1024:
            raise AuthenticationError("Invalid credentials")
        result = await session.execute(select(User).where(User.username == normalized))
        user = result.scalar_one_or_none()
        if user is None or not user.is_active:
            raise AuthenticationError("Invalid credentials")
        if not self._passwords.verify(password, user.password_hash):
            raise AuthenticationError("Invalid credentials")
        user.last_login_at = datetime.utcnow()
        await session.flush()
        return user

    async def register(
        self,
        session: AsyncSession,
        *,
        username: str,
        email: str,
        password: str,
        display_name: str = "",
    ) -> User:
        normalized_username = username.strip()
        normalized_email = email.strip().casefold()
        self._validate_registration(normalized_username, normalized_email, password)
        result = await session.execute(
            select(User.id).where(
                or_(User.username == normalized_username, User.email == normalized_email)
            )
        )
        if result.scalar_one_or_none() is not None:
            raise AuthenticationError("Username or email already exists")
        user = User(
            id=str(uuid.uuid4()),
            username=normalized_username,
            email=normalized_email,
            display_name=display_name.strip() or normalized_username,
            password_hash=self._passwords.hash(password),
        )
        session.add(user)
        try:
            await session.flush()
        except IntegrityError as exc:
            await session.rollback()
            raise AuthenticationError("Username or email already exists") from exc
        return user

    @staticmethod
    def _validate_registration(username: str, email: str, password: str) -> None:
        if len(username) < 3 or len(username) > 64:
            raise AuthenticationError("Username must contain 3 to 64 characters")
        if "@" not in email or len(email) > 255:
            raise AuthenticationError("A valid email address is required")
        if len(password) < 10 or len(password) > 1024:
            raise AuthenticationError("Password must contain 10 to 1024 characters")


authentication_service = AuthenticationService()
