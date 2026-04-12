"""Train Layer 3 Isolation Forest artifacts (global + per-cohort).

Year-over-year fields used by scripts/run_timeline.py via PersonTimeline.changes
(from backend/app/normalization/assemble_timeline.py):
- income_delta
- monetary_delta
- cash_delta
- asset_growth
- income_growth
- unknown_share_delta
- major_assets_appeared
- major_assets_disappeared

Example:
    python scripts/train_layer3.py --data-dir data/raw --year 2024 --output argus/backend/models/layer3_iforest.pkl
"""

from __future__ import annotations

import argparse
import json
import logging
import pickle
import random
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.ingestion.save_raw import iter_raw_declarations, load_declaration  # type: ignore[import-not-found]
from app.features.ownership import compute_ownership_summary  # type: ignore[import-not-found]
from app.normalization.assemble_timeline import assemble_timeline  # type: ignore[import-not-found]
from app.services.pipeline import process_declaration_full  # type: ignore[import-not-found]
from app.config import settings  # type: ignore[import-not-found]


logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


FEATURE_NAMES: list[str] = [
    "total_income",
    "total_assets",
    "cash_holdings",
    "bank_deposits",
    "cash_ratio",
    "asset_income_ratio",
    "unknown_share",
    "confidential_ratio",
    "family_ownership_share",
    "declarant_ownership_share",
    "incomes_count",
    "real_estate_count",
    "vehicles_count",
    "monetary_count",
    "declaration_year",
    "income_yoy_delta_pct",
    "assets_yoy_delta_pct",
    "cash_ratio_yoy_delta",
    "confidential_ratio_yoy_delta",
    "asset_income_ratio_delta",
    "new_property_count",
    "dropped_property_count",
    "max_single_asset_jump_pct",
]


DELTA_FEATURE_DEFAULTS: dict[str, float] = {
    "income_yoy_delta_pct": 0.0,
    "assets_yoy_delta_pct": 0.0,
    "cash_ratio_yoy_delta": 0.0,
    "confidential_ratio_yoy_delta": 0.0,
    "asset_income_ratio_delta": 0.0,
    "new_property_count": 0.0,
    "dropped_property_count": 0.0,
    "max_single_asset_jump_pct": 0.0,
}


def _slug(value: str | None) -> str:
    raw = (value or "other").strip().lower()
    out = []
    for ch in raw:
        if ch.isalnum():
            out.append(ch)
        else:
            out.append("_")
    slug = "".join(out).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "other"


def _as_float(value: object | None) -> float:
    if value is None:
        return 0.0
    return float(Decimal(str(value)))


def _safe_pct_change(prev: float, curr: float) -> float:
    if prev <= 0:
        return 0.0
    return (curr - prev) / prev


def _asset_income_ratio(assets: float, income: float) -> float:
    if income > 0:
        return assets / income
    return 10.0 if assets > 0 else 0.0


def build_feature_vector(
    *,
    total_income: Any,
    total_assets: Any,
    cash_holdings: Any,
    bank_deposits: Any,
    total_value_fields: int,
    unknown_value_fields: int,
    ownership_declarant: int,
    ownership_family: int,
    ownership_total: int,
    declaration_year: int | None,
    incomes_count: int,
    real_estate_count: int,
    vehicles_count: int,
    monetary_count: int,
    confidential_ratio: float,
    income_yoy_delta_pct: float = 0.0,
    assets_yoy_delta_pct: float = 0.0,
    cash_ratio_yoy_delta: float = 0.0,
    confidential_ratio_yoy_delta: float = 0.0,
    asset_income_ratio_delta: float = 0.0,
    new_property_count: float = 0.0,
    dropped_property_count: float = 0.0,
    max_single_asset_jump_pct: float = 0.0,
) -> dict[str, float]:
    income = max(0.0, _as_float(total_income))
    assets = max(0.0, _as_float(total_assets))
    cash = max(0.0, _as_float(cash_holdings))
    bank = max(0.0, _as_float(bank_deposits))

    unknown_share = (
        float(unknown_value_fields) / float(total_value_fields)
        if total_value_fields > 0
        else 0.0
    )
    family_share = (
        float(ownership_family) / float(ownership_total)
        if ownership_total > 0
        else 0.0
    )
    declarant_share = (
        float(ownership_declarant) / float(ownership_total)
        if ownership_total > 0
        else 0.0
    )
    cash_ratio = (cash / (cash + bank)) if (cash + bank) > 0 else 0.0
    asset_income_ratio = _asset_income_ratio(assets, income)

    feature_map = {
        "total_income": income,
        "total_assets": assets,
        "cash_holdings": cash,
        "bank_deposits": bank,
        "cash_ratio": cash_ratio,
        "asset_income_ratio": asset_income_ratio,
        "unknown_share": unknown_share,
        "confidential_ratio": max(0.0, min(1.0, _as_float(confidential_ratio))),
        "family_ownership_share": family_share,
        "declarant_ownership_share": declarant_share,
        "incomes_count": float(max(0, incomes_count)),
        "real_estate_count": float(max(0, real_estate_count)),
        "vehicles_count": float(max(0, vehicles_count)),
        "monetary_count": float(max(0, monetary_count)),
        "declaration_year": float(declaration_year or 0),
        "income_yoy_delta_pct": float(income_yoy_delta_pct),
        "assets_yoy_delta_pct": float(assets_yoy_delta_pct),
        "cash_ratio_yoy_delta": float(cash_ratio_yoy_delta),
        "confidential_ratio_yoy_delta": float(confidential_ratio_yoy_delta),
        "asset_income_ratio_delta": float(asset_income_ratio_delta),
        "new_property_count": float(new_property_count),
        "dropped_property_count": float(dropped_property_count),
        "max_single_asset_jump_pct": float(max_single_asset_jump_pct),
    }
    return {name: float(feature_map.get(name, 0.0)) for name in FEATURE_NAMES}


