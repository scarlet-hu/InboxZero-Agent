#!/usr/bin/env python3
"""
InboxZero MCP Server

Exposes Gmail / Calendar tools so any MCP client (Claude Desktop, Cursor, etc.)
can call them directly without going through the FastAPI layer.

Auth: reads token.json from the project root (created when you first log in
via the web app or run the OAuth flow locally).

Usage:
  python backend/mcp_server.py          # stdio transport (Claude Desktop)
  mcp dev backend/mcp_server.py         # interactive inspector
"""
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# sys.path must be prepended before any local app.* imports.
# All app.* imports are deferred inside functions, so this ordering is safe.
sys.path.insert(0, str(Path(__file__).parent))
load_dotenv(Path(__file__).parent / ".env")

app = Server("inboxzero")

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _load_creds():
    """Load Google OAuth credentials from token.json, refreshing if expired."""
    import os

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials as GoogleCredentials

    token_path = Path(__file__).parent.parent / "token.json"
    if not token_path.exists():
        raise FileNotFoundError(
            f"token.json not found at {token_path}.\n"
            "Log in via the InboxZero web app first to generate it."
        )
    with open(token_path) as f:
        data = json.load(f)

    creds = GoogleCredentials(
        token=data["token"],
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=data.get("client_id") or os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=data.get("client_secret") or os.getenv("GOOGLE_CLIENT_SECRET"),
        scopes=data.get("scopes", []),
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # Write refreshed token back so next call doesn't need to refresh again
        data["token"] = creds.token
        with open(token_path, "w") as f:
            json.dump(data, f, indent=2)

    from app.models import GmailCredentials
    return GmailCredentials(
        token=creds.token,
        refresh_token=creds.refresh_token,
        token_uri=creds.token_uri,
        scopes=list(creds.scopes or data.get("scopes", [])),
    )


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="list_unread_emails",
            description=(
                "Fetch unread emails from the user's Gmail inbox. "
                "Returns sender, subject, and body snippet for each email."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of emails to return (default 5, max 20).",
                        "default": 5,
                    }
                },
                "required": [],
            },
        ),
        Tool(
            name="check_calendar_conflicts",
            description=(
                "Check Google Calendar for existing events in a time window. "
                "Returns a list of event summaries and start times, or an empty list if free."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "time_min": {
                        "type": "string",
                        "description": "Start of window in ISO 8601, e.g. 2026-05-05T09:00:00Z",
                    },
                    "time_max": {
                        "type": "string",
                        "description": "End of window in ISO 8601, e.g. 2026-05-05T10:00:00Z",
                    },
                },
                "required": ["time_min", "time_max"],
            },
        ),
        Tool(
            name="classify_email",
            description=(
                "Run the InboxZero LangGraph agent on a single email. "
                "Classifies it as action / fyi / spam, checks calendar for meeting conflicts, "
                "and creates a Gmail draft for action emails. "
                "Returns category, summary, calendar_status, and draft_id."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "email_id": {
                        "type": "string",
                        "description": "Gmail message ID (from list_unread_emails).",
                    },
                    "sender": {"type": "string"},
                    "subject": {"type": "string"},
                    "email_content": {"type": "string"},
                },
                "required": ["email_id", "sender", "subject", "email_content"],
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    from app.services.google_utils import (
        fetch_unread_emails,
        get_calendar_service,
        get_gmail_service,
    )

    creds = _load_creds()

    if name == "list_unread_emails":
        service = get_gmail_service(creds)
        max_results = min(int(arguments.get("max_results", 5)), 20)
        emails = fetch_unread_emails(service, max_results=max_results)
        return [TextContent(type="text", text=json.dumps(emails, ensure_ascii=False, indent=2))]

    if name == "check_calendar_conflicts":
        service = get_calendar_service(creds)
        result = service.events().list(
            calendarId="primary",
            timeMin=arguments["time_min"],
            timeMax=arguments["time_max"],
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = [
            {"summary": e.get("summary", "(no title)"), "start": e.get("start")}
            for e in result.get("items", [])
        ]
        payload = {"free": len(events) == 0, "events": events}
        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]

    if name == "classify_email":
        from app.services.agent_core import create_inbox_agent

        gmail_svc = get_gmail_service(creds)
        calendar_svc = get_calendar_service(creds)
        agent = create_inbox_agent(gmail_svc, calendar_svc)
        result = agent.invoke({
            "email_id": arguments["email_id"],
            "sender": arguments["sender"],
            "subject": arguments["subject"],
            "email_content": arguments["email_content"],
            "category": None,
            "summary": None,
            "calendar_status": None,
            "draft_id": None,
        })
        output = {
            "category": result.get("category"),
            "summary": result.get("summary"),
            "calendar_status": result.get("calendar_status"),
            "draft_id": result.get("draft_id"),
        }
        return [TextContent(type="text", text=json.dumps(output, ensure_ascii=False, indent=2))]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
