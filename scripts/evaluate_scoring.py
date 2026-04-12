#!/usr/bin/env python3
"""
Evaluate the full anomaly scoring pipeline over a sample of stored declarations.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy.sql.expression import func

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

from app.db.models import (
    DeclarantProfile,
    IncomeEntry,
    MonetaryAsset,
    RealEstateAsset,
    Vehicle,
    BankAccount,
    FamilyMember,
)
from app.db.session import SessionLocal
from app.features.cash import classify_monetary_assets
from app.features.income import compute_total_income
from app.features.ownership import compute_ownership_summary
from app.features.wealth import compute_total_assets
from app.scoring.cohort_taxonomy import TaxonomyNormalizer, create_normalizer_from_config
from app.scoring.rules import score_declaration
from app.scoring.layer3 import build_feature_vector, infer_anomaly, resolve_model

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


def _to_dict_income(r: IncomeEntry) -> dict[str, Any]:
    return {
        "person_ref": r.person_ref,
        "income_type": r.income_type,
        "income_type_other": r.income_type_other,
        "amount": float(r.amount) if r.amount is not None else None,
        "amount_raw": r.amount_raw,
        "amount_status": r.amount_status,
        "source_name": r.source_name,
        "source_code": r.source_code,
        "source_type": r.source_type,
    }


def _to_dict_monetary(r: MonetaryAsset) -> dict[str, Any]:
    return {
        "person_ref": r.person_ref,
        "asset_type": r.asset_type,
        "currency_raw": r.currency_raw,
        "currency_code": r.currency_code,
        "amount": float(r.amount) if r.amount is not None else None,
        "amount_raw": r.amount_raw,
        "amount_status": None,
        "organization": r.organization,
        "organization_status": r.organization_status,
        "ownership_type": r.ownership_type,
    }


def _to_dict_real_estate(r: RealEstateAsset) -> dict[str, Any]:
    return {
        "object_type": r.object_type,
        "other_object_type": r.other_object_type,
        "total_area": float(r.total_area) if r.total_area is not None else None,
        "total_area_raw": r.total_area_raw,
        "total_area_status": r.total_area_status,
        "cost_assessment": float(r.cost_assessment) if r.cost_assessment is not None else None,
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
    }


def _to_dict_vehicle(r: Vehicle) -> dict[str, Any]:
    return {
        "object_type": r.object_type,
        "brand": r.brand,
        "model": r.model,
        "graduation_year": r.graduation_year,
        "owning_date": r.owning_date,
        "cost_date": float(r.cost_date) if r.cost_date is not None else None,
        "ownership_type": r.ownership_type,
        "right_belongs_resolved": r.right_belongs_resolved,
    }


def _to_dict_bank(r: BankAccount) -> dict[str, Any]:
    return {
        "institution_name": r.institution_name,
        "institution_code": r.institution_code,
        "account_owner_resolved": r.account_owner_resolved,
    }


def _to_dict_family(r: FamilyMember) -> dict[str, Any]:
    return {
        "member_id": r.member_id,
        "relation": r.relation,
        "firstname": r.firstname,
        "lastname": r.lastname,
        "middlename": r.middlename,
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


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(values, q))


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate anomaly scoring pipeline against stored DB declarations.")
    parser.add_argument("--sample-size", type=int, default=10000, help="Number of declarations to score (randomly sampled)")
    parser.add_argument("--cohort-min-n", type=int, default=20, help="Minimum records to show cohort-stratified stats")
    parser.add_argument("--anomaly-threshold", type=float, default=0.7, help="Threshold for Layer 3 anomaly rate")
    parser.add_argument("--output-json", type=Path, default=None, help="Optional path to write raw JSON results")
    args = parser.parse_args()

    yaml_path = Path(__file__).resolve().parent.parent / "backend" / "app" / "scoring" / "cohort_taxonomy.yaml"
    normalizer = create_normalizer_from_config(str(yaml_path))

    logger.info(f"Connecting to database to sample up to {args.sample_size} declarations...")
    db = SessionLocal()
    try:
        # Check total count
        total_decls = db.query(DeclarantProfile).count()
        if total_decls == 0:
            logger.error("No declarations found in the database.")
            return
        
        logger.info(f"Database has {total_decls} total declarations.")

        if total_decls <= args.sample_size:
            profiles = db.query(DeclarantProfile).all()
        else:
            profiles = db.query(DeclarantProfile).order_by(func.random()).limit(args.sample_size).all()
        
        decl_ids = [p.declaration_id for p in profiles if p.declaration_id]
        if not decl_ids:
            logger.error("Sampled declarations have no IDs.")
            return

        logger.info(f"Sampled {len(decl_ids)} declarations. Fetching related records.")

        # Batch fetch related
        incomes_raw = db.query(IncomeEntry).filter(IncomeEntry.declaration_id.in_(decl_ids)).all()
        monetary_raw = db.query(MonetaryAsset).filter(MonetaryAsset.declaration_id.in_(decl_ids)).all()
        re_raw = db.query(RealEstateAsset).filter(RealEstateAsset.declaration_id.in_(decl_ids)).all()
        vehicles_raw = db.query(Vehicle).filter(Vehicle.declaration_id.in_(decl_ids)).all()
        banks_raw = db.query(BankAccount).filter(BankAccount.declaration_id.in_(decl_ids)).all()
        families_raw = db.query(FamilyMember).filter(FamilyMember.declaration_id.in_(decl_ids)).all()
    finally:
        db.close()

    logger.info("Organizing related records by declaration ID...")

    incs_by_id = defaultdict(list)
    for r in incomes_raw: incs_by_id[r.declaration_id].append(_to_dict_income(r))
    mons_by_id = defaultdict(list)
    for r in monetary_raw: mons_by_id[r.declaration_id].append(_to_dict_monetary(r))
    res_by_id = defaultdict(list)
    for r in re_raw: res_by_id[r.declaration_id].append(_to_dict_real_estate(r))
    vehs_by_id = defaultdict(list)
    for r in vehicles_raw: vehs_by_id[r.declaration_id].append(_to_dict_vehicle(r))
    anks_by_id = defaultdict(list)
    for r in banks_raw: anks_by_id[r.declaration_id].append(_to_dict_bank(r))
    fams_by_id = defaultdict(list)
    for r in families_raw: fams_by_id[r.declaration_id].append(_to_dict_family(r))

    logger.info(f"Starting scoring for {len(profiles)} profiles...")

    results = []
    layer3_available = False

    for idx, profile in enumerate(profiles, start=1):
        if idx % 1000 == 0:
            logger.info(f"Scored {idx}/{len(profiles)}...")

        did = profile.declaration_id
        incomes = incs_by_id[did]
        monetary = mons_by_id[did]
        real_estate = res_by_id[did]
        vehicles = vehs_by_id[did]
        bank_accounts = anks_by_id[did]
        family_members = fams_by_id[did]

        total_income = compute_total_income(incomes)
        total_assets = compute_total_assets(real_estate, monetary)
        cash_bank = classify_monetary_assets(monetary)
        ownership = compute_ownership_summary(real_estate, vehicles, bank_accounts)

        total_fields, unknown_fields = _count_unknowns([incomes, monetary, real_estate])
        conf_total, conf_fields = _count_confidentials([incomes, monetary, real_estate])
        conf_ratio = conf_fields / conf_total if conf_total > 0 else 0.0

        work_post = str(profile.work_post or "")
        work_place = str(profile.work_place or "")
        post_type = str(profile.post_type or "")
        post_category = str(profile.post_category or "")
        norm = normalizer.normalize(
            work_post=work_post, work_place=work_place,
            post_type=post_type, post_category=post_category
        )
        sector = _slug(norm.sector)
        gov_level = _slug(norm.government_level)
        cohort_key = f"{sector}_{gov_level}"

        score_res = score_declaration(
            total_income=total_income,
            total_assets=total_assets,
            cash_holdings=cash_bank.cash,
            bank_deposits=cash_bank.bank,
            total_value_fields=total_fields,
            unknown_value_fields=unknown_fields,
            largest_acquisition_cost=None,
            ownership_declarant=int(getattr(ownership, "declarant_items", 0)),
            ownership_family=int(getattr(ownership, "family_items", 0)),
            ownership_total=int(getattr(ownership, "total_items", 0)),
            incomes=incomes,
            monetary_assets=monetary,
            real_estate=real_estate,
            vehicles=vehicles,
            family_members=family_members,
            declaration_year=profile.declaration_year,
            declaration_sector=sector,
            declaration_gov_level=gov_level,
            cohort_key_used=cohort_key,
        )

        f_map = build_feature_vector(
            total_income=total_income,
            total_assets=total_assets,
            cash_holdings=cash_bank.cash,
            bank_deposits=cash_bank.bank,
            total_value_fields=total_fields,
            unknown_value_fields=unknown_fields,
            ownership_declarant=int(getattr(ownership, "declarant_items", 0)),
            ownership_family=int(getattr(ownership, "family_items", 0)),
            ownership_total=int(getattr(ownership, "total_items", 0)),
            declaration_year=profile.declaration_year,
            incomes_count=len(incomes),
            real_estate_count=len(real_estate),
            vehicles_count=len(vehicles),
            monetary_count=len(monetary),
            confidential_ratio=conf_ratio,
        )

        l3_score = None
        l3_devs = []
        # Attempt to run Layer 3
        # Since resolve_model handles caching internally, this is safe to call in the loop
        artifact = resolve_model(sector, gov_level)
        if artifact is not None:
            layer3_available = True
            l3_res = infer_anomaly(
                feature_map=f_map,
                model_path="", # will fallback to layer3 module resolution
                sector=sector,
                government_level=gov_level,
            )
            if l3_res is not None:
                l3_score = l3_res.anomaly_score
                l3_devs = l3_res.top_deviations

        results.append({
            "declaration_id": did,
            "cohort_key": cohort_key,
            "total_score": score_res.total_score,
            "rule_results": [
                {
                    "rule_name": r.rule_name,
                    "score": r.score,
                    "triggered": r.triggered,
                    "severity": r.severity
                }
                for r in score_res.rule_results
            ],
            "layer3_anomaly_score": l3_score,
            "layer3_deviations": l3_devs,
        })

    logger.info("Scoring complete. Generating reports.")

    # 1. Overall score distribution
    all_scores = [r["total_score"] for r in results]
    print("\n" + "=" * 60)
    print("1. OVERALL SCORE DISTRIBUTION")
    print("=" * 60)
    if all_scores:
        print(f"Total Evaluated: {len(all_scores)}")
        print(f"Min: {min(all_scores):.2f}")
        print(f"P05: {_percentile(all_scores, 5):.2f}")
        print(f"P25: {_percentile(all_scores, 25):.2f}")
        print(f"P50: {_percentile(all_scores, 50):.2f}")
        print(f"P75: {_percentile(all_scores, 75):.2f}")
        print(f"P95: {_percentile(all_scores, 95):.2f}")
        print(f"Max: {max(all_scores):.2f}")

    # 2. Cohort-stratified score distribution
    print("\n" + "=" * 60)
    print("2. COHORT-STRATIFIED SCORE DISTRIBUTION")
    print("=" * 60)
    cohort_groups = defaultdict(list)
    for r in results:
        cohort_groups[r["cohort_key"]].append(r)
    
    cohort_stats = []
    for ckey, items in cohort_groups.items():
        if len(items) >= args.cohort_min_n:
            c_scores = [i["total_score"] for i in items]
            
            anom_rate = None
            if layer3_available:
                l3_items = [i["layer3_anomaly_score"] for i in items if i.get("layer3_anomaly_score") is not None]
                if l3_items:
                    anom_rate = sum(1 for a in l3_items if a >= args.anomaly_threshold) / len(l3_items)

            cohort_stats.append({
                "cohort_key": ckey,
                "n": len(items),
                "p50": _percentile(c_scores, 50),
                "p95": _percentile(c_scores, 95),
                "anomaly_rate": anom_rate
            })

    cohort_stats.sort(key=lambda x: x["p95"], reverse=True)
    header = f"{'Cohort Key':<35} | {'N':>6} | {'P50':>6} | {'P95':>6} | {'L3 Anom Rate'}"
    print(header)
    print("-" * len(header))
    for cs in cohort_stats:
        ar_str = f"{cs['anomaly_rate']:.1%}" if cs['anomaly_rate'] is not None else "N/A"
        print(f"{cs['cohort_key']:<35} | {cs['n']:>6} | {cs['p50']:>6.1f} | {cs['p95']:>6.1f} | {ar_str}")

    # 3. Rule fire-rate table
    print("\n" + "=" * 60)
    print("3. RULE FIRE-RATE TABLE")
    print("=" * 60)
    rule_stats: dict[str, dict[str, Any]] = {}
    for r in results:
        for r_res in r["rule_results"]:
            rule = r_res["rule_name"]
            if rule not in rule_stats:
                rule_stats[rule] = {
                    "fires": 0,
                    "scores": [],
                    "severities": defaultdict(int)
                }
            if r_res["triggered"]:
                rule_stats[rule]["fires"] += 1
                rule_stats[rule]["scores"].append(r_res["score"])
                sev = r_res.get("severity") or "UNKNOWN"
                rule_stats[rule]["severities"][sev] += 1

    rule_rates = []
    total_records = len(results)
    for rule, stats in rule_stats.items():
        fires = stats["fires"]
        rate = fires / total_records if total_records > 0 else 0
        mean_score = sum(stats["scores"]) / fires if fires > 0 else 0
        top_sev = None
        if stats["severities"]:
            # sort by count descending
            top_sev = sorted(stats["severities"].items(), key=lambda x: x[1], reverse=True)[0][0]
            
        rule_rates.append({
            "rule": rule,
            "fires": fires,
            "rate": rate,
            "mean_score": mean_score,
            "top_severity": top_sev or "N/A"
        })

    rule_rates.sort(key=lambda x: x["rate"], reverse=True)
    r_header = f"{'Rule ID':<30} | {'Fires':>7} | {'Rate %':>7} | {'Mean Sc.':>8} | {'Top Severity'}"
    print(r_header)
    print("-" * len(r_header))
    for rr in rule_rates:
        print(f"{rr['rule']:<30} | {rr['fires']:>7} | {rr['rate']:>7.1%} | {rr['mean_score']:>8.2f} | {rr['top_severity']}")

    # 4. Layer 3 stats
    print("\n" + "=" * 60)
    print("4. LAYER 3 STATS")
    print("=" * 60)
    if layer3_available:
        l3_scores = [r["layer3_anomaly_score"] for r in results if r.get("layer3_anomaly_score") is not None]
        if l3_scores:
            p50_l3 = _percentile(l3_scores, 50)
            p95_l3 = _percentile(l3_scores, 95)
            print(f"Global L3 Anomaly Score Distribution: P50 = {p50_l3:.3f}, P95 = {p95_l3:.3f}")
            
            anomalies = sum(1 for s in l3_scores if s >= args.anomaly_threshold)
            rate_global = anomalies / len(l3_scores)
            print(f"Global L3 Anomaly Rate (>= {args.anomaly_threshold}): {rate_global:.1%}")
            print("\nPer-Cohort Anomaly Rates (Top 5):")
            c_rates = [cs for cs in cohort_stats if cs['anomaly_rate'] is not None]
            c_rates.sort(key=lambda x: x['anomaly_rate'], reverse=True)
            for cs in c_rates[:5]:
                print(f"  - {cs['cohort_key']}: {cs['anomaly_rate']:.1%}")
                
            print(f"\nTop 3 Deviation Features (across anomaly_score >= {args.anomaly_threshold}):")
            dev_counts = defaultdict(int)
            for r in results:
                s = r.get("layer3_anomaly_score")
                if s is not None and s >= args.anomaly_threshold:
                    for dev in r.get("layer3_deviations", []):
                        dev_counts[dev["feature_name"]] += 1
                        
            top_devs = sorted(dev_counts.items(), key=lambda x: x[1], reverse=True)[:3]
            for feat, count in top_devs:
                print(f"  - {feat} (occurred in {count} anomalies)")
        else:
            print("Layer 3 models were available, but no valid scores were produced.")
    else:
        print("No Layer 3 model artifacts found. Skipping Layer 3 statistics.")

    # 5. Potential over-firing alert
    print("\n" + "=" * 60)
    print("5. POTENTIAL OVER-FIRING ALERT")
    print("=" * 60)
    over_firing = [rr for rr in rule_rates if rr["rate"] > 0.30]
    if over_firing:
        print("The following rules fired on >30% of the sample and may need threshold adjustment:")
        for rr in over_firing:
            print(f"  [!] {rr['rule']} -> {rr['rate']:.1%} fire rate")
    else:
        print("All rule fire rates are within expected thresholds (<= 30%).")

    # Optional JSON output
    if args.output_json:
        try:
            with open(args.output_json, "w", encoding="utf-8") as f:
                json.dump({
                    "sample_size": len(results),
                    "overall_distribution": {
                        "min": min(all_scores) if all_scores else None,
                        "p5": _percentile(all_scores, 5),
                        "p25": _percentile(all_scores, 25),
                        "p50": _percentile(all_scores, 50),
                        "p75": _percentile(all_scores, 75),
                        "p95": _percentile(all_scores, 95),
                        "max": max(all_scores) if all_scores else None,
                    },
                    "cohort_stats": cohort_stats,
                    "rule_rates": rule_rates,
                    "over_firing_rules": [rr["rule"] for rr in over_firing],
                    "raw_results": results
                }, f, indent=2, ensure_ascii=False)
            logger.info(f"\nWrote full JSON results to {args.output_json}")
        except Exception as e:
            logger.error(f"Failed to write JSON output: {e}")

if __name__ == "__main__":
    main()
