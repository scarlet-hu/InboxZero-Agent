# Inbox Zero Agent (Human-in-the-Loop)

[![CI](https://github.com/scarlet-hu/InboxZero-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/scarlet-hu/InboxZero-Agent/actions/workflows/ci.yml)

An intelligent email management system that uses AI to categorize, summarize, and draft responses for your Gmail inbox, with human review before sending.

## 🏗️ Architecture

```
┌──────────────────────┐         ┌──────────────────────────┐
│  Next.js (port 3000) │         │  FastAPI (port 8000)     │
│  - / login page      │ ──────▶ │  /auth/login → Google    │
│  - /dashboard        │ cookie  │  /auth/callback → JWT    │
│  - shadcn/ui + SWR   │ ◀────── │  /auth/me, /auth/logout  │
│                      │         │  /agent/process, /usage  │
└──────────────────────┘         └──────────┬───────────────┘
                                            │
                                            ▼
                                  ┌──────────────────────┐
                                  │  LangGraph agent     │
                                  │  categorize → check  │
                                  │  calendar → draft    │
                                  └──────────┬───────────┘
                                             │
                                             ▼
                                  ┌──────────────────────┐
                                  │  Gmail / Calendar    │
                                  │  / Gemini APIs       │
                                  └──────────────────────┘
```

**Core Flow:**
1. **Fetch** → Retrieve unread emails via Gmail API
2. **Categorize** → ReAct Agent analyzes and classifies emails (action/fyi/spam)
3. **Context** → Calendar API checks for scheduling conflicts
4. **Draft** → AI generates response drafts for actionable emails
5. **Review** → Human approves, edits, or discards drafts
6. **Send** → Approved emails sent through Gmail API

## 🛠️ Tech Stack

### Backend
- **FastAPI** - High-performance REST API framework
- **LangGraph** - Workflow orchestration for AI agents
- **LangChain** - LLM integration and prompt management
- **Google Gemini 2.5 Flash** - AI language model (via `langchain-google-genai`)
- **Gmail API** - Email fetching and draft management
- **Calendar API** - Scheduling conflict detection
- **Python 3.x** - Core language

### Frontend
- **Next.js 16** (App Router, TypeScript)
- **Tailwind CSS v4** + **shadcn/ui** components
- **SWR** for client-side data fetching

### Authentication
- **OAuth 2.0** - Google authentication flow
- **google-auth-oauthlib** - OAuth client library

### Development
- **Uvicorn** - ASGI server
- **python-dotenv** - Environment variable management

## ✨ Key Features

### ✅ Implemented
- [x] **Multi-User Authentication** - OAuth 2.0 Google login with user isolation
- [x] **Email Categorization** - AI-powered classification:
  - `action` - Requires email response (direct questions, meeting requests, tasks)
  - `fyi` - Informational only (automated emails, notifications, receipts)
  - `spam` - Unwanted/irrelevant emails
- [x] **Smart Summarization** - Concise AI-generated email summaries
- [x] **Calendar Integration** - Automatic scheduling conflict detection
- [x] **Draft Generation** - AI-drafted responses for action items
- [x] **Human Review Interface** - Next.js dashboard for approving/editing drafts
- [x] **Usage Tracking** - Per-user email processing limits
- [x] **ReAct Agent Workflow** - State-based email processing pipeline

### 🚧 Work in Progress (WIP)
- [ ] **Auto-send Mode** - Option to send low-risk emails without review
- [ ] **Custom Categories** - User-defined email classification rules
- [ ] **Response Templates** - Reusable reply templates
- [ ] **Email Threading** - Conversation context for better drafts
- [ ] **Database Integration** - Persistent usage tracking and history
- [ ] **Batch Processing** - Queue management for large inboxes
- [ ] **Analytics Dashboard** - Email processing statistics
- [ ] **Multi-language Support** - Non-English email handling
- [ ] **GCP Deployment** - Production deployment on Google Cloud Platform

### 📋 Backlog/To-Do
- [ ] **Priority Scoring** - Urgent email detection
- [ ] **Attachment Handling** - Parse and respond to attachments
- [ ] **Meeting Scheduler** - Propose meeting times based on availability
- [ ] **Email Search** - Search through processed emails
- [ ] **Webhooks** - Real-time email processing triggers
- [ ] **Browser Extension** - Quick actions from Gmail UI
- [ ] **Mobile App** - iOS/Android review interface
- [ ] **Team Mode** - Shared inbox management

## 📁 Project Structure

```
InboxZeroAgent/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app entry point + CORS
│   │   ├── models.py            # Pydantic data models
│   │   ├── api/
│   │   │   ├── auth.py          # /auth/login, /callback, /me, /logout
│   │   │   └── endpoints.py     # /agent/process, /agent/usage
│   │   └── services/
│   │       ├── auth.py          # OAuth flow, PKCE, JWT session
│   │       ├── agent_core.py    # LangGraph ReAct agent
│   │       └── google_utils.py  # Gmail/Calendar API wrappers
│   ├── credentials.json         # Google OAuth client secrets
│   └── requirements.txt
├── web/                         # Next.js 16 + Tailwind + shadcn/ui
│   ├── src/app/                 #   /, /dashboard
│   ├── src/components/ui/       #   shadcn primitives
│   └── src/lib/                 #   api.ts, useUser.ts
├── eval/                        # Offline categorization eval harness
├── tests/                       # pytest (backend)
├── Dockerfile.backend
├── web/Dockerfile               # Next.js multi-stage image
├── docker-compose.yml
└── Readme.md                    # This file
```

## 🚀 Getting Started

### Prerequisites
- Python 3.8+
- Google Cloud Project with Gmail & Calendar APIs enabled
- OAuth 2.0 credentials (`credentials.json`)

### Installation

1. **Clone the repository**
   ```bash
   git clone <repo-url>
   cd InboxZeroAgent
   ```

2. **Set up virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

4. **Configure environment variables**
   Create a `.env` file in the `backend/` directory:
   ```env
   GOOGLE_API_KEY=your_gemini_api_key_here
   GOOGLE_CLIENT_ID=your_google_oauth_client_id
   GOOGLE_CLIENT_SECRET=your_google_oauth_client_secret
   ```

   The OAuth callback runs on the backend, so the redirect URI in your
   Google Cloud Console must point at FastAPI:
   ```
   http://localhost:8000/auth/callback
   ```
   Add the same URI to the `redirect_uris` list in `backend/credentials.json`.

5. **Add Google OAuth credentials**
   - Download `credentials.json` from [Google Cloud Console](https://console.cloud.google.com/) and place it at `backend/credentials.json`.

### Running the Application

**Option A — Docker Compose (recommended)**

```bash
docker compose up --build
```

- Backend: `http://localhost:8000` (Swagger at `/docs`)
- Frontend: `http://localhost:3000`

**Option B — Local dev (two terminals)**

Terminal 1 — backend:
```bash
cd backend && uvicorn app.main:app --reload
```

Terminal 2 — frontend:
```bash
cd web && npm install && npm run dev
```

**Login flow**
1. Open `http://localhost:3000` and click "Sign in with Google"
2. Authorize Gmail + Calendar access
3. Land on `/dashboard`
4. Pick max emails to process and click "Run Agent"
5. Review the categorized results / drafts

## 🧠 How It Works

### ReAct Agent Workflow (LangGraph)

The agent uses a state machine with the following nodes:

```python
State: AgentState
├── email_id: str
├── sender: str
├── subject: str
├── email_content: str
├── category: "spam" | "fyi" | "action"
├── summary: str
├── calendar_status: Optional[str]
└── draft_id: Optional[str]

Nodes:
1. categorize_logic    → Analyze email with Gemini LLM
2. calendar_check_logic → Check for scheduling conflicts
3. draft_reply_logic   → Generate response for "action" emails
4. archive_logic       → Mark "fyi" emails as read
```

**Decision Flow:**
- `spam` → Archive immediately
- `fyi` → Summarize + Archive
- `action` → Summarize + Calendar Check + Draft Response

### API Endpoints

#### `POST /agent/process`
Process unread emails from Gmail inbox.

**Headers:**
- `X-User-Id`: User identifier

**Request Body:**
```json
{
  "credentials": "<base64_oauth_token>",
  "max_results": 10
}
```

**Response:**
```json
[
  {
    "subject": "Project Meeting Request",
    "sender": "colleague@company.com",
    "category": "action",
    "summary": "Requests meeting to discuss Q1 roadmap",
    "draft_id": "r-123456789",
    "calendar_status": "Available Tuesday 2-3pm"
  }
]
```

#### `GET /agent/usage`
Get user's daily processing limits.

## 🧪 Evaluation

Categorization quality is measured against a labeled dataset of 30 emails
(10 action / 15 fyi / 5 spam) covering common edge cases like automated alerts
that say "action required" and gift-card / phishing scams.

```bash
set -a && source backend/.env && set +a
python eval/run_eval.py
```

Reports (per-category P/R/F1, confusion matrix, latency p50/p95, and a
misclassifications table) are written to `eval/results/`. See
[`eval/Readme.md`](eval/Readme.md) for the full workflow, including how to
A/B-test prompt changes with `--tag`.

## 🔐 Security Notes

- OAuth tokens stored locally in `token.json`
- Never commit `credentials.json` or `.env` files
- Use environment variables for API keys
- Review all drafts before sending (human-in-the-loop)

## 📊 Future Enhancements

- **Vector Database** - Semantic email search with embeddings
- **Fine-tuned Models** - Custom email classification models
- **A/B Testing** - Compare draft quality across LLMs
- **Enterprise Features** - SSO, admin console, audit logs

## 🤝 Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Submit a pull request with tests

## 📄 License

MIT License

Copyright (c) 2026 Scarlett Hu

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.


## 📞 Support

For issues or questions, please open a GitHub issue.

---

**Status:** Alpha - Active Development 🚧
