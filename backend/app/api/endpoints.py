from typing import List

from app.models import EmailResult, GmailCredentials, ProcessRequest
from app.services.agent_core import create_inbox_agent
from app.services.auth import SessionData, get_current_session
from app.services.google_utils import fetch_unread_emails, get_calendar_service, get_gmail_service
from fastapi import APIRouter, Depends, HTTPException

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
