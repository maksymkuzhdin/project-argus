#!/usr/bin/env python3
"""Project Argus - scoring diagnostics over persisted declarations.

Runs full Layer 1/2/3 scoring inputs against a DB sample and prints
calibration-focused statistics for score distributions, cohort behavior,
rule fire rates, and potential over-firing thresholds.

Usage:
    python scripts/evaluate_scoring.py
    python scripts/evaluate_scoring.py --sample-size 5000 --output-json output/evaluate_scoring.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

# Make the script runnable as a standalone from the backend dir
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "backend"))
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    BankAccount,
    DeclarantProfile,
    FamilyMember,
    IncomeEntry,
    MonetaryAsset,
    RealEstateAsset,
    Vehicle,
)
from app.db.session import SessionLocal
from app.features.cash import classify_monetary_assets
from app.features.income import compute_total_income
from app.features.ownership import compute_ownership_summary
from app.features.wealth import compute_largest_acquisition, compute_total_assets
from app.scoring import layer3 as layer3_inference
from app.scoring.cohort_taxonomy import create_normalizer_from_config
from app.scoring.rules import score_declaration


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("argus.evaluate_scoring")


RULE_IDS: list[str] = [
    *[f"CR{i}" for i in range(1, 17)],
    "BR1",
    *[f"TQ{i}" for i in range(1, 6)],
]


def _chunked(values: list[str], size: int = 900) -> list[list[str]]:
    return [values[idx: idx + size] for idx in range(0, len(values), size)]


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])

    s = sorted(values)
    rank = (len(s) - 1) * (p / 100.0)
    lo = int(rank)
    hi = min(lo + 1, len(s) - 1)
    frac = rank - lo
    return float(s[lo] + (s[hi] - s[lo]) * frac)


def _fmt_float(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "None"
    return f"{value:.{digits}f}"


def _fmt_pct(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "None"
    return f"{value * 100:.{digits}f}%"


def _income_to_dict(i: IncomeEntry) -> dict[str, Any]:
    return {
        "person_ref": i.person_ref,
        "income_type": i.income_type,
        "income_type_other": i.income_type_other,
        "amount": _to_decimal(i.amount),
        "amount_raw": i.amount_raw,
        "amount_status": i.amount_status,
        "source_name": i.source_name,
        "source_code": i.source_code,
        "source_type": i.source_type,
        "raw_iteration": i.raw_iteration,
    }


def _monetary_to_dict(m: MonetaryAsset) -> dict[str, Any]:
    return {
        "person_ref": m.person_ref,
        "asset_type": m.asset_type,
        "currency_raw": m.currency_raw,
        "currency_code": m.currency_code,
        "amount": _to_decimal(m.amount),
        "amount_raw": m.amount_raw,
        "organization": m.organization,
        "organization_status": m.organization_status,
        "ownership_type": m.ownership_type,
        "raw_iteration": m.raw_iteration,
    }


def _real_estate_to_dict(r: RealEstateAsset) -> dict[str, Any]:
    return {
        "object_type": r.object_type,
        "other_object_type": r.other_object_type,
        "total_area": _to_decimal(r.total_area),
        "total_area_raw": r.total_area_raw,
        "total_area_status": r.total_area_status,
        "cost_assessment": _to_decimal(r.cost_assessment),
        "cost_assessment_raw": r.cost_assessment_raw,
        "cost_assessment_status": r.cost_assessment_status,
        "owning_date": r.owning_date,
        "right_belongs_raw": r.right_belongs_raw,
        "right_belongs_resolved": r.right_belongs_resolved,
        "ownership_type": r.ownership_type,
        "percent_ownership": r.percent_ownership,
        "country": r.country,
        "region": r.region,
        "district": r.district,
        "community": r.community,
        "city": r.city,
        "city_type": r.city_type,
        "raw_iteration": r.raw_iteration,
    }


def _vehicle_to_dict(v: Vehicle) -> dict[str, Any]:
    return {
        "object_type": v.object_type,
        "brand": v.brand,
        "model": v.model,
        "graduation_year": v.graduation_year,
        "owning_date": v.owning_date,
        "cost_date": _to_decimal(v.cost_date),
        "ownership_type": v.ownership_type,
        "right_belongs_resolved": v.right_belongs_resolved,
        "raw_iteration": None,
    }


def _family_to_dict(f: FamilyMember) -> dict[str, Any]:
    return {
        "member_id": f.member_id,
        "relation": f.relation,
        "firstname": f.firstname,
        "lastname": f.lastname,
        "middlename": f.middlename,
    }


def _bank_to_dict(b: BankAccount) -> dict[str, Any]:
    return {
        "institution_name": b.institution_name,
        "institution_code": b.institution_code,
        "account_owner_resolved": b.account_owner_resolved,
        "raw_iteration": b.raw_iteration,
    }


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


def _confidential_ratio_from_rows(
    incomes: list[dict[str, Any]],
    monetary_assets: list[dict[str, Any]],
    real_estate: list[dict[str, Any]],
) -> float:
    status_fields = [
        "amount_status",
        "total_area_status",
        "cost_assessment_status",
        "organization_status",
    ]
    confidential_statuses = {"confidential", "redacted_other"}

    total = 0
    confidential = 0
    for rows in (incomes, monetary_assets, real_estate):
        for row in rows:
            for sf in status_fields:
                if sf in row:
                    total += 1
                    if str(row.get(sf) or "") in confidential_statuses:
                        confidential += 1
    if total == 0:
        return 0.0
    return confidential / total


def _load_profiles(db: Session, sample_size: int) -> tuple[list[DeclarantProfile], int, bool]:
    total = int(db.query(func.count(DeclarantProfile.id)).scalar() or 0)
    if total == 0:
        return [], total, False

    query = db.query(DeclarantProfile)
    sampled_random = total > sample_size
    if sampled_random:
        query = query.order_by(func.random()).limit(sample_size)
    else:
        query = query.limit(sample_size)

    return list(query.all()), total, sampled_random


def _load_table_map(
    db: Session,
    model: Any,
    declaration_ids: list[str],
) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = defaultdict(list)
    if not declaration_ids:
        return out

    for chunk in _chunked(declaration_ids):
        rows = (
            db.query(model)
            .filter(model.declaration_id.in_(chunk))
            .all()
        )
        for row in rows:
            out[str(row.declaration_id)].append(row)
    return out


def _load_normalizer() -> Any | None:
    yaml_path = Path(__file__).resolve().parent.parent / "app" / "scoring" / "cohort_taxonomy.yaml"
    try:
        return create_normalizer_from_config(str(yaml_path))
    except Exception as exc:
        logger.warning("Failed to initialize TaxonomyNormalizer from %s (%s)", yaml_path, exc)
        return None


def _score_sample(
    profiles: list[DeclarantProfile],
    db: Session,
    anomaly_threshold: float,
) -> dict[str, Any]:
    declaration_ids = [str(p.declaration_id) for p in profiles]

    family_by_id = _load_table_map(db, FamilyMember, declaration_ids)
    income_by_id = _load_table_map(db, IncomeEntry, declaration_ids)
    monetary_by_id = _load_table_map(db, MonetaryAsset, declaration_ids)
    real_estate_by_id = _load_table_map(db, RealEstateAsset, declaration_ids)
    vehicles_by_id = _load_table_map(db, Vehicle, declaration_ids)
    banks_by_id = _load_table_map(db, BankAccount, declaration_ids)

    normalizer = _load_normalizer()

    total_scores: list[float] = []
    cohort_scores: dict[str, list[float]] = defaultdict(list)

    rule_stats: dict[str, dict[str, Any]] = {
        rid: {
            "fire_count": 0,
            "fired_scores": [],
            "severity": Counter(),
        }
        for rid in RULE_IDS
    }

    layer3_present = False
    layer3_scores: list[float] = []
    layer3_hits_by_cohort: dict[str, int] = defaultdict(int)
    layer3_totals_by_cohort: dict[str, int] = defaultdict(int)
    top_deviation_counter: Counter[str] = Counter()

    n_total = len(profiles)
    n_scored = 0

    for idx, profile in enumerate(profiles, start=1):
        decl_id = str(profile.declaration_id)

        family_rows = [_family_to_dict(r) for r in family_by_id.get(decl_id, [])]
        income_rows = [_income_to_dict(r) for r in income_by_id.get(decl_id, [])]
        monetary_rows = [_monetary_to_dict(r) for r in monetary_by_id.get(decl_id, [])]
        real_estate_rows = [_real_estate_to_dict(r) for r in real_estate_by_id.get(decl_id, [])]
        vehicle_rows = [_vehicle_to_dict(r) for r in vehicles_by_id.get(decl_id, [])]
        bank_rows = [_bank_to_dict(r) for r in banks_by_id.get(decl_id, [])]

        total_income = compute_total_income(income_rows)
        total_assets = compute_total_assets(real_estate_rows, monetary_rows)
        cash_bank = classify_monetary_assets(monetary_rows)
        largest_acquisition = compute_largest_acquisition(real_estate_rows)
        ownership = compute_ownership_summary(real_estate_rows, vehicle_rows, bank_rows)
        total_fields, unknown_fields = _count_unknowns([income_rows, monetary_rows, real_estate_rows])
        confidential_ratio = _confidential_ratio_from_rows(income_rows, monetary_rows, real_estate_rows)

        sector = "other"
        government_level = "other"
        if normalizer is not None:
            try:
                norm = normalizer.normalize(
                    work_post=str(profile.work_post or ""),
                    work_place=profile.work_place,
                    post_type=profile.post_type,
                    post_category=profile.post_category,
                )
                sector = str(norm.sector or "other")
                government_level = str(norm.government_level or "other")
            except Exception as exc:
                logger.warning("Taxonomy normalization failed for %s (%s)", decl_id, exc)

        cohort_key = f"{sector}_{government_level}"

        result = score_declaration(
            total_income=total_income,
            total_assets=total_assets,
            cash_holdings=cash_bank.cash,
            bank_deposits=cash_bank.bank,
            total_value_fields=total_fields,
            unknown_value_fields=unknown_fields,
            largest_acquisition_cost=largest_acquisition,
            ownership_declarant=ownership.declarant_items,
            ownership_family=ownership.family_items,
            ownership_total=ownership.total_items,
            incomes=income_rows,
            monetary_assets=monetary_rows,
            real_estate=real_estate_rows,
            vehicles=vehicle_rows,
            family_members=family_rows,
            declaration_year=profile.declaration_year,
            raw_declaration={"id": decl_id},
            declaration_sector=sector,
            declaration_gov_level=government_level,
        )

        total_score = _to_float(result.total_score)
        total_scores.append(total_score)
        cohort_scores[cohort_key].append(total_score)

        for rr in result.rule_results:
            if rr.rule_name not in rule_stats:
                continue
            if not rr.triggered:
                continue
            rule_stats[rr.rule_name]["fire_count"] += 1
            rule_stats[rr.rule_name]["fired_scores"].append(_to_float(rr.score))
            sev = str(rr.severity or "UNKNOWN")
            rule_stats[rr.rule_name]["severity"][sev] += 1

        try:
            feature_map = layer3_inference.build_feature_vector(
                total_income=total_income,
                total_assets=total_assets,
                cash_holdings=cash_bank.cash,
                bank_deposits=cash_bank.bank,
                total_value_fields=total_fields,
                unknown_value_fields=unknown_fields,
                ownership_declarant=ownership.declarant_items,
                ownership_family=ownership.family_items,
                ownership_total=ownership.total_items,
                declaration_year=profile.declaration_year,
                incomes_count=len(income_rows),
                real_estate_count=len(real_estate_rows),
                vehicles_count=len(vehicle_rows),
                monetary_count=len(monetary_rows),
                confidential_ratio=confidential_ratio,
            )
            layer3_result = layer3_inference.infer_anomaly(
                feature_map=feature_map,
                model_path=str(getattr(settings, "layer3_model_path", "") or ""),
                sector=sector,
                government_level=government_level,
            )
        except Exception:
            layer3_result = None

        if layer3_result is not None:
            layer3_present = True
            layer3_score = _to_float(layer3_result.anomaly_score)
            layer3_scores.append(layer3_score)
            layer3_totals_by_cohort[cohort_key] += 1
            if layer3_score >= anomaly_threshold:
                layer3_hits_by_cohort[cohort_key] += 1
                for dev in layer3_result.top_deviations:
                    feat = str(dev.get("feature_name") or "")
                    if feat:
                        top_deviation_counter[feat] += 1

        n_scored += 1
        if idx % 1000 == 0 or idx == n_total:
            logger.info("Scored %d/%d declarations...", idx, n_total)

    return {
        "n_scored": n_scored,
        "total_scores": total_scores,
        "cohort_scores": cohort_scores,
        "rule_stats": rule_stats,
        "layer3_present": layer3_present,
        "layer3_scores": layer3_scores,
        "layer3_hits_by_cohort": layer3_hits_by_cohort,
        "layer3_totals_by_cohort": layer3_totals_by_cohort,
        "top_deviation_counter": top_deviation_counter,
    }


def _build_report(
    *,
    scored: dict[str, Any],
    cohort_min_n: int,
    anomaly_threshold: float,
) -> dict[str, Any]:
    total_scores = scored["total_scores"]
    cohort_scores = scored["cohort_scores"]
    rule_stats = scored["rule_stats"]
    layer3_present = bool(scored["layer3_present"])
    layer3_scores = scored["layer3_scores"]
    layer3_hits_by_cohort = scored["layer3_hits_by_cohort"]
    layer3_totals_by_cohort = scored["layer3_totals_by_cohort"]
    top_deviation_counter = scored["top_deviation_counter"]
    n_scored = int(scored["n_scored"])

    overall = {
        "min": min(total_scores) if total_scores else None,
        "p5": _percentile(total_scores, 5),
        "p25": _percentile(total_scores, 25),
        "p50": _percentile(total_scores, 50),
        "p75": _percentile(total_scores, 75),
        "p95": _percentile(total_scores, 95),
        "max": max(total_scores) if total_scores else None,
    }

    cohort_rows: list[dict[str, Any]] = []
    for cohort_key, scores in sorted(cohort_scores.items()):
        n = len(scores)
        if n < cohort_min_n:
            continue
        anomaly_rate = None
        if layer3_present:
            total = int(layer3_totals_by_cohort.get(cohort_key, 0))
            hits = int(layer3_hits_by_cohort.get(cohort_key, 0))
            anomaly_rate = (hits / total) if total > 0 else 0.0
        cohort_rows.append(
            {
                "cohort_key": cohort_key,
                "n": n,
                "p50": _percentile(scores, 50),
                "p95": _percentile(scores, 95),
                "anomaly_rate": anomaly_rate,
            }
        )

    rule_rows: list[dict[str, Any]] = []
    for rid in RULE_IDS:
        rs = rule_stats[rid]
        fire_count = int(rs["fire_count"])
        fire_rate = (fire_count / n_scored) if n_scored > 0 else 0.0
        fired_scores = list(rs["fired_scores"])
        mean_fired = (sum(fired_scores) / len(fired_scores)) if fired_scores else None
        severity_counter: Counter[str] = rs["severity"]
        severity_sorted = sorted(
            severity_counter.items(),
            key=lambda x: (-x[1], x[0]),
        )

        rule_rows.append(
            {
                "rule_id": rid,
                "fire_count": fire_count,
                "fire_rate": fire_rate,
                "mean_score_when_fired": mean_fired,
                "top_severity_distribution": [
                    {"severity": sev, "count": cnt}
                    for sev, cnt in severity_sorted
                ],
            }
        )

    rule_rows.sort(key=lambda x: (-x["fire_rate"], x["rule_id"]))

    layer3_section: dict[str, Any]
    if layer3_present:
        per_cohort = []
        for cohort_key in sorted(layer3_totals_by_cohort.keys()):
            total = int(layer3_totals_by_cohort[cohort_key])
            hits = int(layer3_hits_by_cohort.get(cohort_key, 0))
            rate = (hits / total) if total > 0 else 0.0
            per_cohort.append(
                {
                    "cohort_key": cohort_key,
                    "anomaly_rate": rate,
                    "n": total,
                }
            )

        layer3_section = {
            "available": True,
            "global_p50": _percentile(layer3_scores, 50),
            "global_p95": _percentile(layer3_scores, 95),
            "per_cohort_anomaly_rate": per_cohort,
            "top_deviations_among_anomalies": [
                {"feature_name": feat, "count": cnt}
                for feat, cnt in top_deviation_counter.most_common(3)
            ],
            "anomaly_threshold": anomaly_threshold,
        }
    else:
        layer3_section = {
            "available": False,
            "note": "Layer 3 model artifacts unavailable (or could not be loaded).",
            "anomaly_threshold": anomaly_threshold,
        }

    over_firing = [
        {
            "rule_id": row["rule_id"],
            "fire_rate": row["fire_rate"],
            "fire_count": row["fire_count"],
        }
        for row in rule_rows
        if row["fire_rate"] > 0.30
    ]

    return {
        "overall_distribution": overall,
        "cohort_distribution": cohort_rows,
        "rule_fire_rates": rule_rows,
        "layer3_stats": layer3_section,
        "potential_over_firing_alert": over_firing,
    }


def _print_report(report: dict[str, Any], *, anomaly_threshold: float) -> None:
    print("\n=== 1) Overall score distribution ===")
    overall = report["overall_distribution"]
    print(
        "min={minv} p5={p5} p25={p25} p50={p50} p75={p75} p95={p95} max={maxv}".format(
            minv=_fmt_float(overall["min"]),
            p5=_fmt_float(overall["p5"]),
            p25=_fmt_float(overall["p25"]),
            p50=_fmt_float(overall["p50"]),
            p75=_fmt_float(overall["p75"]),
            p95=_fmt_float(overall["p95"]),
            maxv=_fmt_float(overall["max"]),
        )
    )

    print("\n=== 2) Cohort-stratified score distribution ===")
    cohorts = report["cohort_distribution"]
    if not cohorts:
        print("No cohorts met the minimum sample threshold.")
    else:
        print("cohort_key | n | p50 | p95 | anomaly_rate")
        for row in cohorts:
            print(
                f"{row['cohort_key']} | {row['n']} | {_fmt_float(row['p50'])} | "
                f"{_fmt_float(row['p95'])} | {_fmt_pct(row['anomaly_rate'])}"
            )

    print("\n=== 3) Rule fire-rate table ===")
    print("rule_id | fire_count | fire_rate | mean_score_when_fired | top_severity_distribution")
    for row in report["rule_fire_rates"]:
        dist = row["top_severity_distribution"]
        if dist:
            dist_text = ", ".join(f"{d['severity']}:{d['count']}" for d in dist)
        else:
            dist_text = "-"
        print(
            f"{row['rule_id']} | {row['fire_count']} | {_fmt_pct(row['fire_rate'])} | "
            f"{_fmt_float(row['mean_score_when_fired'], 3)} | {dist_text}"
        )

    print("\n=== 4) Layer 3 stats ===")
    layer3 = report["layer3_stats"]
    if not layer3["available"]:
        print(layer3["note"])
    else:
        print(
            f"Global anomaly score: p50={_fmt_float(layer3['global_p50'], 4)} "
            f"p95={_fmt_float(layer3['global_p95'], 4)}"
        )
        print(f"Per-cohort anomaly rate (threshold >= {anomaly_threshold}):")
        for row in layer3["per_cohort_anomaly_rate"]:
            print(
                f"  {row['cohort_key']} | n={row['n']} | anomaly_rate={_fmt_pct(row['anomaly_rate'])}"
            )
        top = layer3["top_deviations_among_anomalies"]
        if top:
            print("Top 3 most common top_deviations features among anomalies:")
            for item in top:
                print(f"  {item['feature_name']}: {item['count']}")
        else:
            print("No anomalies crossed the threshold; no top_deviations to report.")

    print("\n=== 5) Potential over-firing alert ===")
    alerts = report["potential_over_firing_alert"]
    if not alerts:
        print("No rule exceeded 30% fire rate.")
    else:
        print("The following rules fired in >30% of records and may need threshold review:")
        for row in alerts:
            print(f"  {row['rule_id']}: fire_rate={_fmt_pct(row['fire_rate'])} (n={row['fire_count']})")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Argus scoring over a DB sample")
    parser.add_argument(
        "--sample-size",
        type=int,
        default=10_000,
        help="Maximum number of declarations to score (default: 10000)",
    )
    parser.add_argument(
        "--cohort-min-n",
        type=int,
        default=20,
        help="Minimum cohort size for cohort-level table (default: 20)",
    )
    parser.add_argument(
        "--anomaly-threshold",
        type=float,
        default=0.7,
        help="Threshold for Layer 3 anomaly-rate stats (default: 0.7)",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional path to write machine-readable JSON output",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.sample_size <= 0:
        raise ValueError("--sample-size must be > 0")
    if args.cohort_min_n <= 0:
        raise ValueError("--cohort-min-n must be > 0")
    if args.anomaly_threshold < 0 or args.anomaly_threshold > 1:
        raise ValueError("--anomaly-threshold must be in [0, 1]")

    db = SessionLocal()
    try:
        profiles, total_in_db, sampled_random = _load_profiles(db, args.sample_size)
        if not profiles:
            print("No persisted declarations found in DB.")
            return

        logger.info(
            "Loaded %d declarations from DB (total=%d, sampled_random=%s)",
            len(profiles),
            total_in_db,
            sampled_random,
        )

        scored = _score_sample(
            profiles,
            db,
            anomaly_threshold=float(args.anomaly_threshold),
        )

        report = _build_report(
            scored=scored,
            cohort_min_n=int(args.cohort_min_n),
            anomaly_threshold=float(args.anomaly_threshold),
        )

        _print_report(report, anomaly_threshold=float(args.anomaly_threshold))

        if args.output_json is not None:
            payload = {
                "meta": {
                    "sample_size_requested": int(args.sample_size),
                    "sample_size_scored": int(scored["n_scored"]),
                    "total_declarations_in_db": int(total_in_db),
                    "sampled_random": bool(sampled_random),
                    "cohort_min_n": int(args.cohort_min_n),
                    "anomaly_threshold": float(args.anomaly_threshold),
                    "layer3_model_path": str(getattr(settings, "layer3_model_path", "") or ""),
                },
                "report": report,
            }
            args.output_json.parent.mkdir(parents=True, exist_ok=True)
            args.output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("Wrote JSON report: %s", args.output_json)
    finally:
        db.close()


if __name__ == "__main__":
    main()