def _max_single_asset_jump_pct(prev_assets: dict[str, Decimal], curr_assets: dict[str, Decimal]) -> float:
    shared = set(prev_assets.keys()) & set(curr_assets.keys())
    max_jump = 0.0
    for key in shared:
        prev = _as_float(prev_assets.get(key))
        curr = _as_float(curr_assets.get(key))
        if prev <= 0:
            continue
        jump = (curr - prev) / prev
        if jump > max_jump:
            max_jump = jump
    return max_jump


def _compute_timeline_deltas(full_entries: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    by_uid: dict[int, list[dict[str, Any]]] = {}
    conf_ratio_by_decl: dict[str, float] = {}
    for full in full_entries:
        decl_id = str(full.get("declaration_id") or "")
        features = full.get("features") or {}
        conf_ratio_by_decl[decl_id] = float(features.get("confidential_ratio") or 0.0)
        uid = full.get("user_declarant_id")
        if uid is None:
            continue
        by_uid.setdefault(int(uid), []).append(full)

    deltas_by_declaration: dict[str, dict[str, float]] = {}
    for uid_fulls in by_uid.values():
        if len(uid_fulls) < 2:
            continue
        timeline = assemble_timeline(uid_fulls)
        if timeline is None:
            continue

        annual = [s for s in timeline.snapshots if s.declaration_type == 1]
        if len(annual) < 2:
            continue

        for idx in range(1, len(annual)):
            prev = annual[idx - 1]
            curr = annual[idx]
            curr_id = str(curr.declaration_id)

            prev_income = _as_float(prev.total_income)
            curr_income = _as_float(curr.total_income)
            prev_assets = _as_float(prev.total_assets)
            curr_assets = _as_float(curr.total_assets)

            prev_cash = _as_float(prev.cash)
            prev_bank = _as_float(prev.bank)
            curr_cash = _as_float(curr.cash)
            curr_bank = _as_float(curr.bank)
            prev_cash_ratio = (prev_cash / (prev_cash + prev_bank)) if (prev_cash + prev_bank) > 0 else 0.0
            curr_cash_ratio = (curr_cash / (curr_cash + curr_bank)) if (curr_cash + curr_bank) > 0 else 0.0

            prev_conf = conf_ratio_by_decl.get(str(prev.declaration_id), 0.0)
            curr_conf = conf_ratio_by_decl.get(str(curr.declaration_id), 0.0)

            prev_asset_income = _asset_income_ratio(prev_assets, prev_income)
            curr_asset_income = _asset_income_ratio(curr_assets, curr_income)

            appeared = set(curr.major_assets.keys()) - set(prev.major_assets.keys())
            disappeared = set(prev.major_assets.keys()) - set(curr.major_assets.keys())

            deltas_by_declaration[curr_id] = {
                "income_yoy_delta_pct": _safe_pct_change(prev_income, curr_income),
                "assets_yoy_delta_pct": _safe_pct_change(prev_assets, curr_assets),
                "cash_ratio_yoy_delta": curr_cash_ratio - prev_cash_ratio,
                "confidential_ratio_yoy_delta": curr_conf - prev_conf,
                "asset_income_ratio_delta": curr_asset_income - prev_asset_income,
                "new_property_count": float(len(appeared)),
                "dropped_property_count": float(len(disappeared)),
                "max_single_asset_jump_pct": _max_single_asset_jump_pct(prev.major_assets, curr.major_assets),
            }

    return deltas_by_declaration


def _default_model_dir() -> Path:
    raw_model_path = str(getattr(settings, "layer3_model_path", "") or "").strip()
    if not raw_model_path:
        return Path("backend/models")
    p = Path(raw_model_path)
    if p.suffix.lower() == ".pkl":
        return p.parent
    return p


def _train_pipeline(X: list[list[float]], contamination: float, seed: int) -> Any:
    from sklearn.ensemble import IsolationForest  # type: ignore[import-not-found]
    from sklearn.impute import SimpleImputer  # type: ignore[import-not-found]
    from sklearn.pipeline import Pipeline  # type: ignore[import-not-found]
    from sklearn.preprocessing import RobustScaler  # type: ignore[import-not-found]

    pipeline = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", RobustScaler()),
            (
                "model",
                IsolationForest(
                    n_estimators=300,
                    contamination=contamination,
                    random_state=seed,
                    n_jobs=-1,
                ),
            ),
        ]
    )
    pipeline.fit(X)
    return pipeline


