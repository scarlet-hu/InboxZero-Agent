"""Unit tests for agent_core.

The LLM is stubbed so these tests are deterministic and offline. Google API
services are MagicMock objects — we only verify our code's handling, not the
Google SDK.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.services import agent_core
from app.services.agent_core import (
    calendar_check_logic,
    categorize_logic,
    create_inbox_agent,
    draft_reply_logic,
)


def _fake_llm_response(payload: str):
    """Return an object shaped like a LangChain AIMessage (.content str)."""
    return SimpleNamespace(content=payload)


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace the module-level `llm` with a MagicMock.

    We can't use `patch.object(agent_core.llm, "invoke", ...)` because
    ChatGoogleGenerativeAI is a frozen pydantic model and mock's teardown
    trips its __delattr__. Swapping the whole attribute is cleaner.
    """
    mock = MagicMock()
    monkeypatch.setattr(agent_core, "llm", mock)
    return mock


def _base_state(**overrides):
    state = {
        "email_id": "msg-1",
        "sender": "alice@example.com",
        "subject": "Test subject",
        "email_content": "Test body",
        "category": "fyi",
        "summary": "",
        "calendar_status": None,
        "draft_id": None,
    }
    state.update(overrides)
    return state


# ---------------------------------------------------------------------------
# categorize_logic
# ---------------------------------------------------------------------------

class TestCategorizeLogic:
    def test_parses_plain_json(self, fake_llm):
        fake_llm.invoke.return_value = _fake_llm_response(
            '{"category": "action", "summary": "needs reply"}'
        )
        result = categorize_logic(_base_state())
        assert result == {"category": "action", "summary": "needs reply"}

    def test_strips_markdown_code_fence(self, fake_llm):
        fake_llm.invoke.return_value = _fake_llm_response(
            '```json\n{"category": "spam", "summary": "phishing"}\n```'
        )
        result = categorize_logic(_base_state())
        assert result["category"] == "spam"
        assert result["summary"] == "phishing"

    def test_missing_fields_fall_back_to_defaults(self, fake_llm):
        fake_llm.invoke.return_value = _fake_llm_response("{}")
        result = categorize_logic(_base_state())
        assert result["category"] == "fyi"
        assert result["summary"] == "No summary"

    def test_llm_exception_produces_error_parsing_summary(self, fake_llm):
        """Pins the bare-except fallback in production — narrowing the except
        clause in future should fail this test rather than silently change
        behavior."""
        fake_llm.invoke.side_effect = RuntimeError("boom")
        result = categorize_logic(_base_state())
        assert result["category"] == "fyi"
        assert result["summary"].startswith("Error parsing:")
        assert "boom" in result["summary"]

    def test_invalid_json_is_caught(self, fake_llm):
        fake_llm.invoke.return_value = _fake_llm_response("not json at all")
        result = categorize_logic(_base_state())
        assert result["category"] == "fyi"
        assert result["summary"].startswith("Error parsing:")


# ---------------------------------------------------------------------------
# calendar_check_logic
# ---------------------------------------------------------------------------

class TestCalendarCheckLogic:
    def test_no_time_mentioned_short_circuits(self, fake_llm):
        calendar_service = MagicMock()
        fake_llm.invoke.return_value = _fake_llm_response(
            '{"start": null, "end": null}'
        )
        result = calendar_check_logic(_base_state(), calendar_service=calendar_service)
        assert result == {"calendar_status": "No specific time mentioned."}
        calendar_service.events.assert_not_called()

    def test_returns_free_when_no_conflicts(self, fake_llm):
        calendar_service = MagicMock()
        calendar_service.events.return_value.list.return_value.execute.return_value = {
            "items": []
        }
        fake_llm.invoke.return_value = _fake_llm_response(
            '{"start": "2026-05-01T10:00:00Z", "end": "2026-05-01T11:00:00Z"}'
        )
        result = calendar_check_logic(_base_state(), calendar_service=calendar_service)
        assert "✅ Free" in result["calendar_status"]

    def test_returns_conflict_when_event_exists(self, fake_llm):
        calendar_service = MagicMock()
        calendar_service.events.return_value.list.return_value.execute.return_value = {
            "items": [{"summary": "Existing 1:1"}]
        }
        fake_llm.invoke.return_value = _fake_llm_response(
            '{"start": "2026-05-01T10:00:00Z", "end": "2026-05-01T11:00:00Z"}'
        )
        result = calendar_check_logic(_base_state(), calendar_service=calendar_service)
        assert "Conflict" in result["calendar_status"]
        assert "Existing 1:1" in result["calendar_status"]

    def test_unparseable_date_returns_parse_error(self, fake_llm):
        calendar_service = MagicMock()
        fake_llm.invoke.return_value = _fake_llm_response("totally broken")
        result = calendar_check_logic(_base_state(), calendar_service=calendar_service)
        assert result == {"calendar_status": "Could not parse date."}

    def test_calendar_api_error_is_surfaced(self, fake_llm):
        calendar_service = MagicMock()
        calendar_service.events.return_value.list.return_value.execute.side_effect = (
            RuntimeError("quota")
        )
        fake_llm.invoke.return_value = _fake_llm_response(
            '{"start": "2026-05-01T10:00:00Z", "end": "2026-05-01T11:00:00Z"}'
        )
        result = calendar_check_logic(_base_state(), calendar_service=calendar_service)
        assert "Calendar API error" in result["calendar_status"]
        assert "quota" in result["calendar_status"]


