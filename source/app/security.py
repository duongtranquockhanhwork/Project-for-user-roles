"""Password hashing, server-side sessions, CSRF protection and HTTP headers."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from . import db

# Argon2id with the RFC 9106 "second recommended" parameters:
# memory 64 MiB, 3 iterations, 4 lanes, 16-byte salt, 32-byte hash.
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4,
                         hash_len=32, salt_len=16)

# Used when the username does not exist, so that a failed login takes the same
# time whether or not the account exists (prevents username enumeration).
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password):
    return _hasher.hash(password)


def verify_password(password_hash, password):
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def burn_verification_time(password):
    verify_password(_DUMMY_HASH, password)


def needs_rehash(password_hash):
    return _hasher.check_needs_rehash(password_hash)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(user_id, config):
    """Create a new random session and return the token for the cookie.

    A fresh token is issued at every login (prevents session fixation). The
    database stores only the SHA-256 hash of the token.
    """
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=config.SESSION_ABSOLUTE_HOURS)
    db.execute(
        "INSERT INTO sessions (token_hash, user_id, csrf_token, expires_at) "
        "VALUES (%s, %s, %s, %s)",
        (_token_hash(token), user_id, csrf_token, expires))
    return token


def load_session(token, config):
    """Return the session joined with its user, or None if not valid."""
    if not token or len(token) > 128:
        return None
    row = db.query_one(
        "SELECT s.token_hash, s.user_id, s.csrf_token, s.last_seen_at, "
        "       u.username, u.full_name, u.is_active "
        "  FROM sessions s JOIN users u ON u.id = s.user_id "
        " WHERE s.token_hash = %s AND s.revoked_at IS NULL "
        "   AND s.expires_at > now() "
        "   AND s.last_seen_at > now() - make_interval(mins => %s)",
        (_token_hash(token), config.SESSION_IDLE_MINUTES))
    if row is None:
        return None
    if not row["is_active"]:
        revoke_all_sessions(row["user_id"])
        db.commit()
        return None
    db.execute("UPDATE sessions SET last_seen_at = now() WHERE token_hash = %s",
               (row["token_hash"],))
    db.commit()
    return row


def revoke_session(token):
    if token:
        db.execute("UPDATE sessions SET revoked_at = now() "
                   "WHERE token_hash = %s AND revoked_at IS NULL", (_token_hash(token),))


def revoke_all_sessions(user_id):
    db.execute("UPDATE sessions SET revoked_at = now() "
               "WHERE user_id = %s AND revoked_at IS NULL", (user_id,))


def set_session_cookie(response, token, config):
    response.set_cookie(config.SESSION_COOKIE, token, httponly=True,
                        secure=config.COOKIE_SECURE, samesite="Strict", path="/")


def clear_session_cookie(response, config):
    response.delete_cookie(config.SESSION_COOKIE, path="/", httponly=True,
                           secure=config.COOKIE_SECURE, samesite="Strict")


# ---------------------------------------------------------------------------
# CSRF (synchronizer token bound to the server-side session)
# ---------------------------------------------------------------------------

def csrf_valid(expected, supplied):
    if not expected or not supplied:
        return False
    return hmac.compare_digest(expected, supplied)


# ---------------------------------------------------------------------------
# HTTP security headers
# ---------------------------------------------------------------------------

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")


def apply_security_headers(response):
    response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cache-Control"] = "no-store"
    return response
