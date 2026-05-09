"""ReAct alternative to agent_core.py.

The production path uses agent_core.py (deterministic LangGraph state machine).
This module is a ReAct prototype: tools are LangChain `@tool`-decorated and the
LLM decides whether and when to call them.

See `docs/react-vs-state-machine.md` for measured token-cost data behind the
decision to keep the state machine in production (single action email: ReAct
+65% total tokens, +194% input tokens vs the state machine).
"""
import base64
import json
from datetime import datetime
from email.message import EmailMessage
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent

llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)


SYSTEM_PROMPT_TEMPLATE = """\
You are an AI Executive Assistant processing a single email.

Today is {today}.

For each email do the following, in order:

1. Classify into EXACTLY ONE category:
   - **spam**: phishing, scams, cold sales, suspicious senders, unsolicited promos.
   - **action**: a real human wants a written email reply (questions, meeting
     requests, RSVPs, tasks assigned to you).
   - **fyi**: legitimate informational emails that do NOT need a reply
     (receipts, newsletters, automated alerts from real services).
   spam OVERRIDES the "automated → fyi" rule.

2. If the email proposes/mentions a specific meeting time AND category=action,
   call `check_calendar_conflicts(start_iso, end_iso)` with ISO 8601 timestamps.
   Skip this tool for spam, fyi, or emails with no concrete time.

3. If category=action, call `create_draft_reply(reply_subject, reply_body)` to
   put a draft in Gmail Drafts. The recipient and threading are filled
   automatically — you only supply the subject line and body.
   Do NOT call this tool for spam or fyi.

4. After any tool calls (or immediately for spam/fyi), respond with ONLY a
   single JSON object on the last line, no markdown fences:
   {{"category": "action|fyi|spam", "summary": "<one-sentence summary>"}}
"""


# ---------------------------------------------------------------------------
# Tool factory — closes over per-user services + current email context
# ---------------------------------------------------------------------------

def _make_tools(
    gmail_service: Any,
    calendar_service: Any,
    email_id: str,
    sender: str,
):
    """Returns a list of @tool functions bound to this user / email."""

    @tool
    def check_calendar_conflicts(start_iso: str, end_iso: str) -> str:
        """Check the user's primary Google Calendar for events in the time window
        [start_iso, end_iso]. Both arguments must be ISO 8601 with timezone
        offset (e.g. 2026-05-10T14:00:00-07:00). Returns a short status string
        like 'Free at <time>.' or 'Conflict: <event title>.'."""
        try:
            events_result = calendar_service.events().list(
                calendarId="primary",
                timeMin=start_iso,
                timeMax=end_iso,
                singleEvents=True,
                orderBy="startTime",
            ).execute()
            events = events_result.get("items", [])
            if not events:
                return f"Free at {start_iso}."
            return f"Conflict: {events[0].get('summary', '(untitled)')}."
        except Exception as e:
            return f"Calendar API error: {e}"

    @tool
    def create_draft_reply(reply_subject: str, reply_body: str) -> str:
        """Create a Gmail draft reply (NOT sent) in the same thread as the
        current email. The recipient address and threading headers (In-Reply-To,
        References) are filled automatically — supply only the subject and body
        text. Returns 'draft_id=<id>' on success or an error string."""
        try:
            email_details = (
                gmail_service.users()
                .messages()
                .get(userId="me", id=email_id)
                .execute()
            )
            thread_id = email_details.get("threadId")

            # Dedup: reuse existing draft on same thread
            drafts = (
                gmail_service.users()
                .drafts()
                .list(userId="me")
                .execute()
                .get("drafts", [])
            )
            for d in drafts:
                if d.get("message", {}).get("threadId") == thread_id:
                    return f"draft_id={d['id']} (reused existing)"

            message = EmailMessage()
            message.set_content(reply_body)
            message["To"] = sender
            message["Subject"] = reply_subject

            headers = email_details.get("payload", {}).get("headers", [])
            msg_id = next(
                (h["value"] for h in headers if h["name"].lower() == "message-id"),
                None,
            )
            if msg_id:
                message["In-Reply-To"] = msg_id
                message["References"] = msg_id

            encoded = base64.urlsafe_b64encode(message.as_bytes()).decode()
            draft = (
                gmail_service.users()
                .drafts()
                .create(
                    userId="me",
                    body={"message": {"raw": encoded, "threadId": thread_id}},
                )
                .execute()
            )
            return f"draft_id={draft['id']}"
        except Exception as e:
            return f"Draft creation error: {e}"

    return [check_calendar_conflicts, create_draft_reply]


