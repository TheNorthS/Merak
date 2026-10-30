from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from server.models.models import User
from server.services.authentication import AuthenticationError, AuthenticationService


def _session_returning(value: object) -> Mock:
    result = Mock()
    result.scalar_one_or_none.return_value = value
    session = Mock()
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_register_hashes_password_and_persists_user() -> None:
    service = AuthenticationService()
    session = _session_returning(None)

    user = await service.register(
        session,
        username="researcher",
        email="Researcher@Example.org",
        password="correct-horse-battery-staple",
    )

    assert user.email == "researcher@example.org"
    assert user.password_hash != "correct-horse-battery-staple"
    assert service._passwords.verify(
        "correct-horse-battery-staple", user.password_hash
    )
    session.add.assert_called_once_with(user)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_authenticate_rejects_unknown_user() -> None:
    service = AuthenticationService()
    session = _session_returning(None)

    with pytest.raises(AuthenticationError, match="Invalid credentials"):
        await service.authenticate(
            session,
            username="missing",
            password="not-a-real-password",
        )


def test_registration_rejects_demo_strength_passwords() -> None:
    with pytest.raises(AuthenticationError, match="10 to 1024"):
        AuthenticationService._validate_registration(
            "researcher", "researcher@example.org", "merak"
        )
