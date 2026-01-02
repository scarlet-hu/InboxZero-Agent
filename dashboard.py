import streamlit as st
import pandas as pd
from main_v1 import get_google_services, fetch_unread_emails, agent_app

# Set page config for a professional command-center look
st.set_page_config(
    page_title="Inbox Zero Agent",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for modern UI feel
st.markdown("""
    <style>
    .main {
        background-color: #f8f9fa;
    }
    .stMetric {
        background-color: white;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    div[data-testid="stExpander"] {
        border: none;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        background-color: white;
        margin-bottom: 10px;
    }
    </style>
    """, unsafe_allow_html=True)

st.title("🤖 Inbox Zero Executive Agent")
st.markdown("Automated email intelligence and calendar-aware drafting.")

# Sidebar for controls
with st.sidebar:
    st.header("Control Panel")
    max_emails = st.slider("Emails to fetch", 1, 50, 10)
    
    col1, col2 = st.columns(2)
    with col1:
        run_agent = st.button("🚀 Run Agent", width='stretch')
    with col2:
        clear = st.button("🗑️ Clear", width='stretch')

    if clear:
        if 'results' in st.session_state:
            del st.session_state['results']
        st.rerun()

    st.divider()
    st.info("""
    **Workflow:**
    1. Fetches unread emails.
    2. Categorizes (Action/FYI/Spam).
    3. Action items trigger Calendar checks.
    4. Smart drafts are created in Gmail.
    """)

if run_agent:
    with st.status("Working through your inbox...", expanded=True) as status:
        try:
            st.write("🔌 Connecting to Google Services...")
            gmail_service, _ = get_google_services()
            
            st.write("📩 Fetching unread emails...")
            emails = fetch_unread_emails(gmail_service, max_results=max_emails)
            
            if not emails:
                st.success("Inbox is already Zero! 🎉")
            else:
                results_data = []
                
                for i, email in enumerate(emails):
                    st.write(f"🧐 Processing ({i+1}/{len(emails)}): **{email['subject'][:50]}...**")
                    # Run the LangGraph Agent
                    result = agent_app.invoke(email)
                    
                    results_data.append({
                        "From": result['sender'],
                        "Subject": result['subject'],
                        "Category": result['category'].upper(),
                        "Summary": result['summary'],
                        "Calendar Status": result['calendar_status'] or "N/A",
                        "Draft Created": "✅ Yes" if result['draft_id'] else "❌ No",
                        "Draft ID": result['draft_id'] or "None"
                    })
                
                st.session_state['results'] = results_data
                status.update(label="Inbound processing complete!", state="complete", expanded=False)

        except Exception as e:
            st.error(f"Error during execution: {e}")

# Display Results with Metrics
if 'results' in st.session_state and st.session_state['results']:
    df = pd.DataFrame(st.session_state['results'])
    
    # Dashboard Metrics Row
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Scanned", len(df))
    m2.metric("Actions Found", len(df[df['Category'] == 'ACTION']))
    m3.metric("FYI / Updates", len(df[df['Category'] == 'FYI']))
    m4.metric("Drafts Saved", len(df[df['Draft Created'] == '✅ Yes']))

    st.subheader("📬 Processing Log")
    
    # Interactive Dataframe with Column Configuration
    st.dataframe(
        df,
        column_config={
            "From": st.column_config.TextColumn("Sender"),
            "Category": st.column_config.TextColumn("Type"),
            "Calendar Status": st.column_config.TextColumn("Availability"),
            "Draft Created": st.column_config.TextColumn("Draft Status"),
            "Summary": st.column_config.TextColumn("AI Summary", width="large"),
            "Draft ID": None # Hide technical IDs by default
        },
        hide_index=True,
        width='stretch'
    )
    
    st.success("💡 **Next Step:** Open your Gmail 'Drafts' folder to review and send the generated replies.")
else:
    if not run_agent:
        st.info("👋 Welcome! Click **Run Agent** in the sidebar to scan your unread emails and generate smart drafts.")

# Footer
st.divider()
st.caption("Personalized Executive Agent Engine v1.0.1")