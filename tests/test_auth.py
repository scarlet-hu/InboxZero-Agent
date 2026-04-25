"""Tests for the FastAPI auth router and session helpers."""
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from app.main import app
from app.services.auth import (
    SESSION_COOKIE_NAME,
    SessionData,
    sign_session,
    verify_session,
)
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def valid_session() -> SessionData:
    return SessionData(
        email="alice@example.com",
        token="ya29.fake",
        refresh_token="1//refresh",
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )


# ---------------------------------------------------------------------------
# JWT round-trip
# ---------------------------------------------------------------------------

def test_jwt_round_trip(valid_session):
    token = sign_session(valid_session)
    decoded = verify_session(token)
    assert decoded is not None
    assert decoded.email == valid_session.email
    assert decoded.token == valid_session.token
    assert decoded.scopes == valid_session.scopes


def test_verify_session_rejects_garbage():
    assert verify_session("not-a-jwt") is None


# ---------------------------------------------------------------------------
# /auth/login
# ---------------------------------------------------------------------------

def test_login_redirects_to_google_with_pkce(client):
    resp = client.get("/auth/login")
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith("https://accounts.google.com/")

    qs = parse_qs(urlparse(location).query)
    # PKCE was actually sent — this is the bug we couldn't reach in Streamlit.
    assert "code_challenge" in qs
    assert qs.get("code_challenge_method") == ["S256"]
    # State parameter is our HMAC-signed nonce, not Google's.
    assert "state" in qs


# ---------------------------------------------------------------------------
# /auth/me
# ---------------------------------------------------------------------------

def test_me_401_without_cookie(client):
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_me_returns_session_with_valid_cookie(client, valid_session):
    token = sign_session(valid_session)
    resp = client.get("/auth/me", cookies={SESSION_COOKIE_NAME: token})
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "alice@example.com"
    assert "scopes" in body


def test_me_401_with_tampered_cookie(client):
    resp = client.get("/auth/me", cookies={SESSION_COOKIE_NAME: "not.a.jwt"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /auth/logout
# ---------------------------------------------------------------------------

def test_logout_clears_cookie(client, valid_session):
    token = sign_session(valid_session)
    resp = client.post("/auth/logout", cookies={SESSION_COOKIE_NAME: token})
    assert resp.status_code == 204
    # Set-Cookie should overwrite the session with an expired/empty one.
    set_cookie = resp.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in set_cookie


# ---------------------------------------------------------------------------
# /auth/callback (the OAuth bug we're fixing)
# ---------------------------------------------------------------------------

def test_callback_rejects_invalid_state(client):
    resp = client.get("/auth/callback?code=fake&state=bogus")
    assert resp.status_code == 302
    assert "auth_error=invalid_state" in resp.headers["location"]


def test_callback_propagates_oauth_error(client):
    resp = client.get("/auth/callback?error=access_denied")
    assert resp.status_code == 302
    assert "auth_error=access_denied" in resp.headers["location"]


@patch("app.api.auth.email_from_userinfo", return_value="bob@example.com")
@patch("app.api.auth.extract_email_from_id_token", return_value=None)
@patch("app.api.auth.build_google_flow")
@patch("app.api.auth.pop_verifier", return_value="test-verifier")
@patch("app.api.auth.is_valid_oauth_state", return_value=True)
def test_callback_happy_path_sets_session_cookie(
    _is_valid, _pop, build_flow, _extract, _userinfo, client
):
    fake_flow = MagicMock()
    fake_flow.credentials.token = "ya29.fake"
    fake_flow.credentials.refresh_token = "1//refresh"
    fake_flow.credentials.token_uri = "https://oauth2.googleapis.com/token"
    fake_flow.credentials.scopes = ["scope1"]
    fake_flow.oauth2session.token = {"id_token": None}
    build_flow.return_value = fake_flow

    resp = client.get("/auth/callback?code=fakecode&state=fakestate")
    assert resp.status_code == 302
    assert resp.headers["location"].endswith("/dashboard")
    set_cookie = resp.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in set_cookie
    assert "HttpOnly" in set_cookie
