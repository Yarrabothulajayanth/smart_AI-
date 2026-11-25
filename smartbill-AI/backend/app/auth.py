import base64
import binascii
import hashlib
import hmac
import os
import secrets
import threading
import time

from fastapi import HTTPException, Request, status

SESSION_COOKIE = "smartbill_owner_session"
SESSION_SECONDS = 8 * 60 * 60
CSRF_HEADER = "X-CSRF-Token"
PASSWORD_HASH_ITERATIONS = 600_000
_MIN_PASSWORD_HASH_ITERATIONS = 100_000
_MAX_PASSWORD_HASH_ITERATIONS = 1_500_000
_MAX_ACTIVE_SESSIONS = 32
_active_sessions: dict[str, int] = {}
_active_sessions_lock = threading.Lock()


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("Owner passwords must be at least 12 characters.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS
    )
    return (
        f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}$"
        f"{salt.hex()}${digest.hex()}"
    )


def _parse_password_hash(value: str) -> tuple[int, bytes, bytes] | None:
    try:
        algorithm, iteration_text, salt_text, digest_text = value.split("$")
        iterations = int(iteration_text)
        salt = bytes.fromhex(salt_text)
        digest = bytes.fromhex(digest_text)
    except (ValueError, TypeError):
        return None
    if (
        algorithm != "pbkdf2_sha256"
        or not _MIN_PASSWORD_HASH_ITERATIONS
        <= iterations
        <= _MAX_PASSWORD_HASH_ITERATIONS
        or len(salt) < 16
        or len(digest) != hashlib.sha256().digest_size
    ):
        return None
    return iterations, salt, digest


def _is_production() -> bool:
    return os.environ.get("SMARTBILL_ENV", "development").strip().lower() == "production"


def _auth_configured() -> bool:
    username = os.environ.get("SMARTBILL_OWNER_USERNAME", "").strip()
    password_hash = os.environ.get("SMARTBILL_OWNER_PASSWORD_HASH", "").strip()
    legacy_password = os.environ.get("SMARTBILL_OWNER_PASSWORD", "")
    secret = os.environ.get("SMARTBILL_SESSION_SECRET", "")
    has_password = _parse_password_hash(password_hash) is not None
    if not _is_production() and not password_hash:
        has_password = len(legacy_password) >= 12
    return bool(
        username
        and len(username) <= 80
        and secret
        and len(secret) >= 32
        and has_password
    )


def _signature(payload: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def create_session_token(username: str) -> str:
    expires_at = int(time.time()) + SESSION_SECONDS
    nonce = secrets.token_urlsafe(24)
    payload = f"{username}|{expires_at}|{nonce}"
    signature = _signature(payload, os.environ["SMARTBILL_SESSION_SECRET"])
    encoded = base64.urlsafe_b64encode(f"{payload}|{signature}".encode("utf-8"))
    with _active_sessions_lock:
        now = int(time.time())
        for active_nonce, expiry in list(_active_sessions.items()):
            if expiry <= now:
                del _active_sessions[active_nonce]
        while len(_active_sessions) >= _MAX_ACTIVE_SESSIONS:
            del _active_sessions[next(iter(_active_sessions))]
        _active_sessions[nonce] = expires_at
    return encoded.decode("ascii").rstrip("=")


def _session_details(token: str | None) -> tuple[str, int, str] | None:
    if not token or len(token) > 2048 or not _auth_configured():
        return None
    try:
        padded_token = token + "=" * (-len(token) % 4)
        decoded = base64.urlsafe_b64decode(padded_token).decode("utf-8")
        payload, supplied_signature = decoded.rsplit("|", 1)
        username, expires_text, nonce = payload.rsplit("|", 2)
        expires_at = int(expires_text)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return None

    configured_username = os.environ["SMARTBILL_OWNER_USERNAME"].strip()
    if (
        username != configured_username
        or not nonce
        or expires_at <= int(time.time())
        or expires_at > int(time.time()) + SESSION_SECONDS
    ):
        return None

    expected_signature = _signature(
        payload, os.environ["SMARTBILL_SESSION_SECRET"]
    )
    if not hmac.compare_digest(supplied_signature, expected_signature):
        return None
    with _active_sessions_lock:
        if _active_sessions.get(nonce) != expires_at:
            return None
    return username, expires_at, nonce


def verify_session_token(token: str | None) -> str | None:
    details = _session_details(token)
    return details[0] if details is not None else None


def csrf_token_for_session(token: str | None) -> str | None:
    details = _session_details(token)
    if details is None:
        return None
    _, expires_at, nonce = details
    return _signature(
        f"csrf|{nonce}|{expires_at}", os.environ["SMARTBILL_SESSION_SECRET"]
    )


def verify_csrf_token(session_token: str | None, supplied_token: str | None) -> bool:
    if not supplied_token:
        return False
    expected_token = csrf_token_for_session(session_token)
    return expected_token is not None and hmac.compare_digest(
        supplied_token, expected_token
    )


def revoke_session_token(token: str | None) -> None:
    details = _session_details(token)
    if details is None:
        return
    with _active_sessions_lock:
        _active_sessions.pop(details[2], None)


def require_owner(request: Request) -> str:
    if not _auth_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Owner sign-in is not configured. Set "
                "SMARTBILL_OWNER_USERNAME, SMARTBILL_OWNER_PASSWORD_HASH, and "
                "SMARTBILL_SESSION_SECRET before using the application."
            ),
        )

    session_token = request.cookies.get(SESSION_COOKIE)
    username = verify_session_token(session_token)
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Please sign in to use SmartBill.",
        )
    if request.method not in {"GET", "HEAD", "OPTIONS"} and not verify_csrf_token(
        session_token, request.headers.get(CSRF_HEADER)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The request is missing a valid CSRF token.",
        )
    return username


def owner_login_matches(username: str, password: str) -> bool:
    if not _auth_configured():
        return False
    configured_username = os.environ["SMARTBILL_OWNER_USERNAME"].strip()
    if not hmac.compare_digest(username.strip(), configured_username):
        return False
    password_hash = os.environ.get("SMARTBILL_OWNER_PASSWORD_HASH", "").strip()
    if password_hash:
        parsed = _parse_password_hash(password_hash)
        if parsed is None:
            return False
        iterations, salt, expected_digest = parsed
        supplied_digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations
        )
        return hmac.compare_digest(supplied_digest, expected_digest)
    if not _is_production():
        legacy_password = os.environ.get("SMARTBILL_OWNER_PASSWORD", "")
        return hmac.compare_digest(password, legacy_password)
    return False


def auth_configuration_status() -> bool:
    return _auth_configured()
