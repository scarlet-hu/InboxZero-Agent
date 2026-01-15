import streamlit as st
import pandas as pd
import requests
import os
from google_auth_oauthlib.flow import InstalledAppFlow

# --- CONFIGURATION ---
BACKEND_URL = "http://localhost:8000"  # Address of your running FastAPI server
CLIENT_SECRETS_FILE = "credentials.json" # Needed for the Login Flow
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/calendar.readonly'
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
        
        # Store only the user's tokens (client_id/secret are in backend .env)
        st.session_state['auth_token'] = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "scopes": creds.scopes
        }
        
        # Simple hack to get user email (not strictly needed for logic, but good for UI)
        # In a real app, decode the ID token. Here we just set a placeholder or fetch profile.
        st.session_state['user_email'] = "user@example.com" 
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
            # The backend loads client_id/secret from its .env file
            payload = {
                "credentials": st.session_state['auth_token'],
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