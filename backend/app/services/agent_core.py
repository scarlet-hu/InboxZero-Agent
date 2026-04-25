import base64
import json
from datetime import datetime
from email.message import EmailMessage
from functools import partial
from typing import Any, Literal, Optional, TypedDict

from dotenv import load_dotenv

# Load env vars (GOOGLE_API_KEY) immediately
load_dotenv()

# AI & Graph Libraries
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph

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
        "You are an AI Executive Assistant. Classify the email into EXACTLY ONE category.\n\n"
        "DECISION ORDER (apply in this order — first match wins):\n"
        "  1. Check SPAM signals first.\n"
        "  2. If not spam, check ACTION (does a real human want a written reply from you?).\n"
        "  3. Otherwise it is FYI.\n\n"
        "**spam**: Unwanted, fraudulent, or cold unsolicited emails. SPAM OVERRIDES the 'automated → fyi' rule.\n"
        "  Strong spam signals (any one is enough):\n"
        "  - Lottery/prize/inheritance winnings, requests for bank or wallet details\n"
        "  - Phishing: 'verify your account', 'unusual sign-in — click here', urgent account suspension threats from suspicious or look-alike domains (e.g., b4nk.com, paypa1.com)\n"
        "  - Gift card / wire transfer / 'urgent favor' requests, especially from unknown or impersonated senders\n"
        "  - Unsolicited cold sales / lead-gen outreach from senders with no prior relationship (SEO services, generic 'boost your business' pitches)\n"
        "  - Unsolicited pharma, gambling, get-rich-quick, or adult-content promotions\n"
        "  - Mismatched sender domain vs claimed identity, or obvious typos/grammar of a scam\n\n"
        "**action**: Real-person emails that REQUIRE a written email reply from you.\n"
        "  - Direct questions from a real human asking for your input, decision, approval, or confirmation\n"
        "  - Meeting requests, scheduling proposals, or appointment confirmations from a known/legitimate sender\n"
        "  - Tasks, deliverables, or reviews explicitly assigned to you by a manager, client, or colleague\n"
        "  - Personal invites from friends/colleagues that need an RSVP\n"
        "  Note: A legitimate human asking you to confirm an appointment IS action, even if the topic looks routine.\n\n"
        "**fyi**: Legitimate informational emails that do NOT need a written reply.\n"
        "  - Automated emails from real services you use (GitHub, Uber, Atlassian, Stripe, AWS, Google, Figma, Notion, LinkedIn, CI systems, etc.)\n"
        "  - Receipts, shipping notices, invoices, renewal reminders, calendar reminders\n"
        "  - Security alerts and account notifications from LEGITIMATE providers (even if they say 'action required' — the action is clicking a link, not replying)\n"
        "  - Newsletters, digests, product update announcements, marketing from services you've signed up for\n"
        "  - Status updates or incident notifications you're informed of but not asked to act on\n"
        "  - Anything where the only 'action' is clicking a link/button, not composing a reply\n\n"
        "TIE-BREAKERS:\n"
        "  - Automated + from a recognized legitimate service → fyi.\n"
        "  - Automated + scammy signals (suspicious domain, unrealistic offer, credential request) → spam.\n"
        "  - Human-sent + asks a question or requires a reply → action, even on routine topics.\n\n"
        "Return ONLY valid JSON, no markdown: {\"category\": \"action|fyi|spam\", \"summary\": \"brief summary\"}"
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
    print("🗓️  Checking calendar for context...")

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
    print("✍️  Drafting reply...")

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
