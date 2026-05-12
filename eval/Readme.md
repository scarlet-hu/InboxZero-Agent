# 评估框架 (Eval Harness)

对邮件分类逻辑 (`agent_core.categorize_logic`) 进行离线评估，使用人工标注的数据集。
无需 Gmail 或 Calendar 访问权限 —— 只需要一个 LLM API key。

## 目录结构

```
eval/
├── dataset/
│   └── labeled_emails.jsonl   # 30 封人工标注邮件 (action / fyi / spam)
├── results/                   # 自动生成的报告 (已 gitignore)
├── metrics.py                 # 准确率、P/R/F1、混淆矩阵、延迟统计
└── run_eval.py                # CLI 入口
```

## 数据集格式

每行一个 JSON 对象：

```json
{"id": "act-001", "sender": "...", "subject": "...", "email_content": "...", "expected_category": "action", "notes": "..."}
```

`expected_category` 取值范围：{`action`, `fyi`, `spam`}。

当前数据分布：10 条 action / 15 条 fyi / 5 条 spam。

## 运行方式

```bash
# 在仓库根目录执行
set -a && source backend/.env && set +a
python eval/run_eval.py
```

常用参数：

- `--limit N` —— 只跑前 N 条样本 (快速冒烟测试)
- `--tag <name>` —— 给结果文件加后缀，方便 A/B 测试不同 prompt
- `--dataset path/to/other.jsonl` —— 指定其他数据集

## 输出文件

每次运行会在 `eval/results/` 下生成两个文件：

- `eval-<timestamp>[-<tag>].json` —— 完整的机器可读报告 (每条样本 + 所有指标)
- `eval-<timestamp>[-<tag>].md` —— 人类可读报告，包含各类别 P/R/F1、混淆矩阵、错分样本表

CLI 同时会打印一屏摘要：

```
Accuracy : 92.00%  (46/50, 0 errors)
Latency  : p50 1812 ms  p95 3104 ms  mean 1976 ms
Per-category F1:
  action P=0.917 R=0.917 F1=0.917 (n=12)
  fyi    P=0.947 R=0.947 F1=0.947 (n=19)
  spam   P=1.000 R=0.875 F1=0.933 (n=8)
```

## 指标说明

- **Precision (精确率)** = TP / (TP + FP)：预测为该类别的样本中，有多少是真的？关心**误报**。
- **Recall (召回率)** = TP / (TP + FN)：真实属于该类别的样本中，抓到了多少？关心**漏报**。
- **F1** = 2 · P · R / (P + R)：精确率与召回率的调和平均。
- **混淆矩阵**：行是真实标签，列是预测标签，对角线即预测正确。
- **延迟 p50 / p95**：把每条样本耗时升序排列后取分位数。p50 代表典型体验，p95 反映长尾。

## Prompt 迭代工作流

1. 跑基线: `python eval/run_eval.py --tag baseline`
2. 修改 `backend/app/services/agent_core.py::categorize_logic` 中的 system prompt
3. 带新 tag 重跑: `python eval/run_eval.py --tag prompt-v2`
4. 对比两份 markdown 报告 —— 重点看 **Misclassifications** 部分

## 扩充数据集

直接往 `dataset/labeled_emails.jsonl` 追加 JSONL 行即可。建议收集：

- 生产环境中观察到的真实错分案例 (复制粘贴 + 人工标注)
- 模型反复出错的边界样本
- 那些写着 "action required" 但其实是自动通知的 tricky `fyi` 邮件
