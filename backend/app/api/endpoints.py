from typing import List
from fastapi import APIRouter, Header, HTTPException, Depends
from app.models import ProcessRequest, EmailResult
# Import from our divided services
from app.services.google_utils import get_gmail_service, get_calendar_service, fetch_unread_emails
from app.services.agent_core import create_inbox_agent

router = APIRouter()

# --- HELPER: Usage Limits ---
async def check_usage_limit(user_id: str, requested_amount: int):
    """
    Mock database check. Replace with real DB logic later.
    """
    # For now, we just print the check
    print(f"Checking limits for user {user_id} requesting {requested_amount} emails")
    return True

# --- ROUTE: Process Emails ---
@router.post("/process", response_model=List[EmailResult])
async def process_inbox(request: ProcessRequest, x_user_id: str = Header(...)):
    """
    1. Validate Usage
    2. Fetch Emails (using google_utils)
    3. Run AI Agent (using agent_core)
    """
    # 1. Check Usage
    await check_usage_limit(x_user_id, request.max_results)

    try:
        # 2. Setup Services
        gmail_service = get_gmail_service(request.credentials)
        calendar_service = get_calendar_service(request.credentials)
        
        # 3. Fetch Data (Imported Function)
        emails = fetch_unread_emails(gmail_service, max_results=request.max_results)
        
        if not emails:
            return []

        # 4. Initialize Agent for this specific user
        agent = create_inbox_agent(gmail_service, calendar_service)

        # 5. Run Logic
        final_results = []
        for email_data in emails:
            result = agent.invoke(email_data)
            
            final_results.append(EmailResult(
                subject=result['subject'],
                sender=result['sender'],
                category=result['category'],
                summary=result['summary'],
                draft_id=result.get('draft_id'),
                calendar_status=result.get('calendar_status')
            ))

        return final_results

    except Exception as e:
        # Log the full error for debugging
        print(f"API Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/usage")
async def get_usage(x_user_id: str = Header(...)):
    return {
        "user_id": x_user_id,
        "daily_limit": 50,
        "used_today": 0, # Connect to DB
        "remaining": 50
    }