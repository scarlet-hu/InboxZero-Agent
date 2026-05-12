# Inbox Zero Agent

[![CI](https://github.com/scarlet-hu/InboxZero-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/scarlet-hu/InboxZero-Agent/actions/workflows/ci.yml)

> En: [Readme.en.md](Readme.en.md)

🚀 **在线演示：** https://inboxzero-frontend.fly.dev/
> ⚠️ Backend 配置了 Fly.io `auto_stop_machines = 'stop'` 实现闲置零成本——空闲一段时间后的第一个请求会花 ~5–6 秒唤醒机器，后续请求恢复正常速度。

InboxZero 是一个智能邮件管理系统，用 AI 对 Gmail 收件箱里的邮件做分类、摘要和草稿生成，**所有草稿在发送前都需要人工审核**。

## 🏗️ 整体架构

```
┌──────────────────────┐         ┌──────────────────────────┐
│  Next.js (port 3000) │         │  FastAPI (port 8000)     │
│  - / 登录页          │ ──────▶ │  /auth/login → Google    │
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

InboxZero 把 Gmail 和 Calendar 工具以 **MCP server** 的形式暴露出来，
Claude Desktop、Cursor 等任意 MCP 兼容客户端都能直接调用——**不需要走 FastAPI 层**。

![Claude Desktop 调用 InboxZero MCP 工具](mcp-use-claude.png)

```bash
# 接入 Claude Desktop —— 加到 ~/Library/Application Support/Claude/claude_desktop_config.json
{
  "mcpServers": {
    "inboxzero": {
      "command": "/path/to/InboxZeroAgent/venv/bin/python",
      "args": ["/path/to/InboxZeroAgent/backend/mcp_server.py"]
    }
  }
}
```

**已暴露的工具：** `list_unread_emails` · `check_calendar_conflicts` · `classify_email`

---

**核心流程：**
1. **Fetch** → 通过 Gmail API 拉取未读邮件
2. **Categorize** → LangGraph 状态机 agent 分析并分类（action / fyi / spam）
3. **Context** → Calendar API 检查日程冲突
4. **Draft** → 为 action 邮件生成回复草稿
5. **Review** → 人工审批、编辑或丢弃草稿
6. **Send** → 经批准的邮件通过 Gmail API 发出

## 🛠️ 技术栈

### 后端
- **FastAPI** —— 高性能 REST API 框架
- **LangGraph** —— AI agent 工作流编排
- **LangChain** —— LLM 接入与 prompt 管理
- **Google Gemini 2.5 Flash** —— AI 语言模型（通过 `langchain-google-genai`）
- **Gmail API** —— 邮件拉取与草稿管理
- **Calendar API** —— 日程冲突检测
- **Python 3.x** —— 主语言

### 前端
- **Next.js 16**（App Router、TypeScript）
- **Tailwind CSS v4** + **shadcn/ui** 组件
- **SWR** —— 客户端数据获取

### 认证
- **OAuth 2.0** —— Google 认证流程
- **google-auth-oauthlib** —— OAuth 客户端库

### 开发
- **Uvicorn** —— ASGI 服务器
- **python-dotenv** —— 环境变量管理

## ✨ 核心功能

### ✅ 已实现
- [x] **多用户认证** —— OAuth 2.0 Google 登录 + 用户隔离
- [x] **邮件分类** —— AI 驱动的三分类：
  - `action` —— 需要邮件回复（直接提问、会议请求、任务分派）
  - `fyi` —— 仅供参考（自动化邮件、通知、收据）
  - `spam` —— 垃圾或无关邮件
- [x] **智能摘要** —— AI 生成的简洁邮件摘要
- [x] **日历集成** —— 自动检测日程冲突
- [x] **草稿生成** —— 为 action 邮件起草回复
- [x] **人工审核界面（review-approve HITL）** —— Next.js 看板提供 4 个操作，
  分别对应后端 4 个端点：
  - **查看草稿内容**：`GET /agent/drafts/{id}` —— 拉取草稿正文供编辑
  - **编辑后保存**：`PUT /agent/drafts/{id}` —— 改 subject/body，保留 In-Reply-To / References 线程头
  - **批准发送**：`POST /agent/drafts/{id}/send` —— 通过 Gmail API 发出（不可逆）
  - **丢弃草稿**：`DELETE /agent/drafts/{id}` —— 删掉草稿，不发送

  Agent 跑完整个流程并使用 `no-auto-send` 模式（草稿落进 Gmail Drafts），
  看板把所有人工操作代理到 Gmail API。这**不是**严格意义上的
  workflow-interrupt HITL —— 规划中的 `LangGraph interrupt + checkpointer`
  变体（工作流本身在图中暂停）见 [docs/hitl-strong-design.md](docs/hitl-strong-design.md)。
- [x] **用量追踪** —— 每用户邮件处理限额
- [x] **LangGraph 状态机 Agent** —— 类型化 `AgentState` + 条件路由
  （为什么选状态机而不是 ReAct，详见 [docs/react-vs-state-machine.md](docs/react-vs-state-machine.md)）

### 🐞 已知问题（Known Issues）

- [ ] **MCP server 与 web 登录流脱节** —— `backend/mcp_server.py:_load_creds()`
  从项目根目录读取 `token.json`，但当前 web 登录把凭据写进 JWT session cookie，
  **不会生成 `token.json`**。MCP 客户端（Claude Desktop / Cursor）现在用前需要
  手动跑一遍 OAuth 流程生成 `token.json`，否则 `FileNotFoundError`。
  根治方向：MCP server 共用 FastAPI 的 session 鉴权，或在登录成功后同步导出
  一份 `token.json`。
- [ ] **`agent_core.py` 里的 bare-except** —— 分类节点用 `except Exception` 把
  Gemini API 429 / JSON 解析错误静默伪装成 `category="fyi"` fallback。
  Eval runner 通过 `"Error parsing:"` summary 前缀检测出来（保住了评估可信度），
  但底层 bug 还在生产代码里。计划用具体异常 + `tenacity` 指数退避重试 + 30s 超时替代。

### 🚧 路线图（Roadmap）

**P1**

- [ ] **LangSmith / Langfuse 可观测性** —— 接入 trace + token 成本追踪，
  把 print 调试替换成结构化日志
- [ ] **PostgreSQL 持久化** —— SQLAlchemy + Alembic；表：`users`、
  `processed_emails`（去重防重复处理）、`usage_log`（取代 `endpoints.py:14`
  的 mock `check_usage_limit`）、`feedback`（用户对草稿的修改）
- [ ] **批处理 + async** —— `endpoints.py:55` 现在是串行 for 循环，
  改成 `asyncio.gather` 或 LangGraph batch API，减少长收件箱延迟
- [ ] **结构化错误处理** —— 见上方已知问题；加 LLM 30s 超时

**P2**

- [ ] **Feedback loop / self-improving** —— 用户编辑过的草稿作为 in-context
  few-shot examples，提升后续草稿采纳率
- [ ] **RAG over email history** —— pgvector 做语义搜索，草稿生成时检索
  历史相似邮件
- [ ] **Strong HITL** —— 用 `LangGraph interrupt + checkpointer` 让工作流
  在分类置信度低的邮件上**真正暂停**，等用户确认后才生成草稿；
  完整设计见 [docs/hitl-strong-design.md](docs/hitl-strong-design.md)

### 🧹 清理项（Cleanup）

- [ ] 删掉 `requirements.txt` 里没用的 `langchain-anthropic`
- [ ] `requirements.txt` 升级成 `pyproject.toml` + lock 文件（uv / poetry）
- [ ] 架构图升级成 mermaid（现在是 ASCII）
- [ ] 确认 `token.json` 从未进过 git 历史（`.gitignore` 已加，但 history 需要核对）

## 📁 项目结构

```
InboxZeroAgent/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口 + CORS
│   │   ├── models.py            # Pydantic 数据模型
│   │   ├── api/
│   │   │   ├── auth.py          # /auth/login, /callback, /me, /logout
│   │   │   └── endpoints.py     # /agent/process, /agent/usage
│   │   └── services/
│   │       ├── auth.py          # OAuth 流程、PKCE、JWT session
│   │       ├── agent_core.py    # LangGraph 状态机 agent（生产路径）
│   │       ├── agent_core_react.py  # ReAct 替代版 —— 详见 docs/react-vs-state-machine.md
│   │       └── google_utils.py  # Gmail / Calendar API 封装
│   ├── credentials.json         # Google OAuth client secrets
│   └── requirements.txt
├── web/                         # Next.js 16 + Tailwind + shadcn/ui
│   ├── src/app/                 #   /, /dashboard
│   ├── src/components/ui/       #   shadcn primitives
│   └── src/lib/                 #   api.ts, useUser.ts
├── eval/                        # 离线分类评估框架
├── tests/                       # pytest（后端）
├── Dockerfile.backend
├── web/Dockerfile               # Next.js 多阶段镜像
├── docker-compose.yml
└── Readme.md                    # 本文件
```

## 🚀 快速开始

### 前置依赖
- Python 3.8+
- 启用了 Gmail & Calendar API 的 Google Cloud 项目
- OAuth 2.0 凭据（`credentials.json`）

### 安装

1. **克隆仓库**
   ```bash
   git clone <repo-url>
   cd InboxZeroAgent
   ```

2. **创建虚拟环境**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   ```

3. **安装依赖**
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

4. **配置环境变量**
   在 `backend/` 目录下创建 `.env`：
   ```env
   GOOGLE_API_KEY=your_gemini_api_key_here
   GOOGLE_CLIENT_ID=your_google_oauth_client_id
   GOOGLE_CLIENT_SECRET=your_google_oauth_client_secret
   ```

   OAuth callback 走后端，所以 Google Cloud Console 里的 redirect URI 必须指向 FastAPI：
   ```
   http://localhost:8000/auth/callback
   ```
   把这个 URI 同时加到 `backend/credentials.json` 的 `redirect_uris` 列表里。

5. **加入 Google OAuth 凭据**
   - 从 [Google Cloud Console](https://console.cloud.google.com/) 下载 `credentials.json`，
     放到 `backend/credentials.json`。

### 运行应用

**方式 A —— Docker Compose（推荐）**

```bash
docker compose up --build
```

- 后端：`http://localhost:8000`（Swagger 在 `/docs`）
- 前端：`http://localhost:3000`

**方式 B —— 本地开发（两个终端）**

终端 1 —— 后端：
```bash
cd backend && uvicorn app.main:app --reload
```

终端 2 —— 前端：
```bash
cd web && npm install && npm run dev
```

**登录流程**
1. 打开 `http://localhost:3000`，点击 "Sign in with Google"
2. 授权 Gmail + Calendar 权限
3. 跳转到 `/dashboard`
4. 选择要处理的邮件数量，点击 "Run Agent"
5. 审核分类结果 / 草稿

## 🧠 工作原理

### LangGraph 状态机 Agent

agent 是一个**确定性状态机**——分类结果决定每封邮件走哪条固定路径，
而不是让 LLM 在运行时自己选工具。曾经实现过 ReAct 替代版（`agent_core_react.py`）
并做了 benchmark，token 成本数据和"为什么生产版保留状态机"的分析
详见 [docs/react-vs-state-machine.md](docs/react-vs-state-machine.md)。

节点与状态：

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
1. categorize_logic     → 用 Gemini LLM 分析邮件并分类
2. calendar_check_logic → 检查日程冲突（仅 action 走这里）
3. draft_reply_logic    → 生成草稿并 push 到 Gmail Drafts（仅 action 走这里）
```

**决策流程：**
- `spam`   → 直接结束（END），不归档（用户在 Gmail 自己处理）
- `fyi`    → 直接结束（END），用户在 Gmail 自己处理
- `action` → `check_calendar` → `draft_reply` → END

### API 端点

> **鉴权方式：** 所有 `/agent/*` 端点都依赖 `session` cookie（JWT，由
> `/auth/callback` 在登录成功后写入；`HttpOnly` + `SameSite=None` for 生产跨域）。
> 后端通过 `get_current_session` FastAPI dependency 自动解码 cookie，
> 不需要任何额外的 header 或请求体字段携带凭据。未登录时返回 401。

#### `POST /agent/process`
处理 Gmail 收件箱中的未读邮件，跑完整 LangGraph 流程。

**Request Body：**
```json
{
  "max_results": 10
}
```

**Response：**
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
获取用户的每日处理限额。

#### 草稿审核端点（review-approve HITL）

四个端点对应看板上的「查看 / 编辑 / 发送 / 丢弃」四个操作。
Gmail API 的错误统一映射成 HTTP 状态码：
**404 → 草稿不存在；401/403 → Gmail 拒绝；其他 → 502**。

##### `GET /agent/drafts/{draft_id}`
读取一封草稿的可编辑字段。

**Response：**
```json
{
  "draft_id": "r-123456789",
  "to": "colleague@company.com",
  "subject": "Re: Project Meeting Request",
  "body": "Hi, ..."
}
```

##### `PUT /agent/drafts/{draft_id}`
保存对草稿的编辑（**不发送**）。更新时保留原草稿的
`In-Reply-To` / `References` 头，保证回复仍然挂在原线程上。

**Request Body：**
```json
{
  "subject": "Re: Project Meeting Request",
  "body": "Hi, thanks for your message..."
}
```

**Response：** 同 `GET /agent/drafts/{draft_id}`（返回保存后的最新内容）。

##### `POST /agent/drafts/{draft_id}/send`
**不可逆**：通过 Gmail API 真正发送草稿。

**Response：** `204 No Content`。

##### `DELETE /agent/drafts/{draft_id}`
丢弃草稿（在 Gmail 草稿箱里删掉），不发送。

**Response：** `204 No Content`。

## 🧪 评估

分类质量在一个 30 条人工标注的数据集（10 action / 15 fyi / 5 spam）上评估，
覆盖了常见边缘 case，比如**自称 "action required" 的自动化告警**、
**礼品卡 / 钓鱼诈骗** 等。

```bash
set -a && source backend/.env && set +a
python eval/run_eval.py
```

报告（按类别 P/R/F1、混淆矩阵、延迟 p50/p95、错分清单）会写入 `eval/results/`。
完整流程（包括如何用 `--tag` 做 A/B prompt 测试）见 [`eval/Readme.md`](eval/Readme.md)。

## 🔐 安全注意事项

- OAuth token 本地存储在 `token.json`
- **绝对不要 commit** `credentials.json` 或 `.env`
- API key 用环境变量管理
- 所有草稿在发送前都要人工审核（human-in-the-loop）

## 📄 许可证

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


## 📞 支持

有问题请在 GitHub 上开 issue。

---

**状态：** Alpha —— 持续开发中 🚧
