from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from generate_pseudo_labels import generate_pseudo_labels_from_rows


def test_pseudo_positive_by_total_score_threshold() -> None:
    rows = [
        {
            "declaration_id": "decl-1",
            "total_score": "75",
            "triggered_rules": "",
        }
    ]

    labels, stats = generate_pseudo_labels_from_rows(rows)

    assert len(labels) == 1
    assert labels[0]["declaration_id"] == "decl-1"
    assert labels[0]["label"] == 1
    assert labels[0]["source"] == "pseudo_l1_rules"
    assert float(labels[0]["confidence"]) >= 0.5
    assert stats["positives"] == 1
    assert stats["negatives"] == 0


def test_pseudo_positive_by_four_high_extreme_layer1_rules() -> None:
    rows = [
        {
            "declaration_id": "decl-2",
            "score": "45",
            "l1_cr1_severity": "HIGH",
            "l1_cr1_triggered": "true",
            "l1_cr2_severity": "EXTREME",
            "l1_cr2_triggered": "1",
            "l1_cr3_severity": "HIGH",
            "l1_cr3_triggered": "yes",
            "l1_cr4_severity": "HIGH",
            "l1_cr4_triggered": "true",
        }
    ]

    labels, stats = generate_pseudo_labels_from_rows(rows)

    assert len(labels) == 1
    assert labels[0]["label"] == 1
    assert float(labels[0]["confidence"]) >= 0.65
    assert stats["positives"] == 1


def test_pseudo_negative_when_low_score_and_no_high_extreme() -> None:
    rows = [
        {
            "declaration_id": "decl-3",
            "score": "12",
            "triggered_rules": "cash_to_bank_ratio",
        }
    ]

    labels, stats = generate_pseudo_labels_from_rows(rows)

    assert len(labels) == 1
    assert labels[0]["label"] == 0
    assert float(labels[0]["confidence"]) > 0.5
    assert stats["negatives"] == 1


def test_unlabeled_rows_are_omitted() -> None:
    rows = [
        {
            "declaration_id": "decl-4",
            "score": "35",
            "triggered_rules": "",
        },
        {
            "declaration_id": "decl-5",
            "score": "18",
            "layer1_rule_severities": "CR1:HIGH",
        },
    ]

    labels, stats = generate_pseudo_labels_from_rows(rows)

    assert labels == []
    assert stats["coverage_rate"] == 0.0
