"""Password hashing (argon2id) and JWT access tokens (HS256)."""

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()  # argon2id with the library's recommended parameters
# Verified against when the email is unknown, so a login takes the same time either way.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

ALGORITHM = "HS256"
ACCESS_TYPE = "access"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_refresh_token() -> str:
    """Opaque random string. Only its sha256 is stored server side."""
    return secrets.token_urlsafe(32)


class TokenExpired(Exception):
    pass


class TokenInvalid(Exception):
    pass


def create_access_token(user_id: UUID, secret: str, ttl: timedelta) -> str:
    now = datetime.now(UTC)
    claims = {"sub": str(user_id), "type": ACCESS_TYPE, "iat": now, "exp": now + ttl}
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


def decode_access_token(token: str, secret: str) -> UUID:
    """User id from a valid access token. Raises TokenExpired or TokenInvalid."""
    try:
        claims = jwt.decode(
            token, secret, algorithms=[ALGORITHM], options={"require": ["sub", "exp", "type"]}
        )
    except jwt.ExpiredSignatureError as e:
        raise TokenExpired from e
    except jwt.PyJWTError as e:
        raise TokenInvalid from e
    if claims.get("type") != ACCESS_TYPE:
        raise TokenInvalid
    try:
        return UUID(claims["sub"])
    except (ValueError, TypeError) as e:
        raise TokenInvalid from e
