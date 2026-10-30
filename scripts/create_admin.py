"""Provision an operator account locally without exposing a bootstrap HTTP route."""
import asyncio
import getpass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.db.engine import AsyncSessionLocal, init_db
from server.models.models import UserRole
from server.services.authentication import authentication_service


async def main() -> None:
    username = input("Operator username: ").strip()
    email = input("Email: ").strip()
    password = getpass.getpass("Password (10+ characters): ")
    if password != getpass.getpass("Confirm password: "):
        raise ValueError("Passwords do not match")
    await init_db()
    async with AsyncSessionLocal() as session:
        user = await authentication_service.register(session, username=username, email=email, password=password)
        user.role = UserRole.ADMIN
        await session.commit()
    print("Operator created. Sign in through the web UI.")


if __name__ == "__main__":
    asyncio.run(main())
