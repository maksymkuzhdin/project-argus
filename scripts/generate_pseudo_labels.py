"""Generate weak-supervision pseudo-labels from rule-based scoring output.

Usage:
    python scripts/generate_pseudo_labels.py \
        --scores-csv output/scores.csv \
        --output output/pseudo_labels.csv
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Any


SOURCE_NAME = "pseudo_l1_rules"


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _extract_total_score(row: dict[str, Any]) -> float:
    for key in ("total_score", "score"):
        val = _to_float(row.get(key))
        if val is not None:
            return val
    return 0.0


def _truthy(value: Any) -> bool:
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "t"}


def _clean_rule_name(raw: str) -> str:
    name = raw.strip().lower()
    name = re.sub(r"^(layer1_|l1_)", "", name)
    return name


def _extract_high_extreme_rules(row: dict[str, Any]) -> set[str]:
    rules: set[str] = set()

    for key, value in row.items():
        key_l = str(key).lower().strip()
        if "severity" not in key_l and "severities" not in key_l:
            continue

        value_text = str(value or "").strip().upper()
        if not value_text:
            continue

        # Common shape: <rule_name>_severity=HIGH
        if key_l.endswith("_severity") and value_text in {"HIGH", "EXTREME"}:
            base = key_l[: -len("_severity")]
            triggered_key = f"{base}_triggered"
            if triggered_key in row and not _truthy(row.get(triggered_key)):
                continue
            rules.add(_clean_rule_name(base))
            continue

        # Fallback shape: "CR1:HIGH, CR3:EXTREME" inside one text field.
        for match in re.finditer(r"([A-Za-z0-9_.-]+)\s*[:=]\s*(HIGH|EXTREME)", value_text):
            rules.add(_clean_rule_name(match.group(1)))

    triggered_rules_fields = [
        "triggered_rules",
        "layer1_triggered_rules",
        "l1_triggered_rules",
    ]
    for field in triggered_rules_fields:
        text = str(row.get(field) or "")
        if not text:
            continue
        # Optional encoded forms: rule(HIGH) or rule:HIGH
        for match in re.finditer(r"([A-Za-z0-9_.-]+)\s*(?:\(|:)\s*(HIGH|EXTREME)", text, flags=re.IGNORECASE):
            rules.add(_clean_rule_name(match.group(1)))

    return rules


def _positive_confidence(total_score: float, high_extreme_count: int) -> float:
    score_conf = 0.0
    if total_score >= 70.0:
        # 70 -> 0.5, 100+ -> 1.0
        score_conf = 0.5 + min(1.0, max(0.0, (total_score - 70.0) / 30.0)) * 0.5

    rules_conf = 0.0
    if high_extreme_count >= 4:
        # 4 rules -> 0.65, 8+ rules -> 1.0
        rules_conf = 0.65 + min(1.0, max(0.0, (high_extreme_count - 4) / 4.0)) * 0.35

    confidence = max(score_conf, rules_conf)
    return round(min(1.0, max(0.0, confidence)), 4)


def _negative_confidence(total_score: float) -> float:
    # 20 -> 0.5, 0 -> 1.0
    confidence = 0.5 + min(1.0, max(0.0, (20.0 - total_score) / 20.0)) * 0.5
    return round(min(1.0, max(0.0, confidence)), 4)


def generate_pseudo_labels_from_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, float]]:
    labels: list[dict[str, Any]] = []
    total_rows = len(rows)

    for row in rows:
        declaration_id = str(row.get("declaration_id") or "").strip()
        if not declaration_id:
            continue

        total_score = _extract_total_score(row)
        high_extreme_rules = _extract_high_extreme_rules(row)
        high_extreme_count = len(high_extreme_rules)

        is_positive = total_score >= 70.0 or high_extreme_count >= 4
        is_negative = total_score <= 20.0 and high_extreme_count == 0

        if not is_positive and not is_negative:
            continue

        if is_positive:
            label = 1
            confidence = _positive_confidence(total_score, high_extreme_count)
        else:
            label = 0
            confidence = _negative_confidence(total_score)

        labels.append(
            {
                "declaration_id": declaration_id,
                "label": label,
                "confidence": f"{confidence:.4f}",
                "source": SOURCE_NAME,
            }
        )

    positives = sum(1 for row in labels if int(row["label"]) == 1)
    negatives = sum(1 for row in labels if int(row["label"]) == 0)
    coverage_rate = (len(labels) / total_rows) if total_rows > 0 else 0.0

    stats = {
        "total_rows": float(total_rows),
        "positives": float(positives),
        "negatives": float(negatives),
        "coverage_rate": coverage_rate,
    }
    return labels, stats


def _read_scores_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return [dict(row) for row in reader]


def _write_labels_csv(path: Path, labels: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["declaration_id", "label", "confidence", "source"],
        )
        writer.writeheader()
        writer.writerows(labels)


def _print_summary(stats: dict[str, float]) -> None:
    total_rows = int(stats["total_rows"])
    positives = int(stats["positives"])
    negatives = int(stats["negatives"])
    coverage_rate = stats["coverage_rate"] * 100.0

    print(f"Total positives: {positives}")
    print(f"Total negatives: {negatives}")
    print(f"Coverage rate: {coverage_rate:.2f}% ({positives + negatives}/{total_rows})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate pseudo-labels from scoring CSV")
    parser.add_argument("--scores-csv", type=Path, required=True, help="Input scoring CSV path")
    parser.add_argument("--output", type=Path, required=True, help="Output pseudo-label CSV path")
    parser.add_argument("--dry-run", action="store_true", help="Compute and print stats without writing output")
    args = parser.parse_args()

    rows = _read_scores_csv(args.scores_csv)
    labels, stats = generate_pseudo_labels_from_rows(rows)

    if not args.dry_run:
        _write_labels_csv(args.output, labels)

    _print_summary(stats)


if __name__ == "__main__":
    main()
