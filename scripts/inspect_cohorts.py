#!/usr/bin/env python3
"""
Diagnostic tool for Ukraine-specific cohort taxonomy.

Analyzes declared profiles to assess:
  1. Cohort distribution (sizes, sparsity)
  2. Role family clustering quality
  3. Institution normalization quality
  4. Fallback chain usage
  5. Low-confidence mappings for manual review

Usage:
    python scripts/inspect_cohorts.py \
        --data data/crawl_state_smoke.json \
        --min-cohort-size 30 \
        --output output/cohort_inspection.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# Ensure project paths are available
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "backend"))

from app.scoring.cohort_taxonomy import (
    CohortKeyBuilder,
    InstitutionNormalizer,
    RoleClusterer,
    TaxonomyMapper,
    TaxonomyNormalizer,
    create_normalizer_from_config,
    load_taxonomy_config,
)
from app.scoring.cohorts import build_multi_dimensional_cohorts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================================
# Report Data Classes
# ============================================================================

@dataclass
class RoleFamilyStatistics:
    """Statistics for a role_family cluster."""
    role_family: str
    count: int
    confidence_avg: float
    confidence_min: float
    confidence_max: float
    top_raw_titles: list[tuple[str, int]]  # (title, count)
    low_confidence_titles: list[str]


@dataclass
class InstitutionStatistics:
    """Statistics for institution normalization."""
    institution_type: str
    count: int
    confidence_avg: float
    fuzzy_matched_count: int
    keyword_extracted_count: int
    unknown_count: int
    unresolved: list[str]  # Raw institution names with low confidence


@dataclass
class CohortSparsityReport:
    """Report on cohort completeness."""
    total_possible_combinations: int
    cohorts_with_data: int
    sparsity_percentage: float
    min_cohort_size: int
    cohorts_below_min: dict[str, int]  # key -> count


@dataclass
class FallbackStatistics:
    """Statistics on fallback chain usage."""
    feature_type: str
    total_declarations: int
    primary_key_used: int
    fallback_tier_1_used: int
    fallback_tier_2_used: int
    fallback_tier_3_used: int
    global_fallback_used: int


@dataclass
class DiagnosticReport:
    """Complete diagnostic report."""
    total_declarations: int
    timestamp: str
    role_family_stats: dict[str, RoleFamilyStatistics]
    institution_stats: dict[str, InstitutionStatistics]
    cohort_sparsity: CohortSparsityReport
    fallback_stats: list[FallbackStatistics]
    low_confidence_summary: dict[str, int]  # category -> count
    recommendations: list[str]


# ============================================================================
# Diagnostic Engine
# ============================================================================

class CohortDiagnostician:
    """Main diagnostic tool."""

    def __init__(self, min_cohort_size: int = 30, config_path: str | None = None):
        """Initialize diagnostician.

        Parameters
        ----------
        min_cohort_size:
            Threshold for small cohorts
        config_path:
            Path to cohort_taxonomy.yaml
        """
        self.min_cohort_size = min_cohort_size

        if config_path:
            self.normalizer = create_normalizer_from_config(config_path)
        else:
            # Try default path
            default_config = Path(__file__).parent.parent / "backend" / "app" / "scoring" / "cohort_taxonomy.yaml"
            if default_config.exists():
                self.normalizer = create_normalizer_from_config(str(default_config))
            else:
                logger.warning("No config path provided and default not found; using defaults")
                self.normalizer = TaxonomyNormalizer()

        self.normalizations: list[dict[str, Any]] = []
        self.low_confidence: defaultdict[str, list[str]] = defaultdict(list)

    def process_declarations(self, declarations: list[dict[str, Any]]) -> None:
        """Process declarations through taxonomy normalizer.

        Parameters
        ----------
        declarations:
            List of declaration dicts from JSON
        """
        for decl in declarations:
            # Extract profile fields
            profile = decl.get("profile", {})
            work_post = profile.get("work_post", "")
            work_place = profile.get("work_place")
            post_type = profile.get("post_type")
            post_category = profile.get("post_category")
            declaration_year = profile.get("declaration_year", 0)
            primary_region = decl.get("features", {}).get("primary_region")

            # Normalize
            norm = self.normalizer.normalize(
                work_post=work_post,
                work_place=work_place,
                post_type=post_type,
                post_category=post_category,
            )

            # Store results
            self.normalizations.append({
                "declarant_id": decl.get("person_id", "unknown"),
                "work_post": work_post,
                "work_place": work_place,
                "post_type": post_type,
                "post_category": post_category,
                "declaration_year": declaration_year,
                "primary_region": primary_region,
                "role_family": norm.role_family,
                "role_family_confidence": norm.role_family_confidence,
                "sector": norm.sector,
                "government_level": norm.government_level,
                "institution_family": norm.institution_family,
                "institution_family_confidence": norm.institution_family_confidence,
                "role_mapping": asdict(norm.role_mapping) if norm.role_mapping else None,
                "institution_mapping": asdict(norm.institution_mapping) if norm.institution_mapping else None,
            })

            # Track low-confidence mappings
            if norm.role_family == "other":
                self.low_confidence["role_unclassified"].append(work_post)
            if norm.role_family_confidence < 0.6:
                self.low_confidence["role_low_confidence"].append(work_post)
            if norm.institution_family == "unknown":
                self.low_confidence["institution_unknown"].append(work_place or "")
            if norm.institution_family_confidence < 0.6 and norm.institution_family != "unknown":
                self.low_confidence["institution_low_confidence"].append(work_place or "")

    def build_role_family_statistics(self) -> dict[str, RoleFamilyStatistics]:
        """Build per-role_family statistics."""
        stats: dict[str, RoleFamilyStatistics] = {}

        role_titles: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for norm in self.normalizations:
            rf = norm["role_family"]
            title = norm["work_post"]
            conf = norm["role_family_confidence"]
            role_titles[rf].append((title, conf))

        for role_family, title_list in role_titles.items():
            confs = [conf for _, conf in title_list]
            titles_count = defaultdict(int)
            for title, _ in title_list:
                titles_count[title] += 1

            top_titles = sorted(titles_count.items(), key=lambda x: x[1], reverse=True)[:10]

            low_conf = [title for title, conf in title_list if conf < 0.6]

            stats[role_family] = RoleFamilyStatistics(
                role_family=role_family,
                count=len(title_list),
                confidence_avg=sum(confs) / len(confs) if confs else 0.0,
                confidence_min=min(confs) if confs else 0.0,
                confidence_max=max(confs) if confs else 0.0,
                top_raw_titles=top_titles,
                low_confidence_titles=low_conf[:20],  # Top 20
            )

        return stats

    def build_institution_statistics(self) -> dict[str, InstitutionStatistics]:
        """Build per-institution_type statistics."""
        stats: dict[str, InstitutionStatistics] = {}

        inst_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for norm in self.normalizations:
            itype = norm["institution_family"]
            inst_mapping = norm["institution_mapping"]
            inst_by_type[itype].append({
                "raw_name": norm["work_place"],
                "confidence": norm["institution_family_confidence"],
                "matched_via": inst_mapping.get("matched_via") if inst_mapping else "unknown",
            })

        for itype, entries in inst_by_type.items():
            confs = [e["confidence"] for e in entries]
            fuzzy = sum(1 for e in entries if e["matched_via"] == "seed_fuzzy")
            keyword = sum(1 for e in entries if e["matched_via"] == "keyword_extract")
            unknown = sum(1 for e in entries if e["matched_via"] == "unknown")

            unresolved = [
                e["raw_name"] for e in entries
                if e["confidence"] < 0.6 and e["raw_name"]
            ]

            stats[itype] = InstitutionStatistics(
                institution_type=itype,
                count=len(entries),
                confidence_avg=sum(confs) / len(confs) if confs else 0.0,
                fuzzy_matched_count=fuzzy,
                keyword_extracted_count=keyword,
                unknown_count=unknown,
                unresolved=unresolved[:20],  # Top 20 low-confidence
            )

        return stats

    def build_cohort_sparsity_report(self) -> CohortSparsityReport:
        """Analyze cohort completeness."""
        years = set()
        sectors = set()
        govt_levels = set()
        regions = set()

        for norm in self.normalizations:
            years.add(norm["declaration_year"])
            sectors.add(norm["sector"])
            govt_levels.add(norm["government_level"])
            if norm["primary_region"]:
                regions.add(norm["primary_region"].lower().strip())

        # Total possible combinations
        total_possible = len(years) * len(sectors) * len(govt_levels)
        # (regions add another dimension, but calculate separately)
        total_with_regions = total_possible * len(regions) if regions else total_possible

        # Cohorts with actual data
        cohorts_with_data: dict[str, int] = defaultdict(int)
        for norm in self.normalizations:
            key = f"{norm['declaration_year']}_{norm['sector']}_{norm['government_level']}"
            cohorts_with_data[key] += 1

        # Cohorts below min size
        below_min = {k: v for k, v in cohorts_with_data.items() if v < self.min_cohort_size}

        sparsity = 1.0 - (len(cohorts_with_data) / total_possible) if total_possible > 0 else 0.0

        return CohortSparsityReport(
            total_possible_combinations=total_possible,
            cohorts_with_data=len(cohorts_with_data),
            sparsity_percentage=sparsity * 100,
            min_cohort_size=self.min_cohort_size,
            cohorts_below_min=below_min,
        )

    def build_fallback_statistics(self) -> list[FallbackStatistics]:
        """Estimate fallback chain usage (simplified)."""
        # This is a simplified estimate; in production, the scoring pipeline would log actual fallback usage
        total = len(self.normalizations)

        # Count how many declarations are in "small" cohorts
        cohort_sizes: dict[str, int] = defaultdict(int)
        for norm in self.normalizations:
            key = f"{norm['declaration_year']}_{norm['sector']}_{norm['government_level']}"
            cohort_sizes[key] += 1

        small_cohorts = {k: v for k, v in cohort_sizes.items() if v < self.min_cohort_size}
        small_decls = sum(small_cohorts.values())

        return [
            FallbackStatistics(
                feature_type="income_assets",
                total_declarations=total,
                primary_key_used=total - small_decls,
                fallback_tier_1_used=0,  # Placeholder
                fallback_tier_2_used=0,
                fallback_tier_3_used=0,
                global_fallback_used=small_decls,
            ),
        ]

    def generate_recommendations(
        self,
        role_stats: dict[str, RoleFamilyStatistics],
        inst_stats: dict[str, InstitutionStatistics],
        sparsity: CohortSparsityReport,
    ) -> list[str]:
        """Generate actionable recommendations."""
        recs = []

        # Role clustering recommendations
        unclassified_count = role_stats.get("other", RoleFamilyStatistics("other", 0, 0, 0, 0, [], [])).count
        if unclassified_count > 0:
            pct = 100 * unclassified_count / sum(s.count for s in role_stats.values())
            if pct > 10:
                recs.append(f"⚠️  {pct:.1f}% of declarations have unclassified roles ('other'). "
                            "Consider adding keywords to RoleClusterer.ROLE_CLUSTERS.")

        # Institution matching recommendations
        unknown_inst = inst_stats.get("unknown", InstitutionStatistics("unknown", 0, 0, 0, 0, 0, []))
        if unknown_inst.count > 0:
            pct = 100 * unknown_inst.count / sum(s.count for s in inst_stats.values())
            if pct > 5:
                recs.append(f"⚠️  {pct:.1f}% of institutions are unclassified ('unknown'). "
                            "Consider adding entries to seed_institutions in cohort_taxonomy.yaml.")

        # Cohort sparsity recommendations
        if sparsity.sparsity_percentage > 30:
            recs.append(f"⚠️  Cohort sparsity is {sparsity.sparsity_percentage:.1f}%. "
                        f"Only {sparsity.cohorts_with_data}/{sparsity.total_possible_combinations} combinations have data. "
                        "Consider increasing min_cohort_size or coarsening dimensions.")

        if sparsity.cohorts_below_min:
            below_count = sum(sparsity.cohorts_below_min.values())
            pct = 100 * below_count / len(self.normalizations)
            recs.append(f"ℹ️  {pct:.1f}% of declarations ({below_count}) fall into cohorts below min_cohort_size. "
                        "Fallback chain will be used for scoring.")

        # General recommendations
        if len(self.normalizations) < 100:
            recs.append("ℹ️  Dataset size is small (<100 declarations). "
                        "Cohort statistics may be unreliable. "
                        "Consider running on larger dataset (5k+ declarations).")

        if not recs:
            recs.append("✅ Cohort taxonomy configuration appears healthy. No major issues detected.")

        return recs

    def generate_report(self) -> DiagnosticReport:
        """Generate complete diagnostic report."""
        import datetime

        role_stats = self.build_role_family_statistics()
        inst_stats = self.build_institution_statistics()
        sparsity = self.build_cohort_sparsity_report()
        fallback_stats = self.build_fallback_statistics()

        low_conf_summary = {
            "role_unclassified": len(self.low_confidence["role_unclassified"]),
            "role_low_confidence": len(self.low_confidence["role_low_confidence"]),
            "institution_unknown": len(self.low_confidence["institution_unknown"]),
            "institution_low_confidence": len(self.low_confidence["institution_low_confidence"]),
        }

        recommendations = self.generate_recommendations(role_stats, inst_stats, sparsity)

        return DiagnosticReport(
            total_declarations=len(self.normalizations),
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            role_family_stats=role_stats,
            institution_stats=inst_stats,
            cohort_sparsity=sparsity,
            fallback_stats=fallback_stats,
            low_confidence_summary=low_conf_summary,
            recommendations=recommendations,
        )


# ============================================================================
# Output Formatting
# ============================================================================

def report_to_dict(report: DiagnosticReport) -> dict[str, Any]:
    """Convert DiagnosticReport to JSON-serializable dict."""
    return {
        "total_declarations": report.total_declarations,
        "timestamp": report.timestamp,
        "role_family_stats": {
            k: asdict(v) for k, v in report.role_family_stats.items()
        },
        "institution_stats": {
            k: asdict(v) for k, v in report.institution_stats.items()
        },
        "cohort_sparsity": asdict(report.cohort_sparsity),
        "fallback_stats": [asdict(f) for f in report.fallback_stats],
        "low_confidence_summary": report.low_confidence_summary,
        "recommendations": report.recommendations,
    }


def report_to_markdown(report: DiagnosticReport) -> str:
    """Convert DiagnosticReport to readable markdown."""
    lines = [
        "# Cohort Taxonomy Diagnostic Report",
        "",
        f"**Timestamp**: {report.timestamp}",
        f"**Total Declarations Analyzed**: {report.total_declarations}",
        "",
        "## Executive Summary",
        "",
    ]

    lines.extend([f"- {rec}" for rec in report.recommendations])
    lines.append("")

    # Role Family Statistics
    lines.extend([
        "## Role Family Distribution",
        "",
        "| Role Family | Count | Avg Confidence | Min Conf | Max Conf |",
        "|-----------|-------|-----------------|----------|----------|",
    ])
    for rf, stats in sorted(report.role_family_stats.items(), key=lambda x: x[1].count, reverse=True):
        lines.append(
            f"| {rf} | {stats.count} | {stats.confidence_avg:.3f} | "
            f"{stats.confidence_min:.3f} | {stats.confidence_max:.3f} |"
        )
    lines.append("")

    # Top unclassified roles
    if "other" in report.role_family_stats:
        lines.extend([
            "### Sample Unclassified Roles (role_family='other')",
            "",
        ])
        other_titles = report.role_family_stats["other"].low_confidence_titles
        for title in other_titles[:10]:
            lines.append(f"- `{title}`")
        lines.append("")

    # Institution Statistics
    lines.extend([
        "## Institution Type Distribution",
        "",
        "| Institution Type | Count | Fuzzy Matched | Keyword Extracted | Unknown |",
        "|-----------------|-------|---------------|-------------------|---------|",
    ])
    for itype, stats in sorted(report.institution_stats.items(), key=lambda x: x[1].count, reverse=True):
        lines.append(
            f"| {itype} | {stats.count} | {stats.fuzzy_matched_count} | "
            f"{stats.keyword_extracted_count} | {stats.unknown_count} |"
        )
    lines.append("")

    # Unknown institutions
    unknown_inst = report.institution_stats.get("unknown", InstitutionStatistics("unknown", 0, 0.0, 0, 0, 0, []))
    if unknown_inst.unresolved:
        lines.extend([
            "### Sample Unknown Institutions (unresolved)",
            "",
        ])
        for inst in unknown_inst.unresolved[:15]:
            lines.append(f"- `{inst}`")
        lines.append("")

    # Cohort Sparsity
    sparsity = report.cohort_sparsity
    lines.extend([
        "## Cohort Completeness",
        "",
        f"- Total possible combinations: {sparsity.total_possible_combinations}",
        f"- Combinations with data: {sparsity.cohorts_with_data}",
        f"- Sparsity: {sparsity.sparsity_percentage:.1f}%",
        f"- Minimum cohort size threshold: {sparsity.min_cohort_size}",
        "",
    ])

    if sparsity.cohorts_below_min:
        lines.extend([
            "### Cohorts Below Minimum Size",
            "",
            "| Cohort Key | Count |",
            "|-----------|-------|",
        ])
        for key, count in sorted(sparsity.cohorts_below_min.items(), key=lambda x: x[1], reverse=True)[:20]:
            lines.append(f"| `{key}` | {count} |")
        lines.append("")

    # Low Confidence Summary
    lines.extend([
        "## Low Confidence Mappings",
        "",
        "| Category | Count |",
        "|----------|-------|",
    ])
    for category, count in report.low_confidence_summary.items():
        lines.append(f"| {category} | {count} |")
    lines.append("")

    lines.extend([
        "---",
        "*Report generated by inspect_cohorts.py*",
    ])

    return "\n".join(lines)


# ============================================================================
# Main CLI
# ============================================================================

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Diagnostic tool for Ukraine-specific cohort taxonomy"
    )
    parser.add_argument(
        "--data",
        required=True,
        help="Path to JSON declarations file (e.g., data/crawl_state_smoke.json)"
    )
    parser.add_argument(
        "--config",
        help="Path to cohort_taxonomy.yaml (default: backend/app/scoring/cohort_taxonomy.yaml)"
    )
    parser.add_argument(
        "--min-cohort-size",
        type=int,
        default=30,
        help="Minimum cohort size for statistics (default: 30)"
    )
    parser.add_argument(
        "--output",
        default="output/cohort_inspection.json",
        help="Output path for JSON report (default: output/cohort_inspection.json)"
    )
    parser.add_argument(
        "--markdown",
        help="Additional output path for markdown report"
    )

    args = parser.parse_args()

    # Load declarations
    data_path = Path(args.data)
    if not data_path.exists():
        logger.error(f"Data file not found: {data_path}")
        return 1

    logger.info(f"Loading declarations from {data_path}")
    with open(data_path, "r", encoding="utf-8") as f:
        declarations = json.load(f)

    if not isinstance(declarations, list):
        declarations = [declarations]

    logger.info(f"Loaded {len(declarations)} declarations")

    # Run diagnostics
    diagnostician = CohortDiagnostician(
        min_cohort_size=args.min_cohort_size,
        config_path=args.config,
    )

    logger.info("Processing declarations through taxonomy normalizer...")
    diagnostician.process_declarations(declarations)

    logger.info("Generating diagnostic report...")
    report = diagnostician.generate_report()

    # Output JSON
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report_to_dict(report), f, indent=2, ensure_ascii=False)

    logger.info(f"JSON report written to {output_path}")

    # Output markdown if requested
    if args.markdown:
        md_path = Path(args.markdown)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(report_to_markdown(report))
        logger.info(f"Markdown report written to {md_path}")

    # Print summary to console (handle Unicode)
    print("\n" + "=" * 80)
    print("COHORT TAXONOMY DIAGNOSTIC SUMMARY")
    print("=" * 80)
    print(f"Total declarations: {report.total_declarations}")
    print(f"Role families: {len(report.role_family_stats)}")
    print(f"Institution types: {len(report.institution_stats)}")
    print(f"Cohort sparsity: {report.cohort_sparsity.sparsity_percentage:.1f}%")
    print("\nRecommendations:")
    for rec in report.recommendations:
        try:
            print(f"  {rec}")
        except UnicodeEncodeError:
            # Fallback for systems that can't handle Cyrillic
            print(f"  [Recommendation with Ukrainian text]")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    sys.exit(main())
