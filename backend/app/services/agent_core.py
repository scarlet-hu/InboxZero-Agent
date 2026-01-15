import json
import base64
from datetime import datetime
from email.message import EmailMessage
from typing import TypedDict, Literal, Optional, Any
from functools import partial
from dotenv import load_dotenv

# Load env vars (GOOGLE_API_KEY) immediately
load_dotenv()

# AI & Graph Libraries
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END

# Initialize Gemini (Global instance is fine, as API key is usually env-based)
# Ensure GOOGLE_API_KEY is set in your .env
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

# --- 1. STATE DEFINITION ---

class AgentState(TypedDict):
    """
    The state of the email processing workflow.
    """
    email_id: str
    sender: str
    subject: str
    email_content: str
    category: Literal["spam", "fyi", "action"]
    summary: str
    calendar_status: Optional[str]
    draft_id: Optional[str]

# --- 2. NODE LOGIC (Pure Functions) ---

def categorize_logic(state: AgentState):
    """Analyzes the email content to determine category and summary."""
    print(f"🧐 Analyzing: {state['subject'][:40]}...")
    prompt = (
        "You are an AI Executive Assistant. Categorize this email into one of these categories:\n\n"
        "**action**: Emails that REQUIRE an EMAIL RESPONSE from the recipient:\n"
        "  - Direct questions from real people asking for your input or reply\n"
        "  - Meeting requests or scheduling proposals from colleagues\n"
        "  - Tasks assigned to you by managers or clients\n"
        "  - Requests for decisions, approvals, or feedback that need your written response\n\n"
        "**fyi**: Informational emails that do NOT require an email response:\n"
        "  - ALL automated emails from services (Google, Uber, Atlassian, GitHub, etc.)\n"
        "  - Human-sent status updates or notices where no reply is expected\n"
        "  - Security alerts, password resets, account notifications (even if they say 'action required')\n"
        "  - Subscription reminders, renewal notices, platform notifications\n"
        "  - Receipts, confirmations, order updates, shipping notifications\n"
        "  - Newsletters, blog updates, marketing emails\n"
        "  - System-generated alerts or warnings (even if they suggest checking something)\n"
        "  - Status updates, reports you're CC'd on\n"
        "  - Any email where the 'action' is clicking a button/link, NOT writing a reply\n\n"
        "**spam**: Unwanted or irrelevant emails:\n"
        "  - Unsolicited marketing or promotional emails from unknown senders\n"
        "  - Phishing attempts\n"
        "  - Obvious junk mail\n\n"
        "KEY RULE: If the email is automated/system-generated OR the action is to click a link (not reply), choose 'fyi'.\n\n"
        "Return ONLY valid JSON with no markdown formatting: {\"category\": \"action|fyi|spam\", \"summary\": \"brief summary\"}"
    )
    user_msg = f"From: {state['sender']}\nSubject: {state['subject']}\nContent: {state['email_content']}"
    
    try:
        response = llm.invoke([SystemMessage(content=prompt), HumanMessage(content=user_msg)])
        # Clean potential markdown
        content = response.content.replace("```json", "").replace("```", "").strip()
        data = json.loads(content)
        return {"category": data.get("category", "fyi"), "summary": data.get("summary", "No summary")}
    except Exception as e:
        return {"category": "fyi", "summary": f"Error parsing: {str(e)}"}