# ---------------------------------------------------------------------------
# Output reconstruction
# ---------------------------------------------------------------------------

def _content_to_text(content: Any) -> str:
    """Normalize a message's `.content` to a plain string.

    Newer LangChain message types may carry content as a list of content
    blocks (e.g. [{"type": "text", "text": "..."}]). Flatten to text.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(block.get("text") or block.get("content") or "")
        return "".join(parts)
    return str(content) if content is not None else ""


def _extract_structured_output(messages: list, fallback_category: str = "fyi") -> dict:
    """Parse the LLM's final message + tool trace into the same shape that
    agent_core.py's state machine produces."""
    final_content = _content_to_text(messages[-1].content) if messages else ""
    cleaned = final_content.replace("```json", "").replace("```", "").strip()

    # Some models emit prose before the JSON; grab the last `{...}` block.
    last_open = cleaned.rfind("{")
    last_close = cleaned.rfind("}")
    if last_open != -1 and last_close > last_open:
        cleaned = cleaned[last_open : last_close + 1]

    try:
        parsed = json.loads(cleaned)
    except Exception:
        parsed = {"category": fallback_category, "summary": f"Parse error: {final_content[:200]}"}

    out = {
        "category": parsed.get("category", fallback_category),
        "summary": parsed.get("summary", ""),
        "calendar_status": None,
        "draft_id": None,
    }

    # Walk the tool trace and lift results into structured fields.
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        tool_text = _content_to_text(msg.content)
        if msg.name == "check_calendar_conflicts":
            out["calendar_status"] = tool_text
        elif msg.name == "create_draft_reply":
            if tool_text.startswith("draft_id="):
                out["draft_id"] = tool_text[len("draft_id=") :].split(" ", 1)[0]

    return out


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

class InboxReactAgent:
    """Wraps create_react_agent so callers can use the same .invoke(state) shape
    as the production LangGraph agent in agent_core.py."""

    def __init__(self, gmail_service: Any, calendar_service: Any):
        self._gmail = gmail_service
        self._calendar = calendar_service

    def invoke(self, state: dict, config: dict | None = None) -> dict:
        tools = _make_tools(
            gmail_service=self._gmail,
            calendar_service=self._calendar,
            email_id=state["email_id"],
            sender=state["sender"],
        )
        prompt = SYSTEM_PROMPT_TEMPLATE.format(today=datetime.now().isoformat())
        agent = create_react_agent(llm, tools=tools, prompt=prompt)

        user_msg = (
            f"From: {state['sender']}\n"
            f"Subject: {state['subject']}\n"
            f"Content: {state['email_content']}"
        )
        result = agent.invoke({"messages": [HumanMessage(content=user_msg)]}, config=config)

        structured = _extract_structured_output(result["messages"])
        return {
            "email_id": state["email_id"],
            "sender": state["sender"],
            "subject": state["subject"],
            "email_content": state["email_content"],
            **structured,
        }


def create_inbox_react_agent(gmail_service: Any, calendar_service: Any) -> InboxReactAgent:
    """Drop-in replacement for agent_core.create_inbox_agent (same .invoke API)."""
    return InboxReactAgent(gmail_service, calendar_service)
