import base64
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from app.models import GmailCredentials

def get_gmail_service(creds_data: GmailCredentials):
    """Creates a Google API service instance from dynamic user credentials."""
    creds = Credentials(
        token=creds_data.token,
        refresh_token=creds_data.refresh_token,
        token_uri=creds_data.token_uri,
        client_id=creds_data.client_id,
        client_secret=creds_data.client_secret,
        scopes=creds_data.scopes
    )
    return build('gmail', 'v1', credentials=creds)

def get_calendar_service(creds_data: GmailCredentials):
    """Creates a Google Calendar API service instance."""
    creds = Credentials(
        token=creds_data.token,
        refresh_token=creds_data.refresh_token,
        token_uri=creds_data.token_uri,
        client_id=creds_data.client_id,
        client_secret=creds_data.client_secret,
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