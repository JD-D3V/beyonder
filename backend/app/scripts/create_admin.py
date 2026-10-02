"""Create the single owner account.

    python -m app.scripts.create_admin

Reads ADMIN_EMAIL and ADMIN_PASSWORD from the environment/.env. Refuses if
either is empty or if an admin already exists.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.passwords import hash_password
from ..common.config import settings
from ..storage.db import get_session
from ..storage.models import User


def create_admin(s: Session, email: str, password: str) -> User:
    email = email.strip().lower()
    if not email or not password:
        raise SystemExit("ADMIN_EMAIL and ADMIN_PASSWORD must both be set.")
    if len(password) < 8:
        raise SystemExit("ADMIN_PASSWORD must be at least 8 characters.")
    if s.execute(select(User.id).where(User.is_admin.is_(True)).limit(1)).first():
        raise SystemExit("An admin already exists; refusing to create another.")
    user = User(email=email, password_hash=hash_password(password), is_admin=True)
    s.add(user)
    s.flush()
    return user


def main() -> None:
    with get_session() as s:
        user = create_admin(s, settings.admin_email, settings.admin_password)
        print(f"Created admin {user.email}")


if __name__ == "__main__":
    main()