def _permutation_feature_contributions(
    model: Any,
    X: list[list[float]],
    *,
    seed: int,
) -> list[tuple[str, float]]:
    if not X:
        return []
    base_scores = [float(s) for s in model.decision_function(X)]
    rng = random.Random(seed)
    rows = len(X)
    cols = len(FEATURE_NAMES)
    importances: list[tuple[str, float]] = []

    for col_idx in range(cols):
        shuffled = [row[:] for row in X]
        col_vals = [shuffled[r][col_idx] for r in range(rows)]
        rng.shuffle(col_vals)
        for r in range(rows):
            shuffled[r][col_idx] = col_vals[r]

        shuffled_scores = [float(s) for s in model.decision_function(shuffled)]
        mean_abs_change = sum(
            abs(base_scores[i] - shuffled_scores[i]) for i in range(rows)
        ) / float(rows)
        importances.append((FEATURE_NAMES[col_idx], mean_abs_change))

    importances.sort(key=lambda x: x[1], reverse=True)
    return importances


def _log_training_summary(cohort_key: str, model: Any, X: list[list[float]], seed: int) -> None:
    predictions = model.predict(X)
    anomalies = sum(1 for p in predictions if int(p) == -1)
    anomaly_rate = (anomalies / len(predictions)) * 100.0 if predictions is not None and len(predictions) > 0 else 0.0
    top3 = _permutation_feature_contributions(model, X, seed=seed)[:3]
    top3_text = ", ".join(f"{name}={score:.5f}" for name, score in top3) if top3 else "n/a"

    logger.info(
        "Cohort=%s | samples=%d | features=%d | anomaly_rate=%.2f%% | top3=%s",
        cohort_key,
        len(X),
        len(FEATURE_NAMES),
        anomaly_rate,
        top3_text,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Layer 3 Isolation Forest model")
    parser.add_argument("--data-dir", type=Path, default=Path("data/raw"), help="Raw declaration directory")
    parser.add_argument("--year", type=str, default=None, help="Optional year filter")
    parser.add_argument("--limit", type=int, default=0, help="Optional cap on number of declarations")
    parser.add_argument("--output", type=Path, default=None, help="Optional legacy output .pkl path for the global model")
    parser.add_argument("--contamination", type=float, default=0.05, help="IsolationForest contamination")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--min-samples", type=int, default=50, help="Deprecated: kept for CLI compatibility")
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=_default_model_dir(),
        help="Directory where Layer 3 model artifacts are stored",
    )
    parser.add_argument(
        "--min-cohort-size",
        type=int,
        default=30,
        help="Minimum declarations required to train a cohort model",
    )
    parser.add_argument(
        "--low-data-threshold",
        type=int,
        default=50,
        help="Cohorts with samples below this threshold are flagged as low_data",
    )
    args = parser.parse_args()

    try:
        from sklearn.ensemble import IsolationForest  # noqa: F401  # type: ignore[import-not-found]
        from sklearn.impute import SimpleImputer  # noqa: F401  # type: ignore[import-not-found]
        from sklearn.pipeline import Pipeline  # noqa: F401  # type: ignore[import-not-found]
        from sklearn.preprocessing import RobustScaler  # noqa: F401  # type: ignore[import-not-found]
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

    full_entries: list[dict[str, Any]] = []
    for f in files:
        raw = load_declaration(f)
        full = process_declaration_full(raw)
        full_entries.append(full)

    if len(full_entries) < 2:
        raise SystemExit("Not enough samples for training (< 2).")

    delta_by_decl = _compute_timeline_deltas(full_entries)

    rows: list[dict[str, Any]] = []
    for full in full_entries:
        features = full.get("features") or {}
        ownership_summary = compute_ownership_summary(
            list(full.get("real_estate") or []),
            list(full.get("vehicles") or []),
            list(full.get("bank_accounts") or []),
        )
        deltas = delta_by_decl.get(str(full.get("declaration_id") or ""), DELTA_FEATURE_DEFAULTS)
        feature_map = build_feature_vector(
            total_income=features.get("total_income"),
            total_assets=features.get("total_assets"),
            cash_holdings=features.get("cash"),
            bank_deposits=features.get("bank"),
            total_value_fields=int(features.get("total_value_fields") or 0),
            unknown_value_fields=int(features.get("unknown_value_fields") or 0),
            ownership_declarant=ownership_summary.declarant_items,
            ownership_family=ownership_summary.family_items,
            ownership_total=ownership_summary.total_items,
            declaration_year=full.get("declaration_year"),
            incomes_count=len(full.get("incomes", [])),
            real_estate_count=len(full.get("real_estate", [])),
            vehicles_count=len(full.get("vehicles", [])),
            monetary_count=len(full.get("monetary", [])),
            confidential_ratio=float(features.get("confidential_ratio") or 0.0),
            income_yoy_delta_pct=float(deltas.get("income_yoy_delta_pct", 0.0)),
            assets_yoy_delta_pct=float(deltas.get("assets_yoy_delta_pct", 0.0)),
            cash_ratio_yoy_delta=float(deltas.get("cash_ratio_yoy_delta", 0.0)),
            confidential_ratio_yoy_delta=float(deltas.get("confidential_ratio_yoy_delta", 0.0)),
            asset_income_ratio_delta=float(deltas.get("asset_income_ratio_delta", 0.0)),
            new_property_count=float(deltas.get("new_property_count", 0.0)),
            dropped_property_count=float(deltas.get("dropped_property_count", 0.0)),
            max_single_asset_jump_pct=float(deltas.get("max_single_asset_jump_pct", 0.0)),
        )

        taxonomy = full.get("cohort_taxonomy") or {}
        sector = _slug(
            str(
                full.get("_sector")
                or taxonomy.get("sector")
                or "other"
            )
        )
        government_level = _slug(
            str(
                full.get("_government_level")
                or taxonomy.get("government_level")
                or "other"
            )
        )

        rows.append(
            {
                "declaration_id": str(full.get("declaration_id") or ""),
                "cohort_key": f"{sector}_{government_level}",
                "feature_map": feature_map,
            }
        )

    matrix = [[r["feature_map"].get(name, 0.0) for name in FEATURE_NAMES] for r in rows]
    if len(matrix) < args.min_samples:
        logger.warning(
            "Sample count %d is below --min-samples=%d, but training proceeds to keep global fallback available.",
            len(matrix),
            args.min_samples,
        )

    model_dir = Path(args.model_dir)
    if model_dir.suffix.lower() == ".pkl":
        model_dir = model_dir.parent
    model_dir.mkdir(parents=True, exist_ok=True)

    registry: dict[str, Any] = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "global": {},
        "cohorts": {},
    }

    global_model = _train_pipeline(matrix, contamination=args.contamination, seed=args.seed)
    global_name = "layer3_global.pkl"
    global_path = model_dir / global_name
    with global_path.open("wb") as fh:
        pickle.dump(global_model, fh)

    _log_training_summary("global", global_model, matrix, args.seed)
    registry["global"] = {
        "path": global_name,
        "n_samples": len(matrix),
        "feature_names": FEATURE_NAMES,
        "contamination": args.contamination,
    }

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("wb") as fh:
            pickle.dump(global_model, fh)
        logger.info("Legacy global model output written to %s", args.output)

    cohort_rows: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        cohort_rows.setdefault(str(row["cohort_key"]), []).append(row)

    for cohort_key, members in sorted(cohort_rows.items(), key=lambda kv: kv[0]):
        n_samples = len(members)
        if n_samples < args.min_cohort_size:
            logger.warning(
                "Skipping cohort %s due to insufficient data (%d < %d).",
                cohort_key,
                n_samples,
                args.min_cohort_size,
            )
            continue

        cohort_matrix = [
            [m["feature_map"].get(name, 0.0) for name in FEATURE_NAMES]
            for m in members
        ]
        cohort_model = _train_pipeline(
            cohort_matrix,
            contamination=args.contamination,
            seed=args.seed,
        )

        model_name = f"layer3_{cohort_key}.pkl"
        model_path = model_dir / model_name
        with model_path.open("wb") as fh:
            pickle.dump(cohort_model, fh)

        low_data = n_samples < args.low_data_threshold
        _log_training_summary(cohort_key, cohort_model, cohort_matrix, args.seed)
        registry["cohorts"][cohort_key] = {
            "path": model_name,
            "n_samples": n_samples,
            "feature_names": FEATURE_NAMES,
            "contamination": args.contamination,
            "low_data": low_data,
        }

    registry_path = model_dir / "layer3_registry.json"
    registry_path.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info(
        "Trained Layer 3 models: global + %d cohort models -> %s",
        len(registry["cohorts"]),
        model_dir,
    )


if __name__ == "__main__":
    main()
