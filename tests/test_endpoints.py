"""FastAPI endpoint tests.

We patch `get_gmail_service`, `get_calendar_service`, `fetch_unread_emails`,
and the agent so the API layer exercises routing / auth / error handling
without touching Google or the LLM. Auth is exercised end-to-end by minting
a real session JWT and sending it as a cookie.
"""
from unittest.mock import MagicMock, patch

import pytest
from app.main import app
from app.services.auth import SESSION_COOKIE_NAME, SessionData, sign_session
from fastapi.testclient import TestClient
from googleapiclient.errors import HttpError


def _gmail_http_error(status: int) -> HttpError:
    resp = MagicMock()
    resp.status = status
    resp.reason = "Mocked"
    return HttpError(resp, b"{}")


def _session_cookie() -> dict[str, str]:
    token = sign_session(SessionData(
        email="user@example.com",
        token="fake-token",
        refresh_token="fake-refresh",
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/gmail.modify"],
    ))
    return {SESSION_COOKIE_NAME: token}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_cookies():
    return _session_cookie()


# ---------------------------------------------------------------------------
# Root + usage
# ---------------------------------------------------------------------------

def test_root_ok(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Inbox Zero Agent" in resp.json()["message"]


def test_usage_requires_auth(client):
    resp = client.get("/agent/usage")
    assert resp.status_code == 401


def test_usage_returns_user_with_valid_cookie(client, auth_cookies):
    resp = client.get("/agent/usage", cookies=auth_cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "user@example.com"
    assert body["daily_limit"] == 50


# ---------------------------------------------------------------------------
# /agent/process
# ---------------------------------------------------------------------------

def _fake_agent(category="fyi"):
    agent = MagicMock()
    agent.invoke.return_value = {
        "email_id": "m1",
        "sender": "alice@example.com",
        "subject": "Hi",
        "email_content": "body",
        "category": category,
        "summary": "a summary",
        "draft_id": "draft-1" if category == "action" else None,
        "calendar_status": "✅ Free" if category == "action" else None,
    }
    return agent


@patch("app.api.endpoints.create_inbox_agent")
@patch("app.api.endpoints.fetch_unread_emails")
@patch("app.api.endpoints.get_calendar_service")
@patch("app.api.endpoints.get_gmail_service")
def test_process_returns_results_for_each_email(
    gmail, calendar, fetch, create_agent, client, auth_cookies
):
    gmail.return_value = MagicMock()
    calendar.return_value = MagicMock()
    fetch.return_value = [
        {"email_id": "m1", "sender": "a@x.com", "subject": "s1", "email_content": "b1"},
        {"email_id": "m2", "sender": "b@x.com", "subject": "s2", "email_content": "b2"},
    ]
    create_agent.return_value = _fake_agent("fyi")

    resp = client.post(
        "/agent/process",
        json={"max_results": 5},
        cookies=auth_cookies,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert all(item["category"] == "fyi" for item in body)
    assert create_agent.return_value.invoke.call_count == 2


@patch("app.api.endpoints.create_inbox_agent")
@patch("app.api.endpoints.fetch_unread_emails")
@patch("app.api.endpoints.get_calendar_service")
@patch("app.api.endpoints.get_gmail_service")
def test_process_returns_empty_list_when_no_unread(
    gmail, calendar, fetch, create_agent, client, auth_cookies
):
    gmail.return_value = MagicMock()
    calendar.return_value = MagicMock()
    fetch.return_value = []

    resp = client.post(
        "/agent/process",
        json={"max_results": 5},
        cookies=auth_cookies,
    )

    assert resp.status_code == 200
    assert resp.json() == []
    create_agent.assert_not_called()


@patch("app.api.endpoints.get_gmail_service")
def test_process_500s_on_service_failure(gmail, client, auth_cookies):
    gmail.side_effect = RuntimeError("bad creds")

    resp = client.post(
        "/agent/process",
        json={"max_results": 5},
        cookies=auth_cookies,
    )
    assert resp.status_code == 500
    assert "bad creds" in resp.json()["detail"]


def test_process_rejects_request_without_session(client):
    resp = client.post("/agent/process", json={"max_results": 5})
    assert resp.status_code == 401


def test_process_rejects_tampered_cookie(client):
    resp = client.post(
        "/agent/process",
        json={"max_results": 5},
        cookies={SESSION_COOKIE_NAME: "not.a.jwt"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /agent/drafts/* — review-approve HITL surface
# ---------------------------------------------------------------------------

_DRAFT_PAYLOAD = {
    "draft_id": "draft-1",
    "to": "alice@example.com",
    "subject": "Re: Lunch?",
    "body": "Sounds good — see you at noon.",
}


def test_get_draft_requires_auth(client):
    resp = client.get("/agent/drafts/draft-1")
    assert resp.status_code == 401


@patch("app.api.endpoints.read_draft_content", return_value=_DRAFT_PAYLOAD)
@patch("app.api.endpoints.get_gmail_service")
def test_get_draft_returns_content(gmail, read, client, auth_cookies):
    gmail.return_value = MagicMock()
    resp = client.get("/agent/drafts/draft-1", cookies=auth_cookies)
    assert resp.status_code == 200
    assert resp.json() == _DRAFT_PAYLOAD
    read.assert_called_once()


@patch("app.api.endpoints.read_draft_content", side_effect=_gmail_http_error(404))
@patch("app.api.endpoints.get_gmail_service")
def test_get_draft_404_when_gmail_404s(gmail, read, client, auth_cookies):
    gmail.return_value = MagicMock()
    resp = client.get("/agent/drafts/missing", cookies=auth_cookies)
    assert resp.status_code == 404


@patch("app.api.endpoints.read_draft_content")
@patch("app.api.endpoints.update_draft_content")
@patch("app.api.endpoints.get_gmail_service")
def test_update_draft_saves_and_returns_fresh_content(
    gmail, update, read, client, auth_cookies
):
    gmail.return_value = MagicMock()
    updated = {**_DRAFT_PAYLOAD, "subject": "Edited", "body": "Edited body"}
    read.return_value = updated

    resp = client.put(
        "/agent/drafts/draft-1",
        json={"subject": "Edited", "body": "Edited body"},
        cookies=auth_cookies,
    )

    assert resp.status_code == 200
    assert resp.json() == updated
    update.assert_called_once()
    args = update.call_args.args
    assert args[1] == "draft-1"
    assert args[2] == "Edited"
    assert args[3] == "Edited body"


@patch("app.api.endpoints.send_draft")
@patch("app.api.endpoints.get_gmail_service")
def test_send_draft_returns_204(gmail, send, client, auth_cookies):
    gmail.return_value = MagicMock()
    resp = client.post("/agent/drafts/draft-1/send", cookies=auth_cookies)
    assert resp.status_code == 204
    send.assert_called_once()


@patch("app.api.endpoints.send_draft", side_effect=_gmail_http_error(404))
@patch("app.api.endpoints.get_gmail_service")
def test_send_draft_404_when_gmail_404s(gmail, send, client, auth_cookies):
    gmail.return_value = MagicMock()
    resp = client.post("/agent/drafts/missing/send", cookies=auth_cookies)
    assert resp.status_code == 404


@patch("app.api.endpoints.discard_draft")
@patch("app.api.endpoints.get_gmail_service")
def test_discard_draft_returns_204(gmail, discard, client, auth_cookies):
    gmail.return_value = MagicMock()
    resp = client.delete("/agent/drafts/draft-1", cookies=auth_cookies)
    assert resp.status_code == 204
    discard.assert_called_once()


def test_get_draft_in_demo_mode_returns_fixture(client):
    """Demo session: no Gmail call, returns a synthesized fixture draft."""
    demo_token = sign_session(SessionData(
        email="demo@inboxzero.dev",
        token="demo",
        refresh_token=None,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["demo"],
        is_demo=True,
    ))
    resp = client.get(
        "/agent/drafts/demo-draft-001",
        cookies={SESSION_COOKIE_NAME: demo_token},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["draft_id"] == "demo-draft-001"
    assert body["subject"].startswith("Re:")
    assert body["body"]  # non-empty


def test_get_draft_in_demo_mode_404_for_unknown_id(client):
    demo_token = sign_session(SessionData(
        email="demo@inboxzero.dev",
        token="demo",
        refresh_token=None,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["demo"],
        is_demo=True,
    ))
    resp = client.get(
        "/agent/drafts/nonexistent",
        cookies={SESSION_COOKIE_NAME: demo_token},
    )
    assert resp.status_code == 404
