"""Password hashing with argon2id (argon2-cffi defaults)."""
from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()


def hash_password(pw: str) -> str:
    return _hasher.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, pw)
    except (VerificationError, InvalidHashError):
        return False
