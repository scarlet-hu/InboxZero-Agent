from typing import List, Optional
from pydantic import BaseModel

# --- 1. DATA MODELS ---

class GmailCredentials(BaseModel):
    token: str
    refresh_token: str
    token_uri: str
    client_id: str
    client_secret: str
    scopes: List[str]

class ProcessRequest(BaseModel):
    credentials: GmailCredentials
    max_results: int = 10

class EmailResult(BaseModel):
    subject: str
    sender: str
    category: str
    summary: str
    draft_id: Optional[str]
    calendar_status: Optional[str]