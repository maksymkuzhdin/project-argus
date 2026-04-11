"""Train a Layer 3 Isolation Forest artifact from declaration features.

Example:
  python scripts/train_layer3.py --data-dir data/raw --year 2024 --output argus/backend/models/layer3_iforest.pkl
"""

from __future__ import annotations

import argparse
import pickle
import random
import statistics
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.ingestion.save_raw import iter_raw_declarations, load_declaration  # type: ignore[import-not-found]
from app.scoring.layer3 import build_feature_vector  # type: ignore[import-not-found]
from app.services.pipeline import process_declaration_full  # type: ignore[import-not-found]


def _robust_stats(columns: list[list[float]]) -> tuple[list[float], list[float]]:
    medians: list[float] = []
    scales: list[float] = []
    for col in columns:
        if not col:
            medians.append(0.0)
            scales.append(1.0)
            continue
        med = statistics.median(col)
        abs_dev = [abs(v - med) for v in col]
        mad = statistics.median(abs_dev)
        scale = mad * 1.4826
        if scale <= 1e-9:
            scale = 1.0
        medians.append(float(med))
        scales.append(float(scale))
    return medians, scales


def _as_float(value: object | None) -> float:
    if value is None:
        return 0.0
    return float(Decimal(str(value)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Layer 3 Isolation Forest model")
    parser.add_argument("--data-dir", type=Path, default=Path("data/raw"), help="Raw declaration directory")
    parser.add_argument("--year", type=str, default=None, help="Optional year filter")
    parser.add_argument("--limit", type=int, default=0, help="Optional cap on number of declarations")
    parser.add_argument("--output", type=Path, required=True, help="Output .pkl model path")
    parser.add_argument("--contamination", type=float, default=0.03, help="IsolationForest contamination")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--min-samples", type=int, default=50, help="Minimum samples required for training")
    args = parser.parse_args()

    try:
        from sklearn.ensemble import IsolationForest  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover
        raise SystemExit(
            "scikit-learn is required. Install backend requirements before training."
        ) from exc

    files = iter_raw_declarations(args.data_dir, year=args.year)
    if args.limit > 0:
        files = files[: args.limit]

    if not files:
        raise SystemExit("No raw declaration files found for training.")

    random.seed(args.seed)

    feature_maps: list[dict[str, float]] = []
    for f in files:
        raw = load_declaration(f)
        full = process_declaration_full(raw)
        features = full.get("features", {})

        feature_map = build_feature_vector(
            total_income=features.get("total_income"),
            total_assets=features.get("total_assets"),
            cash_holdings=features.get("cash"),
            bank_deposits=features.get("bank"),
            total_value_fields=int(features.get("total_value_fields") or 0),
            unknown_value_fields=int(features.get("unknown_value_fields") or 0),
            ownership_declarant=0,
            ownership_family=0,
            ownership_total=0,
            declaration_year=full.get("declaration_year"),
            incomes_count=len(full.get("incomes", [])),
            real_estate_count=len(full.get("real_estate", [])),
            vehicles_count=len(full.get("vehicles", [])),
            monetary_count=len(full.get("monetary", [])),
            confidential_ratio=float(features.get("confidential_ratio") or 0.0),
        )
        feature_maps.append(feature_map)

    if len(feature_maps) < args.min_samples:
        raise SystemExit(
            f"Not enough samples for training ({len(feature_maps)} < {args.min_samples})."
        )

    feature_order = sorted(feature_maps[0].keys())
    matrix = [[fm.get(name, 0.0) for name in feature_order] for fm in feature_maps]

    # Build robust normalization metadata for explainability and optional calibration.
    columns = [[row[i] for row in matrix] for i in range(len(feature_order))]
    medians, scales = _robust_stats(columns)
    robust_matrix = [
        [
            (row[i] - medians[i]) / scales[i]
            for i in range(len(feature_order))
        ]
        for row in matrix
    ]

    model = IsolationForest(
        n_estimators=300,
        contamination=args.contamination,
        random_state=args.seed,
        n_jobs=-1,
    )
    model.fit(robust_matrix)

    decisions = [float(x) for x in model.decision_function(robust_matrix)]
    artifact = {
        "model": model,
        "feature_order": feature_order,
        "decision_min": min(decisions),
        "decision_max": max(decisions),
        "robust_medians": medians,
        "robust_scales": scales,
        "training": {
            "sample_count": len(matrix),
            "contamination": args.contamination,
            "seed": args.seed,
            "year_filter": args.year,
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as fh:
        pickle.dump(artifact, fh)

    print(f"Trained Layer 3 model on {len(matrix)} samples -> {args.output}")


if __name__ == "__main__":
    main()
