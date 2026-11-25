import threading
import os
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.auth import (
    SESSION_COOKIE,
    SESSION_SECONDS,
    auth_configuration_status,
    csrf_token_for_session,
    create_session_token,
    owner_login_matches,
    require_owner,
    revoke_session_token,
    verify_session_token,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])
_LOGIN_WINDOW_SECONDS = 15 * 60
_MAX_LOGIN_FAILURES = 5
_login_attempts: dict[str, list[float]] = {}
_login_attempts_lock = threading.Lock()


def _check_login_limit(client_host: str) -> None:
    now = time.monotonic()
    with _login_attempts_lock:
        for host, attempts in list(_login_attempts.items()):
            recent = [
                attempt
                for attempt in attempts
                if now - attempt < _LOGIN_WINDOW_SECONDS
            ]
            if recent:
                _login_attempts[host] = recent
            else:
                del _login_attempts[host]
        attempts = _login_attempts.get(client_host, [])
        if len(attempts) >= _MAX_LOGIN_FAILURES:
            retry_after = int(
                _LOGIN_WINDOW_SECONDS - (now - attempts[0])
            ) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many sign-in attempts. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class AuthStatus(BaseModel):
    configured: bool
    authenticated: bool
    csrf_token: str | None = None


def _secure_cookie() -> bool:
    return (
        os.environ.get("SMARTBILL_ENV", "development").strip().lower()
        == "production"
        or os.environ.get("SMARTBILL_COOKIE_SECURE", "false").lower() == "true"
    )


@router.get(
    "/status",
    response_model=AuthStatus,
    summary="Check owner sign-in status",
    description="Return whether owner authentication is configured and signed in.",
)
def get_auth_status(request: Request) -> AuthStatus:
    session_token = request.cookies.get(SESSION_COOKIE)
    authenticated = verify_session_token(session_token) is not None
    return AuthStatus(
        configured=auth_configuration_status(),
        authenticated=authenticated,
        csrf_token=csrf_token_for_session(session_token) if authenticated else None,
    )


@router.post(
    "/login",
    response_model=AuthStatus,
    summary="Sign in as the shop owner",
    responses={
        401: {"description": "Username or password is incorrect."},
        503: {"description": "Owner sign-in is not configured."},
    },
)
def login(
    payload: LoginRequest, request: Request, response: Response
) -> AuthStatus:
    if not auth_configuration_status():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Owner sign-in configuration is incomplete.",
        )
    client_host = request.client.host if request.client else "unknown"
    _check_login_limit(client_host)
    if not owner_login_matches(payload.username, payload.password):
        with _login_attempts_lock:
            _login_attempts.setdefault(client_host, []).append(time.monotonic())
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Username or password is incorrect.",
        )
    with _login_attempts_lock:
        _login_attempts.pop(client_host, None)

    token = create_session_token(payload.username.strip())
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=_secure_cookie(),
        samesite="strict",
        path="/",
    )
    return AuthStatus(
        configured=True,
        authenticated=True,
        csrf_token=csrf_token_for_session(token),
    )


@router.post(
    "/logout",
    response_model=AuthStatus,
    summary="Sign out",
)
def logout(
    request: Request,
    response: Response,
    _username: str = Depends(require_owner),
) -> AuthStatus:
    revoke_session_token(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(
        key=SESSION_COOKIE,
        httponly=True,
        secure=_secure_cookie(),
        samesite="strict",
        path="/",
    )
    return AuthStatus(
        configured=auth_configuration_status(),
        authenticated=False,
        csrf_token=None,
    )
