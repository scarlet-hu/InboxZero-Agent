# Inbox Zero Agent

[![CI](https://github.com/scarlet-hu/InboxZero-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/scarlet-hu/InboxZero-Agent/actions/workflows/ci.yml)

> 🇨🇳 中文版：[Readme.md](Readme.md)

🚀 **Live demo:** https://inboxzero-frontend.fly.dev/  
> ⚠️ Backend uses Fly.io `auto_stop_machines = 'stop'` for zero-idle cost — the first request after an idle period takes ~5–6 seconds to wake the machine; subsequent requests are fast.

An intelligent email management system that uses AI to categorize, summarize, and draft responses for your Gmail inbox, with human review before sending.

## 🏗️ Architecture

```
┌──────────────────────┐         ┌──────────────────────────┐
│  Next.js (port 3000) │         │  FastAPI (port 8000)     │
│  - / login page      │ ──────▶ │  /auth/login → Google    │
│  - /dashboard        │ cookie  │  /auth/callback → JWT    │
│  - shadcn/ui + SWR   │ ◀────── │  /auth/demo-login        │
│                      │         │  /auth/me, /auth/logout  │
│                      │         │  /agent/process, /usage  │
│                      │         │  /agent/drafts/{id}      │
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

## 🔌 MCP Server

InboxZero exposes Gmail and Calendar tools as an **MCP server**, enabling direct use from Claude Desktop, Cursor, and any other MCP-compatible client — no FastAPI layer required.

![Claude Desktop using InboxZero MCP tools](mcp-use-claude.png)

```bash
# Connect to Claude Desktop — add to ~/Library/Application Support/Claude/claude_desktop_config.json
{
  "mcpServers": {
    "inboxzero": {
      "command": "/path/to/InboxZeroAgent/venv/bin/python",
      "args": ["/path/to/InboxZeroAgent/backend/mcp_server.py"]
    }
  }
}
```

**Available tools:** `list_unread_emails` · `check_calendar_conflicts` · `classify_email`

---

**Core Flow:**
1. **Fetch** → Retrieve unread emails via Gmail API
2. **Categorize** → LangGraph state-machine agent analyzes and classifies emails (action/fyi/spam)
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
- [x] **Human Review Interface (review-approve HITL)** - Next.js dashboard
  exposes four actions, each backed by a dedicated endpoint:
  - **View draft** — `GET /agent/drafts/{id}` — fetch draft body for editing
  - **Save edits** — `PUT /agent/drafts/{id}` — update subject/body while
    preserving `In-Reply-To` / `References` headers (keeps the reply threaded)
  - **Approve and send** — `POST /agent/drafts/{id}/send` — irreversible
  - **Discard** — `DELETE /agent/drafts/{id}` — drop the draft without sending

  The agent runs to completion in `no-auto-send` mode (drafts land in Gmail
  Drafts); the dashboard proxies every human action to the Gmail API.
  This is *not* strict workflow-interrupt HITL — see
  [docs/hitl-strong-design.md](docs/hitl-strong-design.md) for the planned
  `LangGraph interrupt + checkpointer` variant where the workflow itself
  pauses mid-graph.
- [x] **Usage Tracking** - Per-user email processing limits
- [x] **LangGraph State-Machine Agent** - Typed `AgentState` + conditional routing pipeline (see [docs/react-vs-state-machine.md](docs/react-vs-state-machine.md) for why this won over a ReAct alternative)

### 🐞 Known Issues

- [ ] **MCP server is decoupled from the web login flow** —
  `backend/mcp_server.py:_load_creds()` reads `token.json` from the project
  root, but the current web login flow writes credentials into a JWT
  session cookie and **does not produce `token.json`**. MCP clients
  (Claude Desktop / Cursor) therefore need a separate one-off OAuth bootstrap
  to create `token.json`, otherwise they hit `FileNotFoundError`.
  Planned fix: share FastAPI session auth, or write `token.json` after
  a successful login as a side effect.
- [ ] **bare-except in `agent_core.py`** — the categorize node uses
  `except Exception` to silently masquerade Gemini 429 / JSON-parse errors as
  a `category="fyi"` fallback. The eval runner detects this via a
  `"Error parsing:"` summary prefix (which keeps eval results honest), but
  the underlying bug still lives in production code. Planned replacement:
  specific exceptions + `tenacity` exponential backoff + a 30s LLM timeout.

### 🚧 Roadmap

**P1**

- [ ] **LangSmith / Langfuse observability** — add tracing + token-cost
  tracking; replace `print` debugging with structured logs.
- [ ] **PostgreSQL persistence** — SQLAlchemy + Alembic; tables: `users`,
  `processed_emails` (dedup), `usage_log` (replaces the mock
  `check_usage_limit` in `endpoints.py:14`), `feedback` (user edits to drafts).
- [ ] **Async batch processing** — `endpoints.py:55` is a serial `for` loop
  today; switch to `asyncio.gather` or LangGraph's batch API to cut latency
  on long inboxes.
- [ ] **Structured error handling** — see the Known Issues above; add a 30s
  LLM timeout.

**P2**

- [ ] **Feedback loop / self-improving** — use user-edited drafts as
  in-context few-shot examples to lift downstream draft acceptance rate.
- [ ] **RAG over email history** — pgvector for semantic retrieval of past
  similar emails when drafting replies.
- [ ] **Strong HITL** — adopt `LangGraph interrupt + checkpointer` so the
  workflow itself **pauses** on low-confidence classifications and only
  drafts after a human confirms. Full design in
  [docs/hitl-strong-design.md](docs/hitl-strong-design.md).

### 🧹 Cleanup

- [ ] Remove the unused `langchain-anthropic` from `requirements.txt`
- [ ] Upgrade `requirements.txt` to `pyproject.toml` + lock file (uv / poetry)
- [ ] Promote the ASCII architecture diagram to mermaid
- [ ] Audit git history to confirm `token.json` never landed in a commit
  (`.gitignore` already covers it, but history needs verification)

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
│   │       ├── agent_core.py    # LangGraph state-machine agent (production)
│   │       ├── agent_core_react.py  # ReAct alternative — see docs/react-vs-state-machine.md
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

### LangGraph State-Machine Agent

The agent is a deterministic state machine — classification routes each email
through a fixed graph rather than letting the LLM choose tools at runtime.
A ReAct alternative (`agent_core_react.py`) was prototyped and benchmarked;
see [docs/react-vs-state-machine.md](docs/react-vs-state-machine.md) for the
token-cost data and rationale for keeping the state machine in production.

Nodes and state:

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
1. categorize_logic     → Analyze and classify the email with Gemini LLM
2. calendar_check_logic → Check for scheduling conflicts (action only)
3. draft_reply_logic    → Generate draft and push to Gmail Drafts (action only)
```

**Decision Flow:**
- `spam`   → Straight to `END` (no archive — user handles it in Gmail)
- `fyi`    → Straight to `END` (user handles it in Gmail)
- `action` → `check_calendar` → `draft_reply` → `END`

### API Endpoints

> **Auth:** all `/agent/*` endpoints depend on the `session` cookie (a JWT set
> by `/auth/callback` after a successful login; `HttpOnly` + `SameSite=None`
> for cross-domain production). The backend decodes it automatically via the
> `get_current_session` FastAPI dependency — no header or body field carries
> credentials. Unauthenticated requests return 401.

#### `POST /agent/process`
Run the full LangGraph pipeline over unread Gmail emails.

**Request Body:**
```json
{
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
Get the user's daily processing limit.

#### Draft Review Endpoints (review-approve HITL)

Four endpoints, one per dashboard action (view / edit / send / discard).
Gmail API errors are mapped to HTTP status codes uniformly:
**404 → draft not found; 401/403 → Gmail rejected the request; otherwise → 502**.

##### `GET /agent/drafts/{draft_id}`
Read the editable fields of a draft.

**Response:**
```json
{
  "draft_id": "r-123456789",
  "to": "colleague@company.com",
  "subject": "Re: Project Meeting Request",
  "body": "Hi, ..."
}
```

##### `PUT /agent/drafts/{draft_id}`
Save edits to a draft (**does not send**). The update preserves the original
`In-Reply-To` / `References` headers so the reply stays in the right thread.

**Request Body:**
```json
{
  "subject": "Re: Project Meeting Request",
  "body": "Hi, thanks for your message..."
}
```

**Response:** same shape as `GET /agent/drafts/{draft_id}` (returns the
saved state).

##### `POST /agent/drafts/{draft_id}/send`
**Irreversible**: send the draft through the Gmail API.

**Response:** `204 No Content`.

##### `DELETE /agent/drafts/{draft_id}`
Discard the draft (deleted from Gmail Drafts) without sending.

**Response:** `204 No Content`.

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