# ---------------------------------------------------------------------------
# draft_reply_logic
# ---------------------------------------------------------------------------

def _gmail_service_with_no_existing_drafts(thread_id="thread-1"):
    gmail = MagicMock()
    gmail.users.return_value.messages.return_value.get.return_value.execute.return_value = {
        "threadId": thread_id,
        "payload": {"headers": [{"name": "Message-ID", "value": "<orig@example.com>"}]},
    }
    gmail.users.return_value.drafts.return_value.list.return_value.execute.return_value = {
        "drafts": []
    }
    gmail.users.return_value.drafts.return_value.create.return_value.execute.return_value = {
        "id": "draft-123"
    }
    return gmail


class TestDraftReplyLogic:
    def test_creates_new_draft_when_none_exists(self, fake_llm):
        gmail = _gmail_service_with_no_existing_drafts()
        fake_llm.invoke.return_value = _fake_llm_response(
            '{"subject": "Re: Test", "body": "Sounds good."}'
        )
        result = draft_reply_logic(_base_state(), gmail_service=gmail)
        assert result == {"draft_id": "draft-123"}
        gmail.users.return_value.drafts.return_value.create.assert_called_once()

    def test_reuses_existing_draft_for_thread(self, fake_llm):
        gmail = MagicMock()
        gmail.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "threadId": "thread-42",
            "payload": {"headers": []},
        }
        gmail.users.return_value.drafts.return_value.list.return_value.execute.return_value = {
            "drafts": [{"id": "existing-draft", "message": {"threadId": "thread-42"}}]
        }
        result = draft_reply_logic(_base_state(), gmail_service=gmail)
        assert result == {"draft_id": "existing-draft"}
        gmail.users.return_value.drafts.return_value.create.assert_not_called()

    def test_falls_back_to_canned_body_when_llm_returns_bad_json(self, fake_llm):
        gmail = _gmail_service_with_no_existing_drafts()
        fake_llm.invoke.return_value = _fake_llm_response("not-json")
        result = draft_reply_logic(_base_state(), gmail_service=gmail)
        assert result == {"draft_id": "draft-123"}
        gmail.users.return_value.drafts.return_value.create.assert_called_once()

    def test_draft_create_failure_returns_none(self, fake_llm):
        gmail = _gmail_service_with_no_existing_drafts()
        gmail.users.return_value.drafts.return_value.create.return_value.execute.side_effect = (
            RuntimeError("gmail down")
        )
        fake_llm.invoke.return_value = _fake_llm_response(
            '{"subject": "Re: Test", "body": "ok"}'
        )
        result = draft_reply_logic(_base_state(), gmail_service=gmail)
        assert result == {"draft_id": None}


# ---------------------------------------------------------------------------
# Graph wiring — routing after categorize
# ---------------------------------------------------------------------------

class TestAgentGraphRouting:
    def test_fyi_skips_calendar_and_draft(self, fake_llm):
        gmail, calendar = MagicMock(), MagicMock()
        graph = create_inbox_agent(gmail, calendar)
        fake_llm.invoke.return_value = _fake_llm_response(
            '{"category": "fyi", "summary": "newsletter"}'
        )
        result = graph.invoke(_base_state())
        assert result["category"] == "fyi"
        assert result.get("draft_id") is None
        calendar.events.assert_not_called()

    def test_spam_skips_calendar_and_draft(self, fake_llm):
        gmail, calendar = MagicMock(), MagicMock()
        graph = create_inbox_agent(gmail, calendar)
        fake_llm.invoke.return_value = _fake_llm_response(
            '{"category": "spam", "summary": "phishing"}'
        )
        result = graph.invoke(_base_state())
        assert result["category"] == "spam"
        assert result.get("draft_id") is None
        calendar.events.assert_not_called()

    def test_action_runs_calendar_then_draft(self, fake_llm):
        gmail = _gmail_service_with_no_existing_drafts()
        calendar = MagicMock()
        calendar.events.return_value.list.return_value.execute.return_value = {"items": []}

        responses = iter(
            [
                _fake_llm_response('{"category": "action", "summary": "please confirm"}'),
                _fake_llm_response('{"start": null, "end": null}'),
                _fake_llm_response('{"subject": "Re: Test", "body": "Confirmed."}'),
            ]
        )
        fake_llm.invoke.side_effect = lambda *_a, **_kw: next(responses)

        graph = create_inbox_agent(gmail, calendar)
        result = graph.invoke(_base_state())

        assert result["category"] == "action"
        assert result["draft_id"] == "draft-123"
        assert result["calendar_status"] == "No specific time mentioned."
