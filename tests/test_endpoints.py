"""FastAPI endpoint tests.

We patch `get_gmail_service`, `get_calendar_service`, `fetch_unread_emails`,
and the agent so the API layer exercises routing / request-model validation /
error handling without touching Google or the LLM.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


VALID_CREDENTIALS = {
    "token": "fake-token",
    "refresh_token": "fake-refresh",
    "token_uri": "https://oauth2.googleapis.com/token",
    "scopes": ["https://www.googleapis.com/auth/gmail.modify"],
}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def valid_request_body():
    return {"credentials": VALID_CREDENTIALS, "max_results": 5}


# ---------------------------------------------------------------------------
# Root + usage (trivial but free coverage)
# ---------------------------------------------------------------------------

def test_root_ok(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Inbox Zero Agent" in resp.json()["message"]


def test_usage_requires_user_header(client):
    resp = client.get("/agent/usage")
    assert resp.status_code == 422  # missing X-User-Id

    resp = client.get("/agent/usage", headers={"X-User-Id": "u-1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "u-1"
    assert body["daily_limit"] == 50


# ---------------------------------------------------------------------------
# /agent/process — happy path + edge cases
# ---------------------------------------------------------------------------

def _fake_agent(category="fyi"):
    """Returns a mock compiled-graph with .invoke echoing a canned result."""
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
    gmail, calendar, fetch, create_agent, client, valid_request_body
):
    gmail.return_value = MagicMock()
    calendar.return_value = MagicMock()
    fetch.return_value = [
        {"email_id": "m1", "sender": "a@x.com", "subject": "s1", "email_content": "b1"},
        {"email_id": "m2", "sender": "b@x.com", "subject": "s2", "email_content": "b2"},
    ]
    create_agent.return_value = _fake_agent("fyi")

    resp = client.post(
        "/agent/process", json=valid_request_body, headers={"X-User-Id": "user-1"}
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
    gmail, calendar, fetch, create_agent, client, valid_request_body
):
    gmail.return_value = MagicMock()
    calendar.return_value = MagicMock()
    fetch.return_value = []

    resp = client.post(
        "/agent/process", json=valid_request_body, headers={"X-User-Id": "user-1"}
    )

    assert resp.status_code == 200
    assert resp.json() == []
    create_agent.assert_not_called()


@patch("app.api.endpoints.get_gmail_service")
def test_process_500s_on_service_failure(gmail, client, valid_request_body):
    gmail.side_effect = RuntimeError("bad creds")

    resp = client.post(
        "/agent/process", json=valid_request_body, headers={"X-User-Id": "user-1"}
    )
    assert resp.status_code == 500
    assert "bad creds" in resp.json()["detail"]


def test_process_rejects_missing_user_header(client, valid_request_body):
    resp = client.post("/agent/process", json=valid_request_body)
    assert resp.status_code == 422


def test_process_rejects_malformed_credentials(client):
    resp = client.post(
        "/agent/process",
        json={"credentials": {"token": "only-token"}, "max_results": 5},
        headers={"X-User-Id": "user-1"},
    )
    # missing required `scopes`
    assert resp.status_code == 422
