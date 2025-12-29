import os
import json
import base64
from typing import TypedDict, Literal
from dotenv import load_dotenv

# Google & AI Libraries
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END

load_dotenv()

# --- 1. CONFIGURATION & STATE ---
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

class AgentState(TypedDict):
    email_id: str
    sender: str
    subject: str
    email_content: str
    category: Literal["spam", "fyi", "action"]
    summary: str

# Initialize Gemini
llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", temperature=0)

# --- 2. GMAIL UTILITIES ---
def get_gmail_service():
    if not os.path.exists('token.json'):
        raise FileNotFoundError("Run auth_test.py first to generate token.json")
    creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    return build('gmail', 'v1', credentials=creds)

def fetch_unread_emails(service, max_results=5):
    results = service.users().messages().list(userId='me', labelIds=['INBOX', 'UNREAD'], maxResults=max_results).execute()
    messages = results.get('messages', [])
    
    parsed_emails = []
    for msg_meta in messages:
        msg = service.users().messages().get(userId='me', id=msg_meta['id']).execute()
        
        # Extract headers
        headers = msg.get('payload', {}).get('headers', [])
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), "No Subject")
        sender = next((h['value'] for h in headers if h['name'] == 'From'), "Unknown")
        
        # Extract Body
        parts = msg.get('payload', {}).get('parts', [])
        body = ""
        if not parts: # Simple message
            body = msg.get('payload', {}).get('body', {}).get('data', '')
        else: # Multipart message
            for part in parts:
                if part['mimeType'] == 'text/plain':
                    body = part.get('body', {}).get('data', '')
        
        # Decode base64
        decoded_body = base64.urlsafe_b64decode(body).decode('utf-8') if body else "No content"
        
        parsed_emails.append({
            "email_id": msg_meta['id'],
            "sender": sender,
            "subject": subject,
            "email_content": decoded_body[:2000] # Limit to 2000 chars for prompt safety
        })
    return parsed_emails

# --- 3. AGENT NODES ---
def categorize_node(state: AgentState):
    print(f"🧐 Analyzing email from: {state['sender']}")
    
    prompt = (
        "You are an AI Executive Assistant. Categorize this email into: 'spam', 'fyi', or 'action'.\n"
        "Provide a short summary. Return JSON: {\"category\": \"...\", \"summary\": \"...\"}"
    )
    
    user_msg = f"Subject: {state['subject']}\nContent: {state['email_content']}"
    
    response = llm.invoke([SystemMessage(content=prompt), HumanMessage(content=user_msg)])
    
    # Cleanup Gemini JSON markdown
    content = response.content.replace("```json", "").replace("```", "").strip()
    data = json.loads(content)
    
    return {
        "category": data.get("category", "fyi"),
        "summary": data.get("summary", "No summary provided")
    }

# --- 4. GRAPH CONSTRUCTION ---
workflow = StateGraph(AgentState)
workflow.add_node("categorizer", categorize_node)
workflow.add_edge(START, "categorizer")
workflow.add_edge("categorizer", END)
agent_app = workflow.compile()

# --- 5. EXECUTION LOOP ---
def main():
    try:
        service = get_gmail_service()
        emails = fetch_unread_emails(service)
        
        if not emails:
            print("Inbox is already Zero! 🎉")
            return

        for email_data in emails:
            # Run the agent for each email
            result = agent_app.invoke(email_data)
            
            print(f"\n[Result for: {result['subject'][:30]}...]")
            print(f"  Category: {result['category'].upper()}")
            print(f"  Summary:  {result['summary']}")
            print("-" * 40)

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()