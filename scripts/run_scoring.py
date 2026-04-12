"""Run declaration scoring with optional Layer 2 and Layer 3 modes.

This script supports three execution styles:
- baseline deterministic scoring,
- Layer 2 cohort uplift,
- Layer 3 unsupervised anomaly contribution (or shadow comparison mode).
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.config import settings
from app.ingestion.save_raw import iter_raw_declarations, load_declaration
from app.scoring.cohorts import (
    CohortFallbackResolver,
    CohortKey,
    build_cohort_distributions,
    build_multi_dimensional_cohorts,
)
from app.services.pipeline import process_declaration_full

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


# Load TaxonomyNormalizer once at startup (lazy, cached)
_normalizer = None


def _get_normalizer():
    """Lazy-load TaxonomyNormalizer for performance."""
    global _normalizer
    if _normalizer is None:
        try:
            from app.scoring.cohort_taxonomy import create_normalizer_from_config
            from pathlib import Path

            yaml_path = str(
                Path(__file__).resolve().parent.parent
                / "backend"
                / "app"
                / "scoring"
                / "cohort_taxonomy.yaml"
            )
            _normalizer = create_normalizer_from_config(yaml_path)
        except Exception as e:
            logger.warning(f"Failed to load TaxonomyNormalizer: {e}")
            _normalizer = False  # Mark as tried but failed
    return _normalizer if _normalizer is not False else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Score raw declarations.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/raw"),
        help="Root directory containing raw declaration JSON files.",
    )
    parser.add_argument("--year", type=str, default=None, help="Filter by year.")
    parser.add_argument(
        "--top",
        type=int,
        default=0,
        help="Show only the top N by score (0 = show all).",
    )
    parser.add_argument(
        "--csv",
        type=str,
        default=None,
        help="Path to write CSV output (e.g. output/scores.csv).",
    )
    parser.add_argument(
        "--layer2",
        action="store_true",
        help="Enable Layer 2 cohort-based scoring on top of Layer 1.",
    )
    parser.add_argument(
        "--layer3",
        action="store_true",
        help="Enable Layer 3 unsupervised scoring contribution.",
    )
    parser.add_argument(
        "--layer3-model-path",
        type=str,
        default="",
        help="Path to serialized Layer 3 model artifact (.pkl).",
    )
    parser.add_argument(
        "--shadow-layer3",
        action="store_true",
        help="Run baseline and Layer 3 side-by-side without changing primary ranking output.",
    )
    args = parser.parse_args()

    if args.shadow_layer3 and not args.layer3:
        logger.warning("--shadow-layer3 requires --layer3; enabling --layer3 automatically.")
        args.layer3 = True

    original_layer3_enabled = settings.layer3_enabled
    original_layer3_model_path = settings.layer3_model_path

    settings.layer3_enabled = bool(args.layer3) and not bool(args.shadow_layer3)
    if args.layer3_model_path:
        settings.layer3_model_path = args.layer3_model_path

    if args.layer3 and not settings.layer3_model_path:
        logger.warning("Layer 3 enabled but no model path provided. ML contribution will no-op.")

    files = iter_raw_declarations(args.data_dir, year=args.year)
    if not files:
        logger.warning("No raw files found in %s", args.data_dir)
        return

    logger.info("Found %d raw declaration files.", len(files))

    # Pass 1: Process declarations without cohort context to build distributions.
    raw_entries: list[tuple[dict, dict[str, object]]] = []
    for f in files:
        try:
            raw = load_declaration(f)
            full = process_declaration_full(raw)
            raw_entries.append((raw, full))
        except Exception:
            logger.exception("  Failed to process %s", f.name)

    if not raw_entries:
        logger.warning("No declarations were successfully processed.")
        settings.layer3_enabled = original_layer3_enabled
        settings.layer3_model_path = original_layer3_model_path
        return

    cohort_summaries = []
    for _, full in raw_entries:
        features = full.get("features", {})
        total_income = features.get("total_income")
        total_assets = features.get("total_assets")
        
        # 3a-3b. Normalize using TaxonomyNormalizer with fallback handling (3d)
        bio = full.get("bio", {})
        sector = "other"
        government_level = "other"
        role_family = "other"
        role_family_confidence = 0.0
        institution_family = "unknown"
        institution_family_confidence = 0.0
        
        normalizer = _get_normalizer()
        if normalizer:
            try:
                # Extract work/post fields
                work_post = bio.get("work_post", "")
                work_place = bio.get("work_place", "")
                post_type_raw = features.get("post_type", "")
                post_category = bio.get("post_category", "")
                
                # Normalize
                norm = normalizer.normalize(
                    work_post=work_post,
                    work_place=work_place,
                    post_type=post_type_raw,
                    post_category=post_category,
                )
                
                # Extract normalized fields only if confidence >= 0.5
                if norm.role_family_confidence >= 0.5:
                    role_family = norm.role_family
                    role_family_confidence = norm.role_family_confidence
                else:
                    logger.warning(
                        f"Low confidence role mapping for '{work_post}' "
                        f"(confidence={norm.role_family_confidence})"
                    )
                
                sector = norm.sector
                government_level = norm.government_level
                
                if norm.institution_family_confidence >= 0.5:
                    institution_family = norm.institution_family
                    institution_family_confidence = norm.institution_family_confidence
                else:
                    logger.warning(
                        f"Low confidence institution mapping for '{work_place}' "
                        f"(confidence={norm.institution_family_confidence})"
                    )
                
            except Exception as e:
                logger.warning(
                    f"Taxonomy normalization failed for {full.get('declaration_id', 'unknown')}: {e}"
                )
                # Fall back to defaults already set above
        
        cohort_summaries.append(
            {
                "post_type": features.get("post_type"),
                "declaration_year": full.get("declaration_year"),
                "total_income": float(Decimal(str(total_income))) if total_income else None,
                "total_assets": float(Decimal(str(total_assets))) if total_assets else None,
                "cash_ratio": features.get("cash_ratio"),
                "confidential_ratio": features.get("confidential_ratio"),
                "sector": sector,
                "government_level": government_level,
                "role_family": role_family,
                "role_family_confidence": role_family_confidence,
                "institution_family": institution_family,
                "institution_family_confidence": institution_family_confidence,
                "year": full.get("declaration_year"),
                "primary_region": bio.get("region"),
            }
        )
        full["_sector"] = sector
        full["_government_level"] = government_level
        full["_primary_region"] = bio.get("region")

    distributions = build_cohort_distributions(cohort_summaries) if args.layer2 else {}
    multi_cohorts = build_multi_dimensional_cohorts(cohort_summaries) if args.layer2 else {}
    resolver = CohortFallbackResolver(multi_cohorts, min_cohort_size=30) if args.layer2 else None

    # Pass 2: Final scoring run (with optional Layer2 and Layer3).
    results: list[dict[str, object]] = []
    shadow_deltas: list[float] = []
    shadow_ml_hits = 0
    for raw, full_first_pass in raw_entries:
        try:
            features = full_first_pass.get("features", {})
            post_type = str(features.get("post_type") or "")
            year = full_first_pass.get("declaration_year")
            sector = str(full_first_pass.get("_sector") or "other")
            gov_level = str(full_first_pass.get("_government_level") or "other")
            region = full_first_pass.get("_primary_region")
            cohort_stats = None
            cohort_key_used = None

            if args.layer2 and resolver and year:
                preferred_key, _ = resolver.resolve_for_income_assets(
                    year=int(year),
                    sector=sector,
                    government_level=gov_level,
                )
                if preferred_key:
                    cohort_stats = resolver.get_cohort(preferred_key)
                    cohort_key_used = preferred_key
                if cohort_stats is None:
                    cohort_stats = distributions.get(CohortKey(post_type=post_type, year=int(year)))
                    cohort_key_used = f"legacy:{post_type}:{year}"
                    logger.info(
                        "Layer 2 cohort fallback for %s: tried %s, used %s",
                        full_first_pass.get("declaration_id", raw.get("id", "unknown")),
                        preferred_key if preferred_key else f"{year}_{sector}_{gov_level}",
                        cohort_key_used,
                    )
                elif preferred_key and cohort_key_used != preferred_key:
                    logger.info(
                        "Layer 2 cohort fallback for %s: tried %s, used %s",
                        full_first_pass.get("declaration_id", raw.get("id", "unknown")),
                        f"{year}_{sector}_{gov_level}",
                        cohort_key_used,
                    )

            # Real score path.
            full_final = process_declaration_full(
                raw,
                cohort_stats=cohort_stats,
                cohort_resolver=resolver,
                declaration_sector=sector if args.layer2 else None,
                declaration_gov_level=gov_level if args.layer2 else None,
                declaration_region=region if args.layer2 else None,
                cohort_key_used=cohort_key_used,
            )

            # Shadow run: compute baseline without Layer3 and compare.
            if args.shadow_layer3:
                settings.layer3_enabled = False
                baseline_full = process_declaration_full(
                    raw,
                    cohort_stats=cohort_stats,
                    cohort_resolver=resolver,
                    declaration_sector=sector if args.layer2 else None,
                    declaration_gov_level=gov_level if args.layer2 else None,
                    declaration_region=region if args.layer2 else None,
                    cohort_key_used=cohort_key_used,
                )
                settings.layer3_enabled = bool(args.layer3)
            else:
                baseline_full = full_final

            score_data = full_final.get("score", {})
            baseline_score_data = baseline_full.get("score", {})
            bio = full_final.get("bio", {})

            total_score = float(score_data.get("total_score") or 0.0)
            baseline_score = float(baseline_score_data.get("total_score") or 0.0)
            delta = round(total_score - baseline_score, 3)
            shadow_deltas.append(delta)

            rule_details = score_data.get("rule_details") or []
            has_ml1 = any((r.get("rule_name") == "ML1" and r.get("triggered")) for r in rule_details if isinstance(r, dict))
            if has_ml1:
                shadow_ml_hits += 1

            summary = {
                "declaration_id": full_final.get("declaration_id"),
                "name": f"{bio.get('firstname', '')} {bio.get('lastname', '')}".strip() or "Unknown",
                "work_post": bio.get("work_post", ""),
                "work_place": bio.get("work_place", ""),
                "total_income": features.get("total_income"),
                "total_assets": features.get("total_assets"),
                "score": total_score,
                "sector": sector,
                "government_level": gov_level,
                "cohort_key_used": cohort_key_used,
                "triggered_rules": score_data.get("triggered_rules") or [],
                "explanation": score_data.get("explanation") or "",
                "layer3_delta": delta,
                "layer3_triggered": has_ml1,
            }
            results.append(summary)
        except Exception:
            logger.exception("  Failed to finalize scoring for declaration %s", raw.get("id", "unknown"))

    settings.layer3_enabled = original_layer3_enabled
    settings.layer3_model_path = original_layer3_model_path

    if args.layer2:
        logger.info("Layer 2: %d cohorts built.", len(distributions))
    if args.layer3:
        logger.info("Layer 3: model path = %s", settings.layer3_model_path or "<none>")
    if args.shadow_layer3 and shadow_deltas:
        avg_delta = sum(shadow_deltas) / len(shadow_deltas)
        max_delta = max(shadow_deltas)
        logger.info(
            "Layer 3 shadow: avg delta %.3f, max delta %.3f, ML1 hits %d/%d.",
            avg_delta,
            max_delta,
            shadow_ml_hits,
            len(shadow_deltas),
        )

    # ── Sort and display ─────────────────────────────────────────────────
    results.sort(key=lambda r: r["score"], reverse=True)

    if args.top > 0:
        results = results[: args.top]

    logger.info("")
    logger.info("%-14s %-30s %8s  %s", "ID", "NAME", "SCORE", "FLAGS")
    logger.info("-" * 80)
    for r in results:
        flags = ", ".join(r["triggered_rules"]) if r["triggered_rules"] else "—"
        logger.info(
            "%-14s %-30s %8.1f  %s",
            str(r["declaration_id"])[:14],
            r["name"][:30],
            r["score"],
            flags,
        )

    logger.info("")
    logger.info(
        "Total: %d declarations, %d flagged.",
        len(results),
        sum(1 for r in results if r["score"] > 0),
    )

    # CSV export
    if args.csv:
        csv_path = Path(args.csv)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "declaration_id", "name", "work_post", "work_place",
            "total_income", "total_assets", "sector", "government_level", "cohort_key_used", "score",
            "triggered_rules", "explanation", "layer3_delta", "layer3_triggered",
        ]
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in results:
                row = dict(r)
                row["triggered_rules"] = ", ".join(r.get("triggered_rules") or [])
                writer.writerow(row)
        logger.info("CSV written to %s (%d rows)", csv_path, len(results))


if __name__ == "__main__":
    main()
