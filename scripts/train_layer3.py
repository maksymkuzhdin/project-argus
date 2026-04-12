"""Train Layer 3 Isolation Forest artifacts (global + per-cohort) from DB data.

This script reads processed declarations from PostgreSQL, builds the canonical
Layer 3 feature vectors, trains:
- a global fallback model, and
- per-cohort models for sufficiently large cohorts.

Artifacts are saved to --model-dir and indexed by layer3_registry.json.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import pickle
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.db.models import (  # type: ignore[import-not-found]
    BankAccount,
    DeclarantProfile,
    IncomeEntry,
    MonetaryAsset,
    RealEstateAsset,
    Vehicle,
)
from app.db.session import SessionLocal  # type: ignore[import-not-found]
from app.features.cash import classify_monetary_assets  # type: ignore[import-not-found]
from app.features.income import compute_total_income  # type: ignore[import-not-found]
from app.features.ownership import compute_ownership_summary  # type: ignore[import-not-found]
from app.features.wealth import compute_total_assets  # type: ignore[import-not-found]
from app.normalization.assemble_timeline import assemble_timeline  # type: ignore[import-not-found]
from app.scoring.cohort_taxonomy import (  # type: ignore[import-not-found]
    TaxonomyNormalizer,
    create_normalizer_from_config,
)


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


@dataclass
class TrainingRow:
    declaration_id: str
    cohort_key: str
    feature_map: dict[str, float]


@dataclass
class TrainSummaryRow:
    cohort_key: str
    n_train: int
    contamination: float
    artifact_path: str


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


def _count_unknowns(rows_list: list[list[dict[str, Any]]]) -> tuple[int, int]:
    total = 0
    unknown = 0
    status_fields = [
        "amount_status",
        "total_area_status",
        "cost_assessment_status",
        "organization_status",
    ]
    for rows in rows_list:
        for row in rows:
            for sf in status_fields:
                if sf in row:
                    total += 1
                    if row[sf] is not None:
                        unknown += 1
    return total, unknown


def _count_confidentials(rows_list: list[list[dict[str, Any]]]) -> tuple[int, int]:
    total = 0
    confidential = 0
    status_fields = [
        "amount_status",
        "total_area_status",
        "cost_assessment_status",
        "organization_status",
    ]
    confidential_statuses = {"confidential", "redacted_other"}

    for rows in rows_list:
        for row in rows:
            for sf in status_fields:
                if sf in row:
                    total += 1
                    if str(row.get(sf) or "") in confidential_statuses:
                        confidential += 1
    return total, confidential


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


def _max_single_asset_jump_pct(
    prev_assets: dict[str, Decimal],
    curr_assets: dict[str, Decimal],
) -> float:
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
            prev_cash_ratio = (
                (prev_cash / (prev_cash + prev_bank))
                if (prev_cash + prev_bank) > 0
                else 0.0
            )
            curr_cash_ratio = (
                (curr_cash / (curr_cash + curr_bank))
                if (curr_cash + curr_bank) > 0
                else 0.0
            )

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
                "max_single_asset_jump_pct": _max_single_asset_jump_pct(
                    prev.major_assets,
                    curr.major_assets,
                ),
            }

    return deltas_by_declaration


def _auto_contamination(n_samples: int) -> float:
    if n_samples <= 0:
        return 0.02
    return min(0.15, max(0.02, 1.0 / math.sqrt(float(n_samples))))


def _to_float_list(values: Any) -> list[float]:
    if values is None:
        return []
    return [float(v) for v in values]


def _train_artifact(X: list[list[float]], contamination: float) -> dict[str, Any]:
    from sklearn.ensemble import IsolationForest  # type: ignore[import-not-found]
    from sklearn.pipeline import Pipeline  # type: ignore[import-not-found]
    from sklearn.preprocessing import RobustScaler  # type: ignore[import-not-found]

    pipeline = Pipeline(
        steps=[
            ("scaler", RobustScaler()),
            (
                "iso",
                IsolationForest(
                    contamination=contamination,
                    random_state=42,
                    n_estimators=200,
                ),
            ),
        ]
    )
    pipeline.fit(X)

    scores = [float(v) for v in pipeline.decision_function(X)]
    decision_min = min(scores) if scores else 0.0
    decision_max = max(scores) if scores else 0.0

    scaler = pipeline.named_steps.get("scaler")
    medians = _to_float_list(getattr(scaler, "center_", []))
    scales = _to_float_list(getattr(scaler, "scale_", []))

    return {
        "model": pipeline,
        "feature_order": list(FEATURE_NAMES),
        "decision_min": float(decision_min),
        "decision_max": float(decision_max),
        "robust_medians": medians,
        "robust_scales": scales,
    }


def _taxonomy_normalizer() -> TaxonomyNormalizer:
    yaml_path = (
        Path(__file__).resolve().parent.parent
        / "backend"
        / "app"
        / "scoring"
        / "cohort_taxonomy.yaml"
    )
    return create_normalizer_from_config(str(yaml_path))


def _profile_to_bio(profile: DeclarantProfile) -> dict[str, Any]:
    return {
        "firstname": profile.firstname,
        "lastname": profile.lastname,
        "middlename": profile.middlename,
        "work_post": profile.work_post,
        "work_place": profile.work_place,
        "post_type": profile.post_type,
        "post_category": profile.post_category,
    }


def _income_to_dict(row: IncomeEntry) -> dict[str, Any]:
    return {
        "person_ref": row.person_ref,
        "income_type": row.income_type,
        "income_type_other": row.income_type_other,
        "amount": float(row.amount) if row.amount is not None else None,
        "amount_raw": row.amount_raw,
        "amount_status": row.amount_status,
        "source_name": row.source_name,
        "source_code": row.source_code,
        "source_type": row.source_type,
    }


def _monetary_to_dict(row: MonetaryAsset) -> dict[str, Any]:
    return {
        "person_ref": row.person_ref,
        "asset_type": row.asset_type,
        "currency_raw": row.currency_raw,
        "currency_code": row.currency_code,
        "amount": float(row.amount) if row.amount is not None else None,
        "amount_raw": row.amount_raw,
        "amount_status": None,
        "organization": row.organization,
        "organization_status": row.organization_status,
        "ownership_type": row.ownership_type,
    }


def _real_estate_to_dict(row: RealEstateAsset) -> dict[str, Any]:
    return {
        "object_type": row.object_type,
        "other_object_type": row.other_object_type,
        "total_area": float(row.total_area) if row.total_area is not None else None,
        "total_area_raw": row.total_area_raw,
        "total_area_status": row.total_area_status,
        "cost_assessment": float(row.cost_assessment) if row.cost_assessment is not None else None,
        "cost_assessment_raw": row.cost_assessment_raw,
        "cost_assessment_status": row.cost_assessment_status,
        "owning_date": row.owning_date,
        "right_belongs_raw": row.right_belongs_raw,
        "right_belongs_resolved": row.right_belongs_resolved,
        "ownership_type": row.ownership_type,
        "percent_ownership": row.percent_ownership,
        "country": row.country,
        "region": row.region,
        "district": row.district,
        "community": row.community,
        "city": row.city,
        "city_type": row.city_type,
    }


def _vehicle_to_dict(row: Vehicle) -> dict[str, Any]:
    return {
        "object_type": row.object_type,
        "brand": row.brand,
        "model": row.model,
        "graduation_year": row.graduation_year,
        "owning_date": row.owning_date,
        "cost_date": float(row.cost_date) if row.cost_date is not None else None,
        "ownership_type": row.ownership_type,
        "right_belongs_resolved": row.right_belongs_resolved,
    }


def _bank_to_dict(row: BankAccount) -> dict[str, Any]:
    return {
        "institution_name": row.institution_name,
        "institution_code": row.institution_code,
        "account_owner_resolved": row.account_owner_resolved,
    }


def _load_full_entries_from_db() -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        profiles = (
            db.query(DeclarantProfile)
            .order_by(DeclarantProfile.declaration_year.asc().nullslast())
            .all()
        )

        full_entries: list[dict[str, Any]] = []
        for profile in profiles:
            decl_id = profile.declaration_id
            if not decl_id:
                continue

            incomes = [
                _income_to_dict(r)
                for r in db.query(IncomeEntry)
                .filter(IncomeEntry.declaration_id == decl_id)
                .all()
            ]
            monetary = [
                _monetary_to_dict(r)
                for r in db.query(MonetaryAsset)
                .filter(MonetaryAsset.declaration_id == decl_id)
                .all()
            ]
            real_estate = [
                _real_estate_to_dict(r)
                for r in db.query(RealEstateAsset)
                .filter(RealEstateAsset.declaration_id == decl_id)
                .all()
            ]
            vehicles = [
                _vehicle_to_dict(r)
                for r in db.query(Vehicle)
                .filter(Vehicle.declaration_id == decl_id)
                .all()
            ]
            bank_accounts = [
                _bank_to_dict(r)
                for r in db.query(BankAccount)
                .filter(BankAccount.declaration_id == decl_id)
                .all()
            ]

            total_income = compute_total_income(incomes)
            total_assets = compute_total_assets(real_estate, monetary)
            cash_bank = classify_monetary_assets(monetary)
            ownership = compute_ownership_summary(real_estate, vehicles, bank_accounts)

            total_fields, unknown_fields = _count_unknowns([incomes, monetary, real_estate])
            conf_total_fields, confidential_fields = _count_confidentials(
                [incomes, monetary, real_estate]
            )
            confidential_ratio = (
                confidential_fields / conf_total_fields if conf_total_fields > 0 else 0.0
            )

            full_entries.append(
                {
                    "declaration_id": str(decl_id),
                    "user_declarant_id": profile.user_declarant_id,
                    "declaration_year": profile.declaration_year,
                    "declaration_type": profile.declaration_type,
                    "bio": _profile_to_bio(profile),
                    "real_estate": real_estate,
                    "vehicles": vehicles,
                    "bank_accounts": bank_accounts,
                    "incomes": incomes,
                    "monetary": monetary,
                    "ownership": ownership,
                    "features": {
                        "total_income": str(total_income) if total_income else None,
                        "total_assets": str(total_assets) if total_assets else None,
                        "cash": str(cash_bank.cash) if cash_bank.cash else None,
                        "bank": str(cash_bank.bank) if cash_bank.bank else None,
                        "total_value_fields": total_fields,
                        "unknown_value_fields": unknown_fields,
                        "confidential_ratio": confidential_ratio,
                    },
                }
            )

        return full_entries
    finally:
        db.close()


def _build_training_rows(
    full_entries: list[dict[str, Any]],
    normalizer: TaxonomyNormalizer,
) -> list[TrainingRow]:
    delta_by_decl = _compute_timeline_deltas(full_entries)
    rows: list[TrainingRow] = []

    for full in full_entries:
        features = full.get("features") or {}
        bio = full.get("bio") or {}
        ownership = full.get("ownership")

        work_post = str(bio.get("work_post") or "")
        work_place = str(bio.get("work_place") or "")
        post_type = str(bio.get("post_type") or "")
        post_category = str(bio.get("post_category") or "")

        norm = normalizer.normalize(
            work_post=work_post,
            work_place=work_place,
            post_type=post_type,
            post_category=post_category,
        )
        cohort_key = f"{_slug(norm.sector)}_{_slug(norm.government_level)}"

        deltas = delta_by_decl.get(
            str(full.get("declaration_id") or ""),
            DELTA_FEATURE_DEFAULTS,
        )

        feature_map = build_feature_vector(
            total_income=features.get("total_income"),
            total_assets=features.get("total_assets"),
            cash_holdings=features.get("cash"),
            bank_deposits=features.get("bank"),
            total_value_fields=int(features.get("total_value_fields") or 0),
            unknown_value_fields=int(features.get("unknown_value_fields") or 0),
            ownership_declarant=int(getattr(ownership, "declarant_items", 0)),
            ownership_family=int(getattr(ownership, "family_items", 0)),
            ownership_total=int(getattr(ownership, "total_items", 0)),
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

        rows.append(
            TrainingRow(
                declaration_id=str(full.get("declaration_id") or ""),
                cohort_key=cohort_key,
                feature_map=feature_map,
            )
        )

    return rows


def _print_summary_table(rows: list[TrainSummaryRow]) -> None:
    if not rows:
        logger.info("No artifacts were produced.")
        return

    key_w = max(len("cohort key"), max(len(r.cohort_key) for r in rows))
    n_w = max(len("n_train"), max(len(str(r.n_train)) for r in rows))
    c_w = max(
        len("contamination"),
        max(len(f"{r.contamination:.4f}") for r in rows),
    )

    header = (
        f"{'cohort key':<{key_w}} | {'n_train':>{n_w}} | "
        f"{'contamination':>{c_w}} | artifact path"
    )
    sep = "-" * len(header)
    print(header)
    print(sep)
    for row in rows:
        print(
            f"{row.cohort_key:<{key_w}} | {row.n_train:>{n_w}} | "
            f"{row.contamination:>{c_w}.4f} | {row.artifact_path}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train Layer 3 Isolation Forest models from DB",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path("backend/models"),
        help="Directory where Layer 3 model artifacts are stored",
    )
    parser.add_argument(
        "--min-cohort-samples",
        type=int,
        default=200,
        help="Minimum samples required to train a cohort-specific model",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print cohort sizes and exit without training or writing artifacts",
    )
    args = parser.parse_args()

    try:
        from sklearn.ensemble import IsolationForest  # noqa: F401  # type: ignore[import-not-found]
        from sklearn.pipeline import Pipeline  # noqa: F401  # type: ignore[import-not-found]
        from sklearn.preprocessing import RobustScaler  # noqa: F401  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover
        raise SystemExit(
            "scikit-learn is required. Install backend requirements before training."
        ) from exc

    full_entries = _load_full_entries_from_db()
    if not full_entries:
        raise SystemExit("No processed declarations found in database.")

    normalizer = _taxonomy_normalizer()
    training_rows = _build_training_rows(full_entries, normalizer)
    if not training_rows:
        raise SystemExit("No training rows could be constructed from DB data.")

    by_cohort: dict[str, list[TrainingRow]] = {}
    for row in training_rows:
        by_cohort.setdefault(row.cohort_key, []).append(row)

    qualifying_keys = {
        key for key, members in by_cohort.items() if len(members) >= args.min_cohort_samples
    }

    if args.dry_run:
        print("cohort key | n_train | qualifies")
        print("--------------------------------")
        for key in sorted(by_cohort.keys()):
            n = len(by_cohort[key])
            qualifies = "yes" if key in qualifying_keys else "no"
            print(f"{key} | {n} | {qualifies}")
        print(f"global | {len(training_rows)} | yes")
        return

    model_dir = Path(args.model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)

    registry: dict[str, Any] = {
        "global": {},
        "cohorts": {},
    }
    summary_rows: list[TrainSummaryRow] = []

    global_matrix = [
        [row.feature_map.get(name, 0.0) for name in FEATURE_NAMES]
        for row in training_rows
    ]
    global_contamination = _auto_contamination(len(global_matrix))
    global_artifact = _train_artifact(global_matrix, contamination=global_contamination)

    global_name = "layer3_global.pkl"
    global_path = model_dir / global_name
    with global_path.open("wb") as fh:
        pickle.dump(global_artifact, fh)

    registry["global"] = {
        "path": global_name,
        "n_train": len(global_matrix),
        "contamination": global_contamination,
    }
    summary_rows.append(
        TrainSummaryRow(
            cohort_key="global",
            n_train=len(global_matrix),
            contamination=global_contamination,
            artifact_path=global_name,
        )
    )

    for cohort_key in sorted(qualifying_keys):
        members = by_cohort[cohort_key]
        cohort_matrix = [
            [m.feature_map.get(name, 0.0) for name in FEATURE_NAMES]
            for m in members
        ]
        contamination = _auto_contamination(len(cohort_matrix))
        artifact = _train_artifact(cohort_matrix, contamination=contamination)

        model_name = f"layer3_{cohort_key}.pkl"
        model_path = model_dir / model_name
        with model_path.open("wb") as fh:
            pickle.dump(artifact, fh)

        registry["cohorts"][cohort_key] = {
            "path": model_name,
            "n_train": len(cohort_matrix),
            "contamination": contamination,
        }
        summary_rows.append(
            TrainSummaryRow(
                cohort_key=cohort_key,
                n_train=len(cohort_matrix),
                contamination=contamination,
                artifact_path=model_name,
            )
        )

    registry_path = model_dir / "layer3_registry.json"
    registry_path.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    _print_summary_table(summary_rows)

    small_cohort_total = sum(
        len(members)
        for key, members in by_cohort.items()
        if key not in qualifying_keys
    )
    logger.info(
        "Trained %d cohort models (+global). Non-qualifying cohort samples merged into global fallback: %d",
        len(qualifying_keys),
        small_cohort_total,
    )
    logger.info("Wrote Layer 3 artifacts and registry to %s", model_dir)


if __name__ == "__main__":
    main()
