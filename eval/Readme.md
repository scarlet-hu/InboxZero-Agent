# Eval Harness

Offline evaluation of the email categorization step (`agent_core.categorize_logic`)
against a labeled dataset. No Gmail or Calendar access required — only an LLM API key.

## Layout

```
eval/
├── dataset/
│   └── labeled_emails.jsonl   # 30 hand-labeled emails (action / fyi / spam)
├── results/                   # generated reports (gitignored)
├── metrics.py                 # accuracy, P/R/F1, confusion matrix, latency
└── run_eval.py                # CLI entry point
```

## Dataset format

One JSON object per line:

```json
{"id": "act-001", "sender": "...", "subject": "...", "email_content": "...", "expected_category": "action", "notes": "..."}
```

`expected_category` ∈ {`action`, `fyi`, `spam`}.

Current split: 10 action / 15 fyi / 5 spam.

## Run it

```bash
# from repo root
set -a && source backend/.env && set +a
python eval/run_eval.py
```

Useful flags:

- `--limit N` — run only the first N cases (fast smoke test)
- `--tag <name>` — appends to result filenames so you can A/B prompts
- `--dataset path/to/other.jsonl` — point at a different set

## Output

Each run writes two files to `eval/results/`:

- `eval-<timestamp>[-<tag>].json` — full machine-readable report (every case + metrics)
- `eval-<timestamp>[-<tag>].md` — human-readable report with per-category P/R/F1, confusion matrix, and a misclassifications table

The CLI also prints a one-screen summary:

```
Accuracy : 92.00%  (46/50, 0 errors)
Latency  : p50 1812 ms  p95 3104 ms  mean 1976 ms
Per-category F1:
  action P=0.917 R=0.917 F1=0.917 (n=12)
  fyi    P=0.947 R=0.947 F1=0.947 (n=19)
  spam   P=1.000 R=0.875 F1=0.933 (n=8)
```

## Workflow for prompt iteration

1. Run baseline: `python eval/run_eval.py --tag baseline`
2. Tweak the system prompt in `backend/app/services/agent_core.py::categorize_logic`
3. Re-run with a new tag: `python eval/run_eval.py --tag prompt-v2`
4. Diff the two markdown reports — focus on the **Misclassifications** section.

## Adding cases

Append new JSONL lines to `dataset/labeled_emails.jsonl`. Useful additions:

- Real misclassifications you saw in production (paste them in, label them)
- Edge cases the model gets wrong consistently
- Tricky `fyi` cases that say "action required" but are automated
