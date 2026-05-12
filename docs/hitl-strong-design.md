# 强 HITL 设计方案（规划中）

> **状态：仅设计，未实现。** 当前生产环境采用主 Readme 描述的
> review-approve HITL 模式：agent 跑完整个流程，草稿落进 Gmail Drafts（不自动发送），
> 用户在看板上批准 / 编辑 / 丢弃每个草稿。**agent 工作流本身不会在图中暂停。**
>
> 本文档描述一个更强的 HITL 变体——通过 `interrupt()` 让 LangGraph 工作流暂停，
> 用 checkpointer 持久化中间状态，等用户提交决策后再恢复执行。
> 这里把它记为"规划中但延后"的升级方向。

## 为什么强 HITL 不同

当前实现是 "human-on-the-loop"：自动化先跑完，然后人审核产物。
**强 HITL** 是工作流在决策点**主动停下来**，把相关上下文暴露给用户，
拿到人工输入后才继续执行。LangGraph 的标准原语就是 `langgraph.types.interrupt()`
配合一个 checkpointer（用来在暂停期间持久化状态）。

为什么这对 InboxZero 有意义：

- 现在 agent 一定会跑到 `END` 并生成草稿，**即使 LLM 对分类不太确定的边缘 case 也照生成**。
  强 HITL 让 agent 可以在分类不确定时**先停下来等人确认**，再决定是否进入草稿生成。
- 有状态工作流意味着看板可以展示 agent 暂停前积累的**完整推理 trace**，而不仅仅是最终草稿。
- 支持更丰富的人工介入——例如用户可以修正分类（"这是 action，不是 fyi"），
  让 agent 基于修正后的状态**重新规划下游节点**。

## 架构概览

```
                          ┌──── interrupt() ────┐
                          ▼                     │
START → categorize → check_calendar → draft_reply → review_node
                                                       │
                                                       ▼
                                              execute_decision → END
                                          (send / edit+send / discard)
```

`review_node` 调用 `interrupt({...})`，把草稿预览和完整 agent 状态作为参数传出。
图随即挂起，checkpointer 以 `thread_id` 为键持久化当前 `AgentState`。
后续调用 `invoke(Command(resume=user_decision), config={"thread_id": ...})`
会从保存的 checkpoint 恢复执行，把 `execute_decision` 跑到完成。

## State 扩展

```python
class AgentState(TypedDict):
    # 现有字段
    email_id: str
    sender: str
    subject: str
    email_content: str
    category: Literal["spam", "fyi", "action"]
    summary: str
    calendar_status: Optional[str]
    draft_id: Optional[str]
    # 强 HITL 新增字段
    user_decision: Optional[dict]   # 由 Command(resume=...) 填入
    final_status: Optional[str]     # "sent" | "sent_edited" | "discarded"
```

## 新节点

```python
from langgraph.types import interrupt, Command

def review_node(state: AgentState):
    """暂停执行，把草稿暴露出来等人审核。"""
    decision = interrupt({
        "kind": "review_draft",
        "email_id": state["email_id"],
        "subject": state["subject"],
        "category": state["category"],
        "summary": state["summary"],
        "calendar_status": state["calendar_status"],
        "draft_id": state["draft_id"],
        "draft_preview": fetch_draft_content(state["draft_id"]),
    })
    return {"user_decision": decision}

def execute_decision_node(state, gmail_service):
    d = state["user_decision"]
    if d["action"] == "approve":
        gmail_service.users().drafts().send(
            userId="me", body={"id": state["draft_id"]}
        ).execute()
        return {"final_status": "sent"}
    if d["action"] == "edit_and_send":
        update_draft_content(state["draft_id"], d["subject"], d["body"])
        gmail_service.users().drafts().send(
            userId="me", body={"id": state["draft_id"]}
        ).execute()
        return {"final_status": "sent_edited"}
    # discard
    gmail_service.users().drafts().delete(
        userId="me", id=state["draft_id"]
    ).execute()
    return {"final_status": "discarded"}
```

## 路由变化

action 类邮件路由到 `review_node` 而不是直接到 `END`：

```python
workflow.add_edge("draft_reply", "review_node")
workflow.add_edge("review_node", "execute_decision")
workflow.add_edge("execute_decision", END)
```

非 action 邮件（`fyi`、`spam`）仍然从 `categorize` 直接到 `END`——**不需要人工审核**。

## Checkpointer 选型

有状态工作流必须有持久化层；否则 `interrupt` 和后续 `resume` 之间，
内存里的 `AgentState` 会丢失。

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| `MemorySaver` | 零基础设施 | 进程重启即丢 | **仅用于开发** |
| `SqliteSaver`（`langgraph-checkpoint-sqlite`） | 单文件，存活于重启 | 在 Fly.io 上需要挂持久卷 | **推荐用于本项目** |
| `PostgresSaver`（`langgraph-checkpoint-postgres`） | 生产级、支持并发 | 引入新基础设施依赖 | 对当前规模过度 |

