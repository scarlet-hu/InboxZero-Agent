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


class DraftContent(BaseModel):
    """Read response for a Gmail draft — what the dashboard needs to edit it."""
    draft_id: str
    to: str
    subject: str
    body: str


class DraftUpdate(BaseModel):
    """Request body for updating an existing draft (PUT /drafts/{id})."""
    subject: str
    body: str