def calendar_check_logic(state: AgentState, calendar_service: Any):
    """Checks the user's calendar if the email contains a date."""
    print(f"🗓️  Checking calendar for context...")
    
    # 1. Extract Date
    date_prompt = (
        f"Identify if this email suggests a meeting date. Today is {datetime.now().isoformat()}. "
        "Return start/end in ISO 8601. If none, return null.\n"
        "Return ONLY valid JSON with no markdown: {\"subject\": \"...\", \"body\": \"...\"}"
    )
    
    try:
        response = llm.invoke([SystemMessage(content=date_prompt), HumanMessage(content=state['email_content'])])
        content = response.content.replace("```json", "").replace("```", "").strip()
        time_data = json.loads(content)
    except Exception:
        return {"calendar_status": "Could not parse date."}
    
    if not time_data.get('start') or time_data.get('start') == 'null':
        return {"calendar_status": "No specific time mentioned."}

    # 2. Check Google Calendar API (using injected service)
    try:
        events_result = calendar_service.events().list(
            calendarId='primary',
            timeMin=time_data['start'],
            timeMax=time_data['end'],
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        status = f"✅ Free at {time_data['start']}." if not events else f"❌ Conflict: '{events[0]['summary']}'."
        return {"calendar_status": status}
    except Exception as e:
        return {"calendar_status": f"Calendar API error: {str(e)}"}

def draft_reply_logic(state: AgentState, gmail_service: Any):
    """Drafts a reply in Gmail using the injected service."""
    print(f"✍️  Drafting reply...")
    
    # Check for existing drafts first
    try:
        # Get thread ID
        email_details = gmail_service.users().messages().get(userId='me', id=state['email_id']).execute()
        thread_id = email_details.get('threadId')
        
        drafts = gmail_service.users().drafts().list(userId='me').execute().get('drafts', [])
        for d in drafts:
            if d.get('message', {}).get('threadId') == thread_id:
                return {"draft_id": d['id']}
    except Exception as e:
        print(f"Draft check warning: {e}")

    # Generate Content
    reply_prompt = (
        "Write a professional, brief email reply. "
        f"Context: {state['category']}. Calendar: {state['calendar_status'] or 'N/A'}. "
        "JSON: {\"subject\": \"...\", \"body\": \"...\"}"
    )
    
    try:
        response = llm.invoke([SystemMessage(content=reply_prompt), HumanMessage(content=state['email_content'])])
        content = response.content.replace("```json", "").replace("```", "").strip()
        draft_content = json.loads(content)
    except Exception:
        draft_content = {"subject": f"Re: {state['subject']}", "body": "Received, thank you."}

    # Create Draft
    try:
        message = EmailMessage()
        message.set_content(draft_content['body'])
        message['To'] = state['sender']
        message['Subject'] = draft_content['subject']
        
        # Threading headers
        headers = email_details.get('payload', {}).get('headers', [])
        msg_id = next((h['value'] for h in headers if h['name'].lower() == 'message-id'), None)
        if msg_id:
            message['In-Reply-To'] = msg_id
            message['References'] = msg_id

        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        create_message = {'message': {'raw': encoded_message, 'threadId': thread_id}}
        
        draft = gmail_service.users().drafts().create(userId="me", body=create_message).execute()
        return {"draft_id": draft['id']}
    except Exception as e:
        print(f"Failed to create draft: {e}")
        return {"draft_id": None}

# --- 3. GRAPH FACTORY ---

def create_inbox_agent(gmail_service, calendar_service):
    """
    Creates and compiles a LangGraph agent specific to a user's session.
    Dependency Injection: pass the authenticated services here.
    """
    
    # Bind the services to the nodes using partials
    # This "locks in" the specific user's Gmail/Calendar service for this graph instance
    calendar_node_with_service = partial(calendar_check_logic, calendar_service=calendar_service)
    draft_node_with_service = partial(draft_reply_logic, gmail_service=gmail_service)

    # Build the graph
    workflow = StateGraph(AgentState)
    
    workflow.add_node("categorizer", categorize_logic)
    workflow.add_node("check_calendar", calendar_node_with_service)
    workflow.add_node("draft_reply", draft_node_with_service)

    # Define Conditional Routing
    def route_after_categorize(state: AgentState):
        if state["category"] == "action":
            return "check_calendar"
        return END

    workflow.add_edge(START, "categorizer")
    workflow.add_conditional_edges("categorizer", route_after_categorize)
    workflow.add_edge("check_calendar", "draft_reply")
    workflow.add_edge("draft_reply", END)

    return workflow.compile()