推荐用 `SqliteSaver` 挂在 Fly.io 卷上——`fly.toml` 加一个 `[mounts]` 块即可，
不需要任何新的 managed service。

## API 改造（两阶段）

原本单一的 `POST /agent/process` 拆成两个端点：

```python
# 阶段 1：启动 agent，让每封邮件跑到自己的 interrupt 点。
@router.post("/agent/start", response_model=AgentStartResponse)
async def agent_start(request, session):
    pending = []
    for email in fetch_unread_emails(...):
        thread_id = f"{session.email}:{email['email_id']}:{uuid4()}"
        config = {"configurable": {"thread_id": thread_id}}
        result = agent.invoke(email, config=config)
        if "__interrupt__" in result:
            pending.append({
                "thread_id": thread_id,
                "interrupt_payload": result["__interrupt__"][0].value,
            })
        else:
            # fyi / spam —— 不需要审核就跑完了
            pending.append({"thread_id": thread_id, "completed": result})
    return AgentStartResponse(items=pending)


# 阶段 2：恢复某个待审核项。
@router.post("/agent/resume")
async def agent_resume(request: ResumeRequest, session):
    config = {"configurable": {"thread_id": request.thread_id}}
    result = agent.invoke(Command(resume=request.decision), config=config)
    return {"final_status": result.get("final_status")}
```

**鉴权要点**：每个 checkpoint 的 `thread_id` 必须以当前 session 的 email 作为前缀；
resume 时必须校验前缀和调用者一致，**防止跨用户 resume 别人的草稿**。

## 前端重设计

当前的单表格看板变成两步式流程：

```
[Run Agent] → POST /agent/start → 渲染 pending-review 卡片
                                       │
                              用户对每张卡片选择：
                              ┌──── Approve ──── POST /agent/resume {action:"approve"}
                              ├──── Edit & Send ── （打开 modal）→ POST /agent/resume
                              │                                  {action:"edit_and_send",
                              │                                   subject, body}
                              └──── Discard ────── POST /agent/resume {action:"discard"}
```

Pending 卡片在 resume 之前保持可见；resume 完成后被结果行替换
（sent / sent edited / discarded）。

UX 考虑：

- 每张卡片要有自己的 loading 状态（resume 是异步的）
- **乐观 UI 在这里有风险**——Gmail send 是不可逆的，宁可走悲观确认
- 批量操作（一次批准所有 action 邮件）需要 N 个并行 resume 调用——可以，但要在客户端做限流

## 测试策略

interrupt 机制完全可以**不依赖外部服务**测试：

```python
def test_review_pauses_then_resumes(mock_llm, mock_gmail):
    checkpointer = MemorySaver()
    agent = create_inbox_agent(mock_gmail, mock_calendar, checkpointer)
    config = {"configurable": {"thread_id": "test-1"}}

    # 第一次 invoke：暂停在 review_node
    result = agent.invoke({"email_id": "abc", ...}, config=config)
    assert "__interrupt__" in result
    assert result["__interrupt__"][0].value["kind"] == "review_draft"

    # 第二次 invoke：用 approve 决策恢复
    result = agent.invoke(
        Command(resume={"action": "approve"}),
        config=config,
    )
    assert result["final_status"] == "sent"
    mock_gmail.users().drafts().send.assert_called_once()
```

现有 17 个 agent 测试对非审核路径（fyi、spam）仍然有效。
新增测试预算大约 6-8 个用例，覆盖：暂停 + 每种 resume 动作
+ 跨用户 thread_id 拒绝 + 跨 agent 重建的 checkpoint 持久化。

## 部署变化

```toml
# fly.toml
[mounts]
  source = "inboxzero_checkpoints"
  destination = "/app/data"
```

加一个 SQLite 路径的环境变量：

```python
checkpointer = SqliteSaver.from_conn_string(
    os.environ.get("CHECKPOINT_DB", "/app/data/checkpoints.db")
)
```

**风险**：写入是单机本地的。在 Fly.io 的多机器 auto-stop 策略下，
理论上两台机器可能写到两个不同的卷。对单用户 demo 可接受；
要做到生产级就必须上 Postgres。

## 工作量估算

| 模块 | 估时 |
|---|---|
| Agent 图改造（review_node、execute_decision、路由） | 3-4 小时 |
| SqliteSaver 接入 + Fly.io 卷配置 | 2-3 小时 |
| `/agent/start` 和 `/agent/resume` 端点 | 2-3 小时 |
| 前端重设计（pending 卡片、resume 调用） | 1 天 |
| 测试（pause/resume、跨用户鉴权） | 半天 |
| **合计** | **2-3 天专注开发** |

## 为什么暂时延后

当前的 review-approve 模式（设计讨论中的 Path B）已经覆盖了 HITL 的核心属性
——**不自动发送、外部可见操作前必须人工批准**——而复杂度只是强 HITL 的几分之一。
强 HITL 解锁的是更丰富的交互模式（图执行中途的人工输入、agent 重新规划），
当前项目还不需要。设计记录在这里，
**等真正出现这类用例时，升级路径是具体可执行的**，不需要从零思考。
