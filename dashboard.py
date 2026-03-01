import json
import os
import time
import hmac
import hashlib
import secrets

import jwt
import pandas as pd
import requests
import streamlit as st
from google_auth_oauthlib.flow import Flow
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
BACKEND_URL = "http://localhost:8000"  # Address of your running FastAPI server
CLIENT_SECRETS_FILE = os.path.join(
    os.path.dirname(__file__),
    "frontend",
    "credentials.json"
)
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

# Page Setup
st.set_page_config(
    page_title="Inbox Zero Agent (Multi-User)",
    page_icon="⚡",
    layout="wide"
)

# --- SESSION STATE MANAGEMENT ---
if "auth_token" not in st.session_state:
    st.session_state["auth_token"] = None
if "user_email" not in st.session_state:
    st.session_state["user_email"] = None


# --- AUTHENTICATION HELPERS ---
def get_query_param(name: str):
    try:
        value = st.query_params.get(name)
    except AttributeError:
        value = st.experimental_get_query_params().get(name)

    if isinstance(value, list):
        return value[0] if value else None
    return value


def clear_oauth_query_params():
    try:
        for key in ("code", "state", "scope", "error"):
            if key in st.query_params:
                del st.query_params[key]
    except AttributeError:
        st.experimental_set_query_params()


def get_oauth_state_secret():
    return (
        os.getenv("GOOGLE_CLIENT_SECRET")
        or os.getenv("STREAMLIT_SERVER_COOKIE_SECRET")
        or "dev-oauth-state-secret"
    )


def generate_oauth_state():
    nonce = secrets.token_urlsafe(16)
    timestamp = str(int(time.time()))
    payload = f"{nonce}:{timestamp}"
    signature = hmac.new(
        get_oauth_state_secret().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}:{signature}"


def is_valid_oauth_state(state: str, max_age_seconds: int = 600):
    if not state:
        return False

    parts = state.split(":")
    if len(parts) != 3:
        return False

    nonce, timestamp, provided_signature = parts
    if not nonce or not timestamp:
        return False

    try:
        issued_at = int(timestamp)
    except ValueError:
        return False

    if time.time() - issued_at > max_age_seconds:
        return False

    payload = f"{nonce}:{timestamp}"
    expected_signature = hmac.new(
        get_oauth_state_secret().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(provided_signature, expected_signature)


def get_redirect_uri():
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
    if redirect_uri:
        return redirect_uri

    if not os.path.exists(CLIENT_SECRETS_FILE):
        return None

    try:
        with open(CLIENT_SECRETS_FILE, "r", encoding="utf-8") as handle:
            client_config = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None

    oauth_config = client_config.get("web") or client_config.get("installed") or {}
    redirect_uris = oauth_config.get("redirect_uris") or []
    return redirect_uris[0] if redirect_uris else None


def build_google_flow(state=None):
    if not os.path.exists(CLIENT_SECRETS_FILE):
        raise FileNotFoundError(
            f"Missing {CLIENT_SECRETS_FILE}. Please add it to the frontend folder."
        )

    redirect_uri = get_redirect_uri()
    if not redirect_uri:
        raise ValueError(
            "No redirect URI configured. Set GOOGLE_REDIRECT_URI or add a valid "
            "web redirect URI to frontend/credentials.json."
        )

    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        state=state
    )
    flow.redirect_uri = redirect_uri
    return flow


def get_google_auth_url():
    flow = build_google_flow()
    state = generate_oauth_state()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return auth_url


def process_oauth_callback():
    auth_error = get_query_param("error")
    auth_code = get_query_param("code")
    request_state = get_query_param("state")

    if auth_error:
        clear_oauth_query_params()
        st.error(f"Login failed: {auth_error}")
        return

    if not auth_code:
        return

    if not is_valid_oauth_state(request_state):
        clear_oauth_query_params()
        st.error("Login failed: invalid OAuth state. Please try signing in again.")
        return

    try:
        flow = build_google_flow(state=request_state)
        flow.fetch_token(code=auth_code)
        creds = flow.credentials

        st.session_state["auth_token"] = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "scopes": creds.scopes,
        }

        user_email = "user@example.com"
        token_data = getattr(flow.oauth2session, "token", {}) or {}
        id_token = token_data.get("id_token")

        if id_token:
            try:
                decoded = jwt.decode(id_token, options={"verify_signature": False})
                user_email = decoded.get("email", user_email)
            except Exception as exc:
                st.warning(f"Could not decode ID token: {exc}")

        if user_email == "user@example.com":
            try:
                userinfo_response = requests.get(
                    "https://www.googleapis.com/oauth2/v2/userinfo",
                    headers={"Authorization": f"Bearer {creds.token}"},
                    timeout=10,
                )
                if userinfo_response.status_code == 200:
                    user_info = userinfo_response.json()
                    user_email = user_info.get("email", user_email)
                else:
                    st.error(
                        "Userinfo API returned status "
                        f"{userinfo_response.status_code}: {userinfo_response.text}"
                    )
            except Exception as exc:
                st.error(f"Exception calling userinfo API: {exc}")

        st.session_state["user_email"] = user_email
        clear_oauth_query_params()
        st.rerun()
    except Exception as exc:
        clear_oauth_query_params()
        st.error(f"Login failed: {exc}")


def logout():
    st.session_state["auth_token"] = None
    st.session_state["user_email"] = None
    clear_oauth_query_params()
    st.rerun()


# --- MAIN UI ---
process_oauth_callback()
st.title("⚡ Inbox Zero Agent")

# 1. LOGIN SCREEN
if not st.session_state["auth_token"]:
    st.info("Please sign in to access your secure agent.")
    col1, col2 = st.columns([1, 2])
    with col1:
        try:
            auth_url = get_google_auth_url()
            st.link_button("Sign in with Google", auth_url, type="primary")
        except Exception as exc:
            st.error(f"Unable to start login: {exc}")
            st.caption(
                "Configure GOOGLE_REDIRECT_URI or add a valid web redirect URI in "
                "frontend/credentials.json."
            )
    st.stop()

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
            payload = {
                "credentials": st.session_state["auth_token"],
                "max_results": max_emails
            }

            # Use the authenticated email as the per-user identifier for now.
            headers = {"x-user-id": st.session_state["user_email"]}

            response = requests.post(
                f"{BACKEND_URL}/agent/process",
                json=payload,
                headers=headers,
                timeout=60,
            )

            if response.status_code == 200:
                results = response.json()

                if not results:
                    st.success("Inbox is already Zero! 🎉")
                else:
                    df = pd.DataFrame(results)

                    c1, c2, c3 = st.columns(3)
                    c1.metric("Emails Processed", len(df))
                    c2.metric("Actions Found", len(df[df["category"] == "action"]))
                    c3.metric("Drafts Created", len(df[df["draft_id"].notnull()]))

                    st.dataframe(
                        df,
                        column_config={
                            "subject": "Subject",
                            "sender": "From",
                            "category": "Category",
                            "summary": st.column_config.TextColumn(
                                "Summary",
                                width="large"
                            ),
                            "draft_id": "Draft ID",
                            "calendar_status": "Calendar"
                        },
                        hide_index=True
                    )
            else:
                st.error(f"Backend Error ({response.status_code}): {response.text}")

        except requests.exceptions.ConnectionError:
            st.error("Could not connect to Backend. Is it running on port 8000?")
        except Exception as exc:
            st.error(f"An unexpected error occurred: {exc}")

# Footer
st.divider()
st.caption("Decoupled Architecture: Frontend (Streamlit) -> Backend (FastAPI)")
