"""Tests for the FastAPI auth router and session helpers."""
import time
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from app.main import app
from app.services import auth as auth_service
from app.services.auth import (
    SESSION_COOKIE_NAME,
    SessionData,
    email_from_userinfo,
    extract_email_from_id_token,
    generate_oauth_state,
    is_valid_oauth_state,
    pop_verifier,
    sign_session,
    store_verifier,
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

@patch("app.api.auth.build_google_flow")
def test_login_redirects_to_google_with_pkce(build_flow, client):
    # Stub the Flow so the test doesn't need backend/credentials.json on disk
    # (CI runners don't have it, and committing OAuth secrets is a no-go).
    fake_flow = MagicMock()
    fake_flow.authorization_url.return_value = (
        "https://accounts.google.com/o/oauth2/auth"
        "?code_challenge=abc&code_challenge_method=S256&state=signed-state",
        "signed-state",
    )
    build_flow.return_value = fake_flow

    resp = client.get("/auth/login")
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith("https://accounts.google.com/")

    qs = parse_qs(urlparse(location).query)
    assert "code_challenge" in qs
    assert qs.get("code_challenge_method") == ["S256"]
    assert "state" in qs
    assert fake_flow.code_verifier  # endpoint set a verifier before redirecting


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


# ---------------------------------------------------------------------------
# OAuth state HMAC helpers
# ---------------------------------------------------------------------------

class TestOAuthState:
    def test_generated_state_validates(self):
        state = generate_oauth_state()
        assert is_valid_oauth_state(state)

    def test_none_or_empty_rejected(self):
        assert not is_valid_oauth_state(None)
        assert not is_valid_oauth_state("")

    def test_wrong_segment_count_rejected(self):
        assert not is_valid_oauth_state("only-two:parts")
        assert not is_valid_oauth_state("a:b:c:d")

    def test_non_integer_timestamp_rejected(self):
        assert not is_valid_oauth_state("nonce:notanumber:sig")

    def test_expired_state_rejected(self):
        state = generate_oauth_state()
        # max_age=0 forces the freshness check to fail without sleeping.
        assert not is_valid_oauth_state(state, max_age_seconds=0)

    def test_tampered_signature_rejected(self):
        state = generate_oauth_state()
        nonce, ts, _sig = state.split(":")
        assert not is_valid_oauth_state(f"{nonce}:{ts}:deadbeef")

    def test_empty_nonce_or_timestamp_rejected(self):
        assert not is_valid_oauth_state(":123:sig")
        assert not is_valid_oauth_state("nonce::sig")


# ---------------------------------------------------------------------------
# PKCE verifier store
# ---------------------------------------------------------------------------

class TestVerifierStore:
    def test_round_trip(self):
        store_verifier("state-1", "verifier-abc")
        assert pop_verifier("state-1") == "verifier-abc"
        # popped — no longer present
        assert pop_verifier("state-1") is None

    def test_pop_unknown_state_returns_none(self):
        assert pop_verifier("never-stored") is None

    def test_expired_verifier_is_dropped(self, monkeypatch):
        store_verifier("state-2", "verifier-xyz")
        # Force the entry to look ancient.
        verifier, _ts = auth_service._PENDING_VERIFIERS["state-2"]
        auth_service._PENDING_VERIFIERS["state-2"] = (verifier, time.time() - 10_000)
        assert pop_verifier("state-2") is None


# ---------------------------------------------------------------------------
# ID-token / userinfo email extraction
# ---------------------------------------------------------------------------

class TestEmailExtraction:
    def test_extract_returns_none_for_missing_token(self):
        assert extract_email_from_id_token(None) is None
        assert extract_email_from_id_token("") is None

    def test_extract_returns_none_for_garbage(self):
        assert extract_email_from_id_token("not.a.jwt") is None

    def test_extract_returns_email_from_unsigned_jwt(self):
        import jwt as pyjwt
        token = pyjwt.encode({"email": "carol@example.com"}, "irrelevant", algorithm="HS256")
        assert extract_email_from_id_token(token) == "carol@example.com"

    @patch("requests.get")
    def test_userinfo_returns_email_on_200(self, get):
        get.return_value = MagicMock(status_code=200, json=lambda: {"email": "dan@example.com"})
        assert email_from_userinfo("access-tok") == "dan@example.com"

    @patch("requests.get")
    def test_userinfo_returns_none_on_non_200(self, get):
        get.return_value = MagicMock(status_code=403, json=lambda: {})
        assert email_from_userinfo("access-tok") is None

    @patch("requests.get")
    def test_userinfo_handles_request_exception(self, get):
        get.side_effect = requests.RequestException("boom")
        assert email_from_userinfo("access-tok") is None


# ---------------------------------------------------------------------------
# build_google_flow error path
# ---------------------------------------------------------------------------

def test_build_google_flow_raises_when_credentials_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_CREDENTIALS_FILE", str(tmp_path / "missing.json"))
    with pytest.raises(FileNotFoundError):
        auth_service.build_google_flow()
