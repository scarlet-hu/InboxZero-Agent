from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(BACKEND_DIR))

from eval.metrics import CaseResult, build_report, render_markdown  # noqa: E402

DEFAULT_DATASET = REPO_ROOT / "eval" / "dataset" / "labeled_emails.jsonl"
DEFAULT_RESULTS_DIR = REPO_ROOT / "eval" / "results"


def load_dataset(path: Path) -> list[dict]:
    cases = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            cases.append(json.loads(line))
    return cases


SILENT_FAILURE_PREFIX = "Error parsing:"


def run_case(categorize_fn, case: dict) -> CaseResult:
    state = {
        "email_id": case["id"],
        "sender": case["sender"],
        "subject": case["subject"],
        "email_content": case["email_content"],
    }
    started = time.perf_counter()
    try:
        result = categorize_fn(state)
        latency_ms = (time.perf_counter() - started) * 1000
        predicted = result.get("category", "")
        summary = result.get("summary", "")
        # Detect silent fallback inside categorize_logic (bare except → fyi).
        # Without this, API/parse failures masquerade as legitimate "fyi" predictions.
        if summary.startswith(SILENT_FAILURE_PREFIX):
            return CaseResult(
                case_id=case["id"],
                expected=case["expected_category"],
                predicted=predicted,
                summary=summary,
                latency_ms=round(latency_ms, 2),
                error=summary,
            )
        return CaseResult(
            case_id=case["id"],
            expected=case["expected_category"],
            predicted=predicted,
            summary=summary,
            latency_ms=round(latency_ms, 2),
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        return CaseResult(
            case_id=case["id"],
            expected=case["expected_category"],
            predicted="",
            latency_ms=round(latency_ms, 2),
            error=f"{type(exc).__name__}: {exc}",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run categorization eval over a labeled dataset")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--limit", type=int, default=None, help="Run only the first N cases")
    parser.add_argument("--tag", type=str, default="", help="Optional label appended to result filename")
    args = parser.parse_args()

    if not os.getenv("GOOGLE_API_KEY"):
        print("ERROR: GOOGLE_API_KEY is not set. Add it to backend/.env or export it.", file=sys.stderr)
        return 2

    if not args.dataset.exists():
        print(f"ERROR: dataset not found at {args.dataset}", file=sys.stderr)
        return 2

    from app.services.agent_core import categorize_logic, llm

    cases = load_dataset(args.dataset)
    if args.limit:
        cases = cases[: args.limit]

    print(f"Running {len(cases)} cases against model={llm.model}...")
    results: list[CaseResult] = []
    for i, case in enumerate(cases, 1):
        r = run_case(categorize_logic, case)
        marker = "✓" if r.correct else ("ERR" if r.error else "✗")
        print(f"  [{i:>2}/{len(cases)}] {marker} {r.case_id:<10} expected={r.expected:<6} predicted={r.predicted or '<error>':<6} {r.latency_ms:>7.0f} ms")
        results.append(r)

    report = build_report(results)
    args.results_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    suffix = f"-{args.tag}" if args.tag else ""
    json_path = args.results_dir / f"eval-{stamp}{suffix}.json"
    md_path = args.results_dir / f"eval-{stamp}{suffix}.md"

    json_path.write_text(json.dumps(report.to_dict(), indent=2))
    md_path.write_text(render_markdown(report, model_name=llm.model, dataset_path=str(args.dataset.relative_to(REPO_ROOT))))

    print()
    print(f"Accuracy : {report.accuracy:.2%}  ({report.correct}/{report.total}, {report.errors} errors)")
    print(f"Latency  : p50 {report.latency_p50_ms} ms  p95 {report.latency_p95_ms} ms  mean {report.latency_mean_ms} ms")
    print("Per-category F1:")
    for cat, s in report.per_category.items():
        print(f"  {cat:<6} P={s.precision:.3f} R={s.recall:.3f} F1={s.f1:.3f} (n={s.support})")
    print()
    print(f"Wrote {json_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {md_path.relative_to(REPO_ROOT)}")
    return 0 if report.errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
