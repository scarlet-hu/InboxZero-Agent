# ReAct vs 状态机：Token 成本对比

生产环境的 agent 在 `backend/app/services/agent_core.py`，是一个确定性的
LangGraph 状态机：分类结果决定每封邮件走固定的图路径
（`categorize → check_calendar → draft_reply` 处理 action 邮件，fyi/spam 直接到
`END`）。`backend/app/services/agent_core_react.py` 是另一种实现：用
`langgraph.prebuilt.create_react_agent` + `@tool` 装饰的 calendar / draft 工具，
让 LLM 自己决定是否调用、何时调用。

本文档用一次实测的 token 数据说明：为什么生产路径保留状态机。

## 实验设置

- 模型：`gemini-2.5-flash`，`temperature=0`
- 埋点：在 `process_inbox` 里挂 `langchain_core.callbacks.UsageMetadataCallbackHandler`，
  按 per-email 和 per-run 两个粒度累计 token
- 邮件批次：5 封真实邮件——1 封 action（`wanna meet up tmr?`，包含具体会议时间，
  会触发 calendar + draft 路径）、2 封 fyi 通知、2 封营销邮件
- 同一批 Gmail、同一模型、同一 temperature；两次跑之间只切换 agent 实现

## 结果

### 整批（5 封邮件）

| | 状态机 | ReAct | Δ |
|---|---:|---:|---:|
| Input tokens | 6,078 | 7,536 | **+24%** |
| Output tokens | 2,647 | 1,677 | -37% |
| **Total** | **8,725** | **9,213** | **+5.6%** |
| avg / email | 1,745 | 1,842 | +5.6% |

### 单封 action 邮件（`wanna meet up tmr?`）

| | 状态机 | ReAct | Δ |
|---|---:|---:|---:|
| Input tokens | 798 | 2,348 | **+194%（2.9×）** |
| Output tokens | 1,242 | 1,018 | -18% |
| **Total** | **2,040** | **3,366** | **+65%** |

### 原始日志

状态机：

```
🧐 Analyzing: wanna meet up tmr?...
🗓️  Checking calendar for context...
✍️  Drafting reply...
[USAGE] action | in=  798 out= 1242 total= 2040 | wanna meet up tmr?
[USAGE]    fyi | in=  914 out=  354 total= 1268 | Billing usage this month
[USAGE]    fyi | in= 1150 out=  362 total= 1512 | Your shopping cart is ready
[USAGE]    fyi | in= 1587 out=  298 total= 1885 | Make shopping 15% more rewarding
[USAGE]    fyi | in= 1629 out=  391 total= 2020 | * Up to 50% off starts now *
[USAGE] === RUN TOTAL: 5 emails | in=6078 out=2647 total=8725 | avg/email=1745 ===
```

ReAct：

```
[USAGE] action | in= 2348 out= 1018 total= 3366 | wanna meet up tmr?
[USAGE]    fyi | in=  891 out=  171 total= 1062 | Billing usage this month
[USAGE]    fyi | in= 1127 out=  221 total= 1348 | Your shopping cart is ready
[USAGE]   spam | in= 1564 out=  153 total= 1717 | Make shopping 15% more rewarding
[USAGE]   spam | in= 1606 out=  114 total= 1720 | * Up to 50% off starts now *
[USAGE] === RUN TOTAL: 5 emails | in=7536 out=1677 total=9213 | avg/email=1842 ===
```

## 分析

### 为什么 action 邮件的 ReAct input tokens 几乎是 3 倍

ReAct 在每轮 reasoning 都会重发整个对话上下文。一封 action 邮件的 trace 大致是：

```
Round 1: [system + tool schemas] + user(email) → LLM 决定调 check_calendar
Round 2: [system + tool schemas] + user(email) + AI(call calendar) + tool(result)
         → LLM 决定调 create_draft
Round 3: [system + tool schemas] + user(email) + AI(call calendar) + tool(result)
         + AI(call draft) + tool(result) → LLM 输出最终 JSON
```

`[方括号]` 里的内容每轮都重发一次。`@tool` 自动生成的 JSON schema
本身就不小（两个 tool 加起来约 500 tokens）。

状态机的三次 LLM call（`categorize`、`extract date`、`draft body`）每次都是
**独立短 prompt**，没有上下文累积——所以 input 又小又稳定。

### 为什么状态机的 output 反而更高

状态机在 `draft_reply_logic` 有一次专门用来生成完整回信正文的 LLM call——
1,242 output tokens 大头都来自那里。ReAct 这边，回信正文是作为
`create_draft_reply(subject, body)` 的 tool call 参数发出的；这部分仍然算
output tokens，但 LLM 通常更紧凑——因为对话上下文里已经隐含了背景。

### 整批 +5.6% 是有误导性的

这批 80% 都是非 action 邮件，那些路径在两种实现下基本都是 1 次 LLM call，
架构差异被大幅稀释。真正的成本差异集中在 action 路径。按单 action 邮件
+65% 外推不同的 action 占比：

| Inbox 中 action 占比 | ReAct 估算溢价 |
|---|---|
| 20%（本次实测） | +5.6%（实测） |
| 50%（典型工作邮箱） | ~+33% |
| 80%（销售/客服岗） | ~+52% |

### 边界邮件分类漂移

两封营销邮件分到了不同类别：

| 邮件主题 | 状态机 | ReAct |
|---|---|---|
| Make shopping 15% more rewarding | fyi | spam |
| * Up to 50% off starts now * | fyi | spam |

**这不是 ReAct 范式本身的问题**——两个版本的 prompt 文本不严格等价。
状态机的 prompt 明确把已订阅营销列为 fyi（`"Newsletters, digests, product
update announcements, marketing from services you've signed up for"`），
ReAct 的 prompt 没写这条豁免。

但它确实暴露了一个普遍风险：当一条规则和 tool schemas + 累积的 tool history
打包送给 LLM 时，它的"权重"不如在独立短 prompt 里的版本。

## 结论

生产路径保留状态机，因为：

1. **成本可预测**——三次独立短 prompt，比"每轮重发整个上下文"在任何
   有意义的 action 占比下都更便宜。
2. **行为确定**——边界邮件的路由由 category 决定，不会因为 LLM 在 trace
   中途改主意而漂移。这点重要，因为 action 分支会创建 Gmail 草稿，是有副作用的。
3. **可观测性**——`AgentState` 的 typed 字段直接对应 HITL 看板要读的字段；
   ReAct 版本需要从一份自由格式的 messages trace 反向重建相同的结构。
4. **可测试性**——节点是纯函数（`(state) -> dict`），mock `llm.invoke`
   就能写确定性 unit test；ReAct 的多轮决策很难写出确定性测试。

ReAct（或 `langgraph.prebuilt.create_react_agent`）在以下场景更合适：
工具数量很多、调用顺序真的开放、需要 LLM 推理来挑选合适的 tool——
InboxZero 的三步固定流程都不属于这种。
