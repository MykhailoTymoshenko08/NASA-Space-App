"""Register, login, refresh, logout, me.

The access token (JWT) is returned in the JSON body; the client sends it as `Authorization: Bearer`.
The refresh token is an opaque random string in an httpOnly cookie scoped to `/v1/auth`, rotated on
every refresh and deleted on logout.
"""

from datetime import timedelta

from fastapi import APIRouter, Cookie, Depends, Response
from fastapi.responses import JSONResponse

from app.auth.deps import get_current_user, get_user_store, unauthorized
from app.auth.store import EmailTaken, User, UserStore
from app.auth.tokens import (
    create_access_token,
    hash_password,
    needs_rehash,
    new_refresh_token,
    verify_password,
)
from app.core.config import Settings
from app.core.errors import ApiException, ErrorCode
from app.core.ratelimit import rate_limited
from app.models import AuthTokens, LoginRequest, RegisterRequest, UserOut
from app.services import Services, get_services

router = APIRouter(tags=["auth"])

REFRESH_COOKIE = "refresh_token"
REFRESH_COOKIE_PATH = "/v1/auth"


def _user_out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, created_at=u.created_at)


def _issue(svc: Services, store: UserStore, user: User, status_code: int) -> JSONResponse:
    s: Settings = svc.settings
    access_ttl = timedelta(minutes=s.access_token_ttl_min)
    refresh_ttl = timedelta(days=s.refresh_token_ttl_days)
    refresh = new_refresh_token()
    store.add_refresh_token(user.id, refresh, refresh_ttl)
    body = AuthTokens(
        access_token=create_access_token(user.id, svc.jwt_secret, access_ttl),
        expires_in=int(access_ttl.total_seconds()),
        user=_user_out(user),
    )
    resp = JSONResponse(body.model_dump(mode="json"), status_code=status_code)
    resp.set_cookie(
        REFRESH_COOKIE,
        refresh,
        max_age=int(refresh_ttl.total_seconds()),
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=s.auth_cookie_secure,
        samesite=s.auth_cookie_samesite,
    )
    return resp


def _clear_cookie(resp: Response, s: Settings) -> None:
    resp.delete_cookie(
        REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=s.auth_cookie_secure,
        samesite=s.auth_cookie_samesite,
    )


@router.post("/auth/register", status_code=201, dependencies=[Depends(rate_limited("auth"))])
def register(
    body: RegisterRequest,
    svc: Services = Depends(get_services),
    store: UserStore = Depends(get_user_store),
) -> JSONResponse:
    try:
        user = store.create_user(body.email, hash_password(body.password))
    except EmailTaken:
        raise ApiException(
            ErrorCode.EMAIL_TAKEN, "An account with this email already exists.", {"field": "email"}
        ) from None
    return _issue(svc, store, user, 201)


@router.post("/auth/login", dependencies=[Depends(rate_limited("auth"))])
def login(
    body: LoginRequest,
    svc: Services = Depends(get_services),
    store: UserStore = Depends(get_user_store),
) -> JSONResponse:
    found = store.get_by_email(body.email)
    if not verify_password(found.password_hash if found else None, body.password):
        raise unauthorized("Invalid email or password.", "invalid_credentials")
    if needs_rehash(found.password_hash):
        store.update_password_hash(found.user.id, hash_password(body.password))
    return _issue(svc, store, found.user, 200)


@router.post("/auth/refresh")
def refresh(
    refresh_token: str | None = Cookie(default=None),
    svc: Services = Depends(get_services),
    store: UserStore = Depends(get_user_store),
) -> JSONResponse:
    user_id = store.consume_refresh_token(refresh_token) if refresh_token else None
    user = store.get_by_id(user_id) if user_id else None
    if user is None:
        raise unauthorized(
            "Session expired. Sign in again.",
            "invalid_refresh_token" if refresh_token else "missing_refresh_token",
        )
    return _issue(svc, store, user, 200)


@router.post("/auth/logout", status_code=204)
def logout(
    refresh_token: str | None = Cookie(default=None),
    svc: Services = Depends(get_services),
    store: UserStore = Depends(get_user_store),
) -> Response:
    # Idempotent: no cookie or an unknown token is still a successful logout.
    if refresh_token:
        store.revoke_refresh_token(refresh_token)
    resp = Response(status_code=204)
    _clear_cookie(resp, svc.settings)
    return resp


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> UserOut:
    return _user_out(user)
