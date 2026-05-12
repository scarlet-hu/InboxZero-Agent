import asyncio
from typing import List

from app.models import DraftContent, DraftUpdate, EmailResult, GmailCredentials, ProcessRequest
# TEMP: swapped to ReAct experiment build. Revert this import to switch back.
from app.services.agent_core import create_inbox_agent
# from app.services.agent_core_react import create_inbox_react_agent as create_inbox_agent
from app.services.auth import SessionData, get_current_session
from app.services.demo_data import get_demo_draft, get_demo_results
from app.services.google_utils import (
    discard_draft,
    fetch_unread_emails,
    get_calendar_service,
    get_gmail_service,
    read_draft_content,
    send_draft,
    update_draft_content,
)
from fastapi import APIRouter, Depends, HTTPException
from googleapiclient.errors import HttpError

router = APIRouter()


async def check_usage_limit(user_id: str, requested_amount: int):
    """Mock database check. Replace with real DB logic later."""
    print(f"Checking limits for user {user_id} requesting {requested_amount} emails")
    return True


def _credentials_from_session(session: SessionData) -> GmailCredentials:
    return GmailCredentials(
        token=session.token,
        refresh_token=session.refresh_token,
        token_uri=session.token_uri,
        scopes=session.scopes,
    )


@router.post("/process", response_model=List[EmailResult])
async def process_inbox(
    request: ProcessRequest,
    session: SessionData = Depends(get_current_session),
):
    """Run the agent across the user's unread inbox.

    Auth: requires a valid session cookie minted by /auth/callback.
    """
    if session.is_demo:
        await asyncio.sleep(0.8)
        return get_demo_results(request.max_results)

    creds = _credentials_from_session(session)
    await check_usage_limit(session.email, request.max_results)

    try:
        gmail_service = get_gmail_service(creds)
        calendar_service = get_calendar_service(creds)

        emails = fetch_unread_emails(gmail_service, max_results=request.max_results)
        if not emails:
            return []

        agent = create_inbox_agent(gmail_service, calendar_service)

        final_results = []
        for email_data in emails:
            result = agent.invoke(email_data)
            final_results.append(EmailResult(
                subject=result['subject'],
                sender=result['sender'],
                category=result['category'],
                summary=result['summary'],
                draft_id=result.get('draft_id'),
                calendar_status=result.get('calendar_status'),
            ))
        return final_results

    except HTTPException:
        raise
    except Exception as e:
        print(f"API Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/usage")
async def get_usage(session: SessionData = Depends(get_current_session)):
    return {
        "user_id": session.email,
        "daily_limit": 50,
        "used_today": 0,  # Connect to DB
        "remaining": 50,
    }


# ---------------------------------------------------------------------------
# Draft review endpoints — review-approve HITL
# ---------------------------------------------------------------------------
#
# The agent creates Gmail drafts (no auto-send). These endpoints let the
# dashboard fetch / edit / send / discard those drafts so the user keeps
# final control over outbound mail. See docs/hitl-strong-design.md for
# the planned LangGraph-interrupt variant.


def _map_gmail_error(e: HttpError) -> HTTPException:
    status = getattr(getattr(e, "resp", None), "status", 500)
    if status == 404:
        return HTTPException(status_code=404, detail="Draft not found")
    if status in (401, 403):
        return HTTPException(status_code=403, detail="Gmail rejected the request")
    return HTTPException(status_code=502, detail=f"Gmail API error: {e}")


@router.get("/drafts/{draft_id}", response_model=DraftContent)
async def get_draft(
    draft_id: str,
    session: SessionData = Depends(get_current_session),
):
    """Return the current contents of a Gmail draft for editing."""
    if session.is_demo:
        demo = get_demo_draft(draft_id)
        if not demo:
            raise HTTPException(status_code=404, detail="Draft not found")
        return DraftContent(**demo)

    gmail_service = get_gmail_service(_credentials_from_session(session))
    try:
        return DraftContent(**read_draft_content(gmail_service, draft_id))
    except HttpError as e:
        raise _map_gmail_error(e) from e


@router.put("/drafts/{draft_id}", response_model=DraftContent)
async def update_draft(
    draft_id: str,
    payload: DraftUpdate,
    session: SessionData = Depends(get_current_session),
):
    """Save edits to a draft (does not send)."""
    if session.is_demo:
        demo = get_demo_draft(draft_id)
        if not demo:
            raise HTTPException(status_code=404, detail="Draft not found")
        # Demo mode: pretend we saved by echoing the edited payload.
        return DraftContent(
            draft_id=draft_id,
            to=demo["to"],
            subject=payload.subject,
            body=payload.body,
        )

    gmail_service = get_gmail_service(_credentials_from_session(session))
    try:
        update_draft_content(gmail_service, draft_id, payload.subject, payload.body)
        return DraftContent(**read_draft_content(gmail_service, draft_id))
    except HttpError as e:
        raise _map_gmail_error(e) from e


@router.post("/drafts/{draft_id}/send", status_code=204)
async def send_draft_endpoint(
    draft_id: str,
    session: SessionData = Depends(get_current_session),
):
    """Send a draft. Irreversible."""
    if session.is_demo:
        if not get_demo_draft(draft_id):
            raise HTTPException(status_code=404, detail="Draft not found")
        return  # demo: no-op

    gmail_service = get_gmail_service(_credentials_from_session(session))
    try:
        send_draft(gmail_service, draft_id)
    except HttpError as e:
        raise _map_gmail_error(e) from e


@router.delete("/drafts/{draft_id}", status_code=204)
async def discard_draft_endpoint(
    draft_id: str,
    session: SessionData = Depends(get_current_session),
):
    """Delete a draft without sending."""
    if session.is_demo:
        if not get_demo_draft(draft_id):
            raise HTTPException(status_code=404, detail="Draft not found")
        return  # demo: no-op

    gmail_service = get_gmail_service(_credentials_from_session(session))
    try:
        discard_draft(gmail_service, draft_id)
    except HttpError as e:
        raise _map_gmail_error(e) from e
