import streamlit as st
import pandas as pd
import requests
import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow

# --- CONFIGURATION ---
BACKEND_URL = "http://localhost:8000"  # Address of your running FastAPI server
CLIENT_SECRETS_FILE = os.path.join(os.path.dirname(__file__), "frontend", "credentials.json") # Needed for the Login Flow
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/userinfo.email',  # Add this to get user email
    'openid'  # Add this for OpenID Connect
]

# Page Setup
st.set_page_config(
    page_title="Inbox Zero Agent (Multi-User)",
    page_icon="⚡",
    layout="wide"
)

# --- SESSION STATE MANAGEMENT ---
if 'auth_token' not in st.session_state:
    st.session_state['auth_token'] = None
if 'user_email' not in st.session_state:
    st.session_state['user_email'] = None

# --- AUTHENTICATION HELPER ---
def login_with_google():
    """
    Runs the local OAuth flow to get user credentials.
    NOTE: This opens a browser window on the machine running Streamlit.
    """
    try:
        if not os.path.exists(CLIENT_SECRETS_FILE):
            st.error(f"Missing {CLIENT_SECRETS_FILE}. Please add it to the frontend folder.")
            return

        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
        
        # Get user email from the ID token (more reliable than separate API call)
        import google.auth.transport.requests
        from google.oauth2.credentials import Credentials
        
        # Create a Credentials object
        google_creds = Credentials(
            token=creds.token,
            refresh_token=creds.refresh_token,
            token_uri=creds.token_uri,
            client_id=creds.client_id,
            client_secret=creds.client_secret,
            scopes=creds.scopes
        )
        
        # Store the full credentials object as a dict in session state
        st.session_state['auth_token'] = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes
        }
        
        # Try to get email from ID token first, then fall back to userinfo API
        user_email = "user@example.com"
        
        # Method 1: Decode ID token if available
        if hasattr(creds, 'id_token') and creds.id_token:
            import jwt
            try:
                decoded = jwt.decode(creds.id_token, options={"verify_signature": False})
                user_email = decoded.get('email', user_email)
                st.success(f"✅ Got email from ID token: {user_email}")
            except Exception as e:
                st.warning(f"Could not decode ID token: {e}")
        
        # Method 2: Fetch from userinfo API (fallback)
        if user_email == "user@example.com":
            try:
                userinfo_response = requests.get(
                    "https://www.googleapis.com/oauth2/v2/userinfo",
                    headers={"Authorization": f"Bearer {creds.token}"}
                )
                if userinfo_response.status_code == 200:
                    user_info = userinfo_response.json()
                    user_email = user_info.get('email', user_email)
                    st.success(f"✅ Got email from userinfo API: {user_email}")
                else:
                    st.error(f"⚠️ Userinfo API returned status {userinfo_response.status_code}: {userinfo_response.text}")
            except Exception as e:
                st.error(f"⚠️ Exception calling userinfo API: {str(e)}")
        
        st.session_state['user_email'] = user_email
        
        st.rerun()
        
    except Exception as e:
        st.error(f"Login failed: {e}")

def logout():
    st.session_state['auth_token'] = None
    st.session_state['user_email'] = None
    st.rerun()

# --- MAIN UI ---

st.title("⚡ Inbox Zero Agent")

# 1. LOGIN SCREEN
if not st.session_state['auth_token']:
    st.info("Please sign in to access your secure agent.")
    col1, col2 = st.columns([1, 2])
    with col1:
        if st.button("Sign in with Google", type="primary"):
            login_with_google()
    st.stop() # Stop execution here if not logged in

# 2. DASHBOARD (LOGGED IN)
with st.sidebar:
    st.write(f"Authenticated as: **{st.session_state['user_email']}**")
    if st.button("Logout"):
        logout()
    
    st.divider()
    max_emails = st.slider("Emails to fetch", 1, 20, 5)
    run_btn = st.button("🚀 Run Agent", type="primary")

st.markdown("### Agent Dashboard")

if run_btn:
    with st.spinner("Contacting Agent Backend..."):
        try:
            # Prepare the payload for the API
            # IMPORTANT: Filter out client_id/secret. The backend has its own copies in .env.
            # We only send the user's tokens.
            safe_creds = {
                k: v for k, v in st.session_state['auth_token'].items() 
                if k in ['token', 'refresh_token', 'token_uri', 'scopes']
            }

            payload = {
                "credentials": safe_creds,
                "max_results": max_emails
            }
            
            # Use a unique ID for the user header
            headers = {"x-user-id": "streamlit-user-v1"}

            # CALL THE BACKEND API
            response = requests.post(
                f"{BACKEND_URL}/agent/process",
                json=payload,
                headers=headers
            )

            if response.status_code == 200:
                results = response.json()
                
                if not results:
                    st.success("Inbox is already Zero! 🎉")
                else:
                    # Convert API result to DataFrame
                    df = pd.DataFrame(results)
                    
                    # Display metrics
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Emails Processed", len(df))
                    c2.metric("Actions Found", len(df[df['category'] == 'action']))
                    c3.metric("Drafts Created", len(df[df['draft_id'].notnull()]))
                    
                    # Display Data
                    st.dataframe(
                        df,
                        column_config={
                            "subject": "Subject",
                            "sender": "From",
                            "category": "Category",
                            "summary": st.column_config.TextColumn("Summary", width="large"),
                            "draft_id": "Draft ID",
                            "calendar_status": "Calendar"
                        },
                        hide_index=True
                    )
            else:
                st.error(f"Backend Error ({response.status_code}): {response.text}")

        except requests.exceptions.ConnectionError:
            st.error("❌ Could not connect to Backend. Is it running on port 8000?")
        except Exception as e:
            st.error(f"An unexpected error occurred: {e}")

# Footer
st.divider()
st.caption("Decoupled Architecture: Frontend (Streamlit) -> Backend (FastAPI)")