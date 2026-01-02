import os
import json
import base64
from datetime import datetime
from email.message import EmailMessage
from typing import TypedDict, Literal, Optional
from dotenv import load_dotenv

# Google & AI Libraries
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END

load_dotenv()

# --- 1. CONFIGURATION & STATE ---
# Added 'gmail.compose' so we can create drafts
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/calendar.readonly'
]

class AgentState(TypedDict):
    email_id: str
    sender: str
    subject: str
    email_content: str
    category: Literal["spam", "fyi", "action"]
    summary: str
    calendar_status: Optional[str]
    draft_id: Optional[str] # New field to track the created draft

# Initialize Gemini
llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", temperature=0)

# --- 2. GOOGLE SERVICE UTILITIES ---
def get_google_services():
    """Handles authentication and returns Gmail and Calendar services."""
    creds = None
    # The file token.json stores the user's access and refresh tokens
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials.json'):
                raise FileNotFoundError("credentials.json not found. Please download it from Google Cloud Console.")
            
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
            
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    gmail_service = build('gmail', 'v1', credentials=creds)
    calendar_service = build('calendar', 'v3', credentials=creds)
    return gmail_service, calendar_service

def fetch_unread_emails(service, max_results=5):
    results = service.users().messages().list(userId='me', labelIds=['INBOX', 'UNREAD'], maxResults=max_results).execute()
    messages = results.get('messages', [])
    
    parsed_emails = []
    for msg_meta in messages:
        msg = service.users().messages().get(userId='me', id=msg_meta['id']).execute()
        headers = msg.get('payload', {}).get('headers', [])
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), "No Subject")
        sender = next((h['value'] for h in headers if h['name'] == 'From'), "Unknown")
        
        parts = msg.get('payload', {}).get('parts', [])
        body = ""
        if not parts:
            body = msg.get('payload', {}).get('body', {}).get('data', '')
        else:
            for part in parts:
                if part['mimeType'] == 'text/plain':
                    body = part.get('body', {}).get('data', '')
        
        decoded_body = base64.urlsafe_b64decode(body).decode('utf-8') if body else "No content"
        
        parsed_emails.append({
            "email_id": msg_meta['id'],
            "sender": sender,
            "subject": subject,
            "email_content": decoded_body[:2000],
            "calendar_status": None,
            "draft_id": None
        })
    return parsed_emails

# --- 3. AGENT NODES ---

def categorize_node(state: AgentState):
    print(f"🧐 Analyzing: {state['subject'][:40]}...")
    prompt = (
        "You are an AI Executive Assistant. Categorize this email into: 'spam', 'fyi', or 'action'.\n"
        "Return JSON: {\"category\": \"...\", \"summary\": \"...\"}"
    )
    user_msg = f"From: {state['sender']}\nSubject: {state['subject']}\nContent: {state['email_content']}"
    response = llm.invoke([SystemMessage(content=prompt), HumanMessage(content=user_msg)])
    content = response.content.replace("```json", "").replace("```", "").strip()
    data = json.loads(content)
    return {"category": data.get("category", "fyi"), "summary": data.get("summary", "No summary")}

def calendar_check_node(state: AgentState):
    """If the email is an action item, check if it mentions a date and check the calendar."""
    print(f"🗓️  Checking calendar for context...")
    
    # 1. Ask Gemini to extract a potential date/time from the email
    date_prompt = (
        "Identify if this email suggests a meeting date and time. "
        f"Today's date is {datetime.now().isoformat()}. "
        "Return the start and end time in ISO 8601 format with timezone (e.g., 2025-12-29T14:00:00-08:00). "
        "If no specific time is mentioned, return null for both.\n"
        "Return JSON: {\"start\": \"...\", \"end\": \"...\"}"
    )
    
    response = llm.invoke([SystemMessage(content=date_prompt), HumanMessage(content=state['email_content'])])
    content = response.content.replace("```json", "").replace("```", "").strip()
    
    try:
        time_data = json.loads(content)
    except json.JSONDecodeError:
        return {"calendar_status": "Could not parse date from email."}
    
    if not time_data.get('start') or time_data.get('start') == 'null':
        return {"calendar_status": "No specific time mentioned in email."}

    # Validate the dates aren't placeholders
    if "YYYY" in time_data['start'] or "MM" in time_data['start']:
        return {"calendar_status": "Could not extract valid date from email."}

    # 2. Call the real Google Calendar API
    _, calendar_service = get_google_services()
    
    try:
        events_result = calendar_service.events().list(
            calendarId='primary',
            timeMin=time_data['start'],
            timeMax=time_data['end'],
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        if not events:
            status = f"✅ You are FREE at {time_data['start']}."
        else:
            status = f"❌ CONFLICT: You have '{events[0]['summary']}' at that time."
            
        return {"calendar_status": status}
    except Exception as e:
        return {"calendar_status": f"Calendar API error: {str(e)}"}

def check_draft_exists(gmail_service, email_id):
    """Check if a draft reply already exists for this email."""
    try:
        # Get the thread ID for the email
        email_details = gmail_service.users().messages().get(userId='me', id=email_id).execute()
        thread_id = email_details.get('threadId')
        
        # List all drafts
        drafts_result = gmail_service.users().drafts().list(userId='me').execute()
        drafts = drafts_result.get('drafts', [])
        
        # Check if any draft belongs to the same thread
        for draft in drafts:
            draft_message = draft.get('message', {})
            if draft_message.get('threadId') == thread_id:
                return draft['id']
        
        return None
    except Exception as e:
        print(f"Warning: Error checking existing drafts: {e}")
        return None

def draft_reply_node(state: AgentState):
    """Creates a draft reply in Gmail based on the categorization and calendar status."""
    print(f"✍️  Drafting reply...")
    
    # Check if a draft already exists
    gmail_service, _ = get_google_services()
    existing_draft_id = check_draft_exists(gmail_service, state['email_id'])
    
    if existing_draft_id:
        print(f"📋 Draft already exists (ID: {existing_draft_id}), skipping creation")
        return {"draft_id": existing_draft_id}
    
    reply_prompt = (
        "Write a professional, brief email reply. "
        f"Context: The email was categorized as {state['category']}. "
        f"Calendar Status: {state['calendar_status'] or 'N/A'}. "
        "If there is a conflict, politely decline or ask for another time. "
        "If free, confirm. If no time was mentioned, just acknowledge the email.\n"
        "Return JSON: {\"subject\": \"...\", \"body\": \"...\"}"
    )
    
    response = llm.invoke([SystemMessage(content=reply_prompt), HumanMessage(content=state['email_content'])])
    draft_content = json.loads(response.content.replace("```json", "").replace("```", "").strip())

    # Get the original email details for proper threading
    original_email = gmail_service.users().messages().get(userId='me', id=state['email_id']).execute()
    thread_id = original_email.get('threadId')
    headers = original_email.get('payload', {}).get('headers', [])
    message_id = next((h['value'] for h in headers if h['name'].lower() == 'message-id'), None)
    
    # Create Gmail Draft with proper reply headers
    message = EmailMessage()
    message.set_content(draft_content['body'])
    message['To'] = state['sender']
    message['Subject'] = f"Re: {state['subject']}"
    
    # Add reply headers for proper threading
    if message_id:
        message['In-Reply-To'] = message_id
        message['References'] = message_id
    
    # Encoded message
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    create_message = {
        'message': {
            'raw': encoded_message,
            'threadId': thread_id  # Associate with the original thread
        }
    }
    
    draft = gmail_service.users().drafts().create(userId="me", body=create_message).execute()
    print(f"📁 Draft created: {draft['id']}")
    
    return {"draft_id": draft['id']}

# --- 4. GRAPH CONSTRUCTION ---

def route_after_categorize(state: AgentState):
    if state["category"] == "action": return "check_calendar"
    return END

workflow = StateGraph(AgentState)
workflow.add_node("categorizer", categorize_node)
workflow.add_node("check_calendar", calendar_check_node)
workflow.add_node("draft_reply", draft_reply_node)

workflow.add_edge(START, "categorizer")
workflow.add_conditional_edges("categorizer", route_after_categorize)
workflow.add_edge("check_calendar", "draft_reply")
workflow.add_edge("draft_reply", END)

agent_app = workflow.compile()

# --- 5. EXECUTION ---
def main():
    try:
        gmail_service, _ = get_google_services()
        emails = fetch_unread_emails(gmail_service)
        if not emails:
            print("Inbox is already Zero! 🎉")
            return
        for email_data in emails:
            result = agent_app.invoke(email_data)
            print(f"SUMMARY: {result['summary']}")
            if result['draft_id']: print(f"ACTION: Draft created (ID: {result['draft_id']})")
            print("-" * 40)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()