"""`get_current_user`: the dependency that protects a route.

    @router.get("/things")
    def list_things(user: User = Depends(get_current_user)): ...

Missing, malformed, expired or revoked-user tokens all give `401 UNAUTHORIZED` with
`WWW-Authenticate: Bearer`.
"""

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.store import User, UserStore
from app.auth.tokens import TokenExpired, TokenInvalid, decode_access_token
from app.core.errors import ApiException, ErrorCode
from app.services import Services, get_services

_bearer = HTTPBearer(auto_error=False)


def unauthorized(message: str, reason: str) -> ApiException:
    return ApiException(
        ErrorCode.UNAUTHORIZED, message, {"reason": reason}, headers={"WWW-Authenticate": "Bearer"}
    )


def get_user_store(svc: Services = Depends(get_services)) -> UserStore:
    if svc.users is None:
        raise ApiException(ErrorCode.INTERNAL_ERROR, "Accounts are unavailable (database not reachable).")
    return svc.users


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    svc: Services = Depends(get_services),
    store: UserStore = Depends(get_user_store),
) -> User:
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials:
        raise unauthorized("Not signed in.", "missing_token")
    try:
        user_id, version = decode_access_token(creds.credentials, svc.jwt_secret)
    except TokenExpired:
        raise unauthorized("Session expired. Refresh the access token.", "token_expired") from None
    except TokenInvalid:
        raise unauthorized("Invalid access token.", "invalid_token") from None
    user = store.get_by_id(user_id)
    if user is None:
        raise unauthorized("Invalid access token.", "unknown_user")
    if user.auth_version != version:
        raise unauthorized("Password changed. Sign in again.", "session_revoked")
    return user
