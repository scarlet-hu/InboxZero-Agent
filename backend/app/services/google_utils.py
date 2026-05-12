import base64
import os
from email.message import EmailMessage

from app.models import GmailCredentials
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

load_dotenv()

def get_gmail_service(creds_data: GmailCredentials):
    """Creates a Google API service instance from dynamic user credentials."""
    creds = Credentials(
        token=creds_data.token,
        refresh_token=creds_data.refresh_token,
        token_uri=creds_data.token_uri,
        client_id= os.getenv('GOOGLE_CLIENT_ID'),
        client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
        scopes=creds_data.scopes
    )
    return build('gmail', 'v1', credentials=creds)

def get_calendar_service(creds_data: GmailCredentials):
    """Creates a Google Calendar API service instance."""
    creds = Credentials(
        token=creds_data.token,
        refresh_token=creds_data.refresh_token,
        token_uri=creds_data.token_uri,
        client_id=os.getenv('GOOGLE_CLIENT_ID'),
        client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
        scopes=creds_data.scopes
    )
    return build('calendar', 'v3', credentials=creds)

def fetch_unread_emails(service, max_results=5):
    """
    Fetches unread emails using the provided service object.
    Moved here from main_v1.py to keep concerns separated.
    """
    try:
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
    except Exception as e:
        print(f"Error fetching emails: {e}")
        return []


# ---------------------------------------------------------------------------
# Draft CRUD helpers (used by /drafts/* endpoints — review-approve HITL)
# ---------------------------------------------------------------------------

def _extract_header(headers, name):
    target = name.lower()
    return next((h["value"] for h in headers if h["name"].lower() == target), "")


def _extract_body_text(payload):
    """Walk a Gmail message payload tree and return the first text/plain part decoded."""
    if not payload:
        return ""
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    for part in payload.get("parts", []) or []:
        text = _extract_body_text(part)
        if text:
            return text
    return ""


def read_draft_content(gmail_service, draft_id: str) -> dict:
    """Fetch a Gmail draft and return {to, subject, body} for editing.

    Raises googleapiclient.errors.HttpError on 404 / 403 — caller maps to HTTP.
    """
    draft = gmail_service.users().drafts().get(
        userId="me", id=draft_id, format="full"
    ).execute()
    message = draft.get("message", {}) or {}
    payload = message.get("payload", {}) or {}
    headers = payload.get("headers", []) or []

    return {
        "draft_id": draft_id,
        "to": _extract_header(headers, "To"),
        "subject": _extract_header(headers, "Subject"),
        "body": _extract_body_text(payload),
    }


def update_draft_content(gmail_service, draft_id: str, subject: str, body: str) -> None:
    """Replace a Gmail draft's subject + body, preserving the threading headers.

    We refetch the existing draft to keep the original To / In-Reply-To /
    References so the reply stays threaded correctly. Only subject + body
    are user-editable in this MVP.
    """
    existing = gmail_service.users().drafts().get(
        userId="me", id=draft_id, format="full"
    ).execute()
    message = existing.get("message", {}) or {}
    payload = message.get("payload", {}) or {}
    headers = payload.get("headers", []) or []
    thread_id = message.get("threadId")

    to_addr = _extract_header(headers, "To")
    in_reply_to = _extract_header(headers, "In-Reply-To")
    references = _extract_header(headers, "References")

    new_msg = EmailMessage()
    new_msg.set_content(body)
    new_msg["To"] = to_addr
    new_msg["Subject"] = subject
    if in_reply_to:
        new_msg["In-Reply-To"] = in_reply_to
    if references:
        new_msg["References"] = references

    encoded = base64.urlsafe_b64encode(new_msg.as_bytes()).decode()
    update_body = {"message": {"raw": encoded}}
    if thread_id:
        update_body["message"]["threadId"] = thread_id

    gmail_service.users().drafts().update(
        userId="me", id=draft_id, body=update_body
    ).execute()


def send_draft(gmail_service, draft_id: str) -> None:
    gmail_service.users().drafts().send(
        userId="me", body={"id": draft_id}
    ).execute()


def discard_draft(gmail_service, draft_id: str) -> None:
    gmail_service.users().drafts().delete(userId="me", id=draft_id).execute()
