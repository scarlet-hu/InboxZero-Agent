"""OAuth + session management for the FastAPI backend.

This module owns the entire Google OAuth dance:
- starts the flow (PKCE-protected, HMAC-signed state)
- exchanges the authorization code for tokens on callback
- mints a signed JWT session cookie carrying the Google credentials

The PKCE `code_verifier` is held in a process-level dict keyed by the OAuth
`state` nonce — it must outlive the external redirect to Google, which would
kill any per-connection session storage.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

import jwt
from fastapi import Cookie, HTTPException, status
from google_auth_oauthlib.flow import Flow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

SESSION_COOKIE_NAME = "session"
SESSION_TTL_SECONDS = 24 * 3600
STATE_TTL_SECONDS = 600
VERIFIER_TTL_SECONDS = 600

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_DEFAULT_CREDENTIALS_FILE = _BACKEND_DIR / "credentials.json"


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _credentials_file() -> str:
    return os.getenv("GOOGLE_CREDENTIALS_FILE", str(_DEFAULT_CREDENTIALS_FILE))


def _session_secret() -> str:
    """Secret for HMAC-signing OAuth state and JWT sessions.

    Falls back to GOOGLE_CLIENT_SECRET so existing deployments work without
    new env vars; production should set SESSION_SECRET explicitly.
    """
    return (
        os.getenv("SESSION_SECRET")
        or os.getenv("GOOGLE_CLIENT_SECRET")
        or "dev-only-session-secret"
    )


def backend_redirect_uri() -> str:
    """The URI Google redirects to after consent — our /auth/callback."""
    explicit = os.getenv("BACKEND_OAUTH_REDIRECT_URI")
    if explicit:
        return explicit
    base = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
    return f"{base}/auth/callback"


def frontend_url() -> str:
    return os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")


# ---------------------------------------------------------------------------
# OAuth state (HMAC-signed nonce + timestamp)
# ---------------------------------------------------------------------------

def generate_oauth_state() -> str:
    nonce = secrets.token_urlsafe(16)
    timestamp = str(int(time.time()))
    payload = f"{nonce}:{timestamp}"
    signature = hmac.new(
        _session_secret().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}:{signature}"


def is_valid_oauth_state(state: str | None, max_age_seconds: int = STATE_TTL_SECONDS) -> bool:
    if not state:
        return False
    parts = state.split(":")
    if len(parts) != 3:
        return False
    nonce, timestamp, provided_signature = parts
    if not nonce or not timestamp:
        return False
    try:
        issued_at = int(timestamp)
    except ValueError:
        return False
    if time.time() - issued_at > max_age_seconds:
        return False
    payload = f"{nonce}:{timestamp}"
    expected_signature = hmac.new(
        _session_secret().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(provided_signature, expected_signature)


# ---------------------------------------------------------------------------
# PKCE verifier store (process-level, TTL'd)
# ---------------------------------------------------------------------------

_PENDING_VERIFIERS: dict[str, tuple[str, float]] = {}


def generate_pkce_verifier() -> str:
    # RFC 7636: 43-128 chars from [A-Z][a-z][0-9]-._~
    return secrets.token_urlsafe(64)[:96]


def store_verifier(state: str, verifier: str) -> None:
    now = time.time()
    expired = [
        k for k, (_, ts) in _PENDING_VERIFIERS.items()
        if now - ts > VERIFIER_TTL_SECONDS
    ]
    for k in expired:
        _PENDING_VERIFIERS.pop(k, None)
    _PENDING_VERIFIERS[state] = (verifier, now)


def pop_verifier(state: str) -> str | None:
    entry = _PENDING_VERIFIERS.pop(state, None)
    if not entry:
        return None
    verifier, ts = entry
    if time.time() - ts > VERIFIER_TTL_SECONDS:
        return None
    return verifier


# ---------------------------------------------------------------------------
# Google Flow factory
# ---------------------------------------------------------------------------

def build_google_flow(state: str | None = None) -> Flow:
    creds_file = _credentials_file()
    if not os.path.exists(creds_file):
        raise FileNotFoundError(
            f"OAuth client config missing at {creds_file}. "
            "Set GOOGLE_CREDENTIALS_FILE or place credentials.json in backend/."
        )
    flow = Flow.from_client_secrets_file(creds_file, scopes=SCOPES, state=state)
    flow.redirect_uri = backend_redirect_uri()
    return flow


# ---------------------------------------------------------------------------
# Session JWT
# ---------------------------------------------------------------------------

@dataclass
class SessionData:
    email: str
    token: str
    refresh_token: str | None
    token_uri: str
    scopes: list[str]


def sign_session(session: SessionData) -> str:
    payload = {
        "email": session.email,
        "token": session.token,
        "refresh_token": session.refresh_token,
        "token_uri": session.token_uri,
        "scopes": session.scopes,
        "exp": int(time.time()) + SESSION_TTL_SECONDS,
    }
    return jwt.encode(payload, _session_secret(), algorithm="HS256")


def verify_session(token: str) -> SessionData | None:
    try:
        payload = jwt.decode(token, _session_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return SessionData(
        email=payload["email"],
        token=payload["token"],
        refresh_token=payload.get("refresh_token"),
        token_uri=payload["token_uri"],
        scopes=payload.get("scopes", []),
    )


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def get_current_session_optional(
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> SessionData | None:
    """Return the decoded session if a valid cookie is present, else None.

    Used by endpoints that should accept either the new cookie auth or the
    legacy in-body credentials (Streamlit transition path).
    """
    if not session:
        return None
    return verify_session(session)


def get_current_session(
    raw_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> SessionData:
    """Strict variant — 401s if no/invalid session cookie."""
    session = verify_session(raw_cookie) if raw_cookie else None
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return session


# ---------------------------------------------------------------------------
# ID-token / userinfo helpers
# ---------------------------------------------------------------------------

def extract_email_from_id_token(id_token: str | None) -> str | None:
    """Decode the Google ID token (without verification) to read the email.

    Google has already validated the token via the TLS-protected exchange;
    we only need the unsigned payload.
    """
    if not id_token:
        return None
    try:
        decoded = jwt.decode(id_token, options={"verify_signature": False})
    except jwt.PyJWTError:
        return None
    email = decoded.get("email")
    return email if isinstance(email, str) else None


def email_from_userinfo(access_token: str) -> str | None:
    """Fallback when the ID token is missing or unparseable."""
    import requests

    try:
        resp = requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except json.JSONDecodeError:
        return None
    email = data.get("email")
    return email if isinstance(email, str) else None
