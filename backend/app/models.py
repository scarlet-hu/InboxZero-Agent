from typing import List, Optional

from pydantic import BaseModel

# --- 1. DATA MODELS ---

class GmailCredentials(BaseModel):
    token: str
    refresh_token: Optional[str] = None
    token_uri: str = "https://oauth2.googleapis.com/token" # Default for Google
    scopes: List[str]

class ProcessRequest(BaseModel):
    max_results: int = 10

class EmailResult(BaseModel):
    subject: str
    sender: str
    category: str
    summary: str
    draft_id: Optional[str]
    calendar_status: Optional[str]
