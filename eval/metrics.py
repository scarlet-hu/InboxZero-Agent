from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from statistics import median
from typing import Iterable

CATEGORIES = ("action", "fyi", "spam")


@dataclass
class CaseResult:
    case_id: str
    expected: str
    predicted: str
    latency_ms: float
    summary: str = ""
    error: str | None = None

    @property
    def correct(self) -> bool:
        return self.error is None and self.expected == self.predicted


@dataclass
class CategoryStats:
    precision: float
    recall: float
    f1: float
    support: int


@dataclass
class EvalReport:
    total: int
    correct: int
    errors: int
    accuracy: float
    per_category: dict[str, CategoryStats]
    confusion: dict[str, dict[str, int]]
    latency_p50_ms: float
    latency_p95_ms: float
    latency_mean_ms: float
    cases: list[CaseResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "correct": self.correct,
            "errors": self.errors,
            "accuracy": self.accuracy,
            "per_category": {k: asdict(v) for k, v in self.per_category.items()},
            "confusion": self.confusion,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p95_ms": self.latency_p95_ms,
            "latency_mean_ms": self.latency_mean_ms,
            "cases": [asdict(c) for c in self.cases],
        }


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((pct / 100) * (len(s) - 1)))))
    return s[k]


def _per_category_stats(cases: Iterable[CaseResult]) -> dict[str, CategoryStats]:
    tp = defaultdict(int)
    fp = defaultdict(int)
    fn = defaultdict(int)
    support = defaultdict(int)

    for c in cases:
        support[c.expected] += 1
        if c.error is not None:
            fn[c.expected] += 1
            continue
        if c.predicted == c.expected:
            tp[c.expected] += 1
        else:
            fp[c.predicted] += 1
            fn[c.expected] += 1

    out: dict[str, CategoryStats] = {}
    for cat in CATEGORIES:
        p_denom = tp[cat] + fp[cat]
        r_denom = tp[cat] + fn[cat]
        precision = tp[cat] / p_denom if p_denom else 0.0
        recall = tp[cat] / r_denom if r_denom else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        out[cat] = CategoryStats(
            precision=round(precision, 4),
            recall=round(recall, 4),
            f1=round(f1, 4),
            support=support[cat],
        )
    return out


def _confusion(cases: Iterable[CaseResult]) -> dict[str, dict[str, int]]:
    matrix = {a: {b: 0 for b in CATEGORIES} for a in CATEGORIES}
    for c in cases:
        if c.error is not None or c.predicted not in CATEGORIES:
            continue
        matrix[c.expected][c.predicted] += 1
    return matrix


def build_report(cases: list[CaseResult]) -> EvalReport:
    total = len(cases)
    errors = sum(1 for c in cases if c.error is not None)
    correct = sum(1 for c in cases if c.correct)
    latencies = [c.latency_ms for c in cases]

    return EvalReport(
        total=total,
        correct=correct,
        errors=errors,
        accuracy=round(correct / total, 4) if total else 0.0,
        per_category=_per_category_stats(cases),
        confusion=_confusion(cases),
        latency_p50_ms=round(median(latencies), 2) if latencies else 0.0,
        latency_p95_ms=round(_percentile(latencies, 95), 2),
        latency_mean_ms=round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
        cases=cases,
    )


def render_markdown(report: EvalReport, model_name: str, dataset_path: str) -> str:
    lines = [
        "# Eval Report",
        "",
        f"- **Model:** `{model_name}`",
        f"- **Dataset:** `{dataset_path}`",
        f"- **Cases:** {report.total} ({report.errors} errors)",
        f"- **Accuracy:** **{report.accuracy:.2%}** ({report.correct}/{report.total})",
        f"- **Latency:** p50 {report.latency_p50_ms} ms · p95 {report.latency_p95_ms} ms · mean {report.latency_mean_ms} ms",
        "",
        "## Per-Category",
        "",
        "| Category | Precision | Recall | F1 | Support |",
        "|---|---:|---:|---:|---:|",
    ]
    for cat, s in report.per_category.items():
        lines.append(f"| {cat} | {s.precision:.3f} | {s.recall:.3f} | {s.f1:.3f} | {s.support} |")

    lines += ["", "## Confusion Matrix (rows = expected, cols = predicted)", ""]
    header = "| expected \\ predicted | " + " | ".join(CATEGORIES) + " |"
    sep = "|" + "---|" * (len(CATEGORIES) + 1)
    lines += [header, sep]
    for actual in CATEGORIES:
        row = [str(report.confusion[actual][p]) for p in CATEGORIES]
        lines.append(f"| **{actual}** | " + " | ".join(row) + " |")

    misses = [c for c in report.cases if not c.correct]
    if misses:
        lines += ["", "## Misclassifications", "", "| Case | Expected | Predicted | Latency (ms) | Error |", "|---|---|---|---:|---|"]
        for c in misses:
            err = c.error or ""
            lines.append(f"| `{c.case_id}` | {c.expected} | {c.predicted} | {c.latency_ms:.0f} | {err} |")

    return "\n".join(lines) + "\n"
