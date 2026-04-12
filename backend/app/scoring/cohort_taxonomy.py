"""
Ukraine-specific cohort taxonomy and normalization module.

This module provides:
  1. RoleClusterer: Clusters raw job titles (work_post) into semantic role_family groups
  2. InstitutionNormalizer: Fuzzy-matches and type-extracts institution names
  3. TaxonomyMapper: Maps post_type → sector, government_level
  4. CohortKeyBuilder: Builds multi-dimensional cohort keys with fallback hierarchy

Design principles:
  - Preserve raw values for debugging and future manual curation
  - Automatic clustering/matching with confidence scoring
  - Ukraine-specific classification (judiciary, local vs central govt, etc.)
  - Backward-compatible with existing (post_type, year) cohorts
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

logger = logging.getLogger(__name__)


# ============================================================================
# Data classes for taxonomy mappings
# ============================================================================

@dataclass
class RoleFamilyMapping:
    """Normalized role classification."""

    raw_title: str
    role_family: str  # e.g., "physician", "manager", "technician"
    confidence: float  # [0.0, 1.0]
    keywords_matched: list[str] = field(default_factory=list)
    other_candidates: dict[str, float] = field(default_factory=dict)  # alternatives


@dataclass
class InstitutionMapping:
    """Normalized institution classification."""

    raw_name: str
    canonical_name: str | None  # None if no seed match found
    institution_type: str  # e.g., "healthcare", "judiciary", "local_government"
    confidence: float  # [0.0, 1.0]
    matched_via: str  # "seed_fuzzy", "keyword_extract", "unknown"
    fuzzy_score: float = 0.0
    overlap_score: float = 0.0


@dataclass
class TaxonomyNormalization:
    """Complete taxonomy normalization for a declaration profile."""

    work_post_raw: str
    work_place_raw: str | None
    post_type_raw: str
    post_category_raw: str | None

    # Normalized outputs
    role_family: str
    role_family_confidence: float
    sector: str
    government_level: str
    institution_family: str
    institution_family_confidence: float

    # Audit trail
    role_mapping: RoleFamilyMapping | None = None
    institution_mapping: InstitutionMapping | None = None
    sector_keywords_found: list[str] = field(default_factory=list)
    govt_level_keywords_found: list[str] = field(default_factory=list)


# ============================================================================
# Role Clustering
# ============================================================================

class RoleClusterer:
    """Cluster raw Ukrainian job titles into semantic role families.

    Uses keyword-based clustering (TF-IDF not implemented in MVP for simplicity).
    Clusters are discovered by analyzing frequency of Ukrainian title keywords.

    Predefined clusters:
      - "physician"
      - "nurse/paramedic"
      - "technician"
      - "manager"
      - "judge/prosecutor"
      - "teacher/instructor"
      - "engineer"
      - "administrative"
      - "security"
      - "other"
    """

    # Keyword clusters for role families (Ukrainian keywords)
    ROLE_CLUSTERS = {
        "physician": [
            "ЛІКАР", "ЛІКАРКА", "МЕДИК", "ХІРУРГ", "НЕВРОПАТОЛОГ",
            "КАРДІОЛОГ", "ПЕДІАТР", "ОФТАЛМОЛОГ", "УРОЛОГ", "ТЕРАПЕВТ",
            "ГІНЕКОЛОГ", "СТОМАТОЛОГ", "ДЕРМАТОЛОГ", "ПСИХІАТР",
        ],
        "nurse_paramedic": [
            "МЕДСЕСТРА", "МЕДСЕСТР", "ФЕЛЬДШЕР", "АКУШЕРКА",
            "ЛАБОРАНТ", "МАССАЖИСТ", "РЕНТГЕНОЛОГ", "САНІТАР",
        ],
        "technician": [
            "ТЕХПРАЦІВНИК", "ТЕХНІКА", "ТЕХНИК", "ЛЕСНИК", "ЕЛЕКТРИК",
            "СЛЮСАР", "ЗВАРНИК", "СТОЛЯР", "МАЛЮНОК",
        ],
        "engineer": [
            "ІНЖЕНЕР", "ПРОЕКТАНТ", "КОНСТРУКТОР", "АРХІТЕКТОР",
            "ПРОГРАМІСТ", "IT", "ІТ", "СИСТЕМНИК", "РОЗРОБНИК",
        ],
        "manager": [
            "ДИРЕКТОР", "НАЧАЛЬНИК", "ГОЛОВА", "ЗАВІДУВАЧ", "КЕРІВНИК",
            "МЕНЕДЖЕР", "УПРАВЛІННЯ", "ПРЕЗИДЕНТ", "ВІЦЕ", "ЗАСТУПНИК",
            "ГЕНЕРАЛЬНИЙ", "ГЕНЕРАЛЬН", "ЗАВЕДУВАЧ",
        ],
        "judge_prosecutor": [
            "СУДД", "СУД", "СУДДЯ", "ПРОКУРОР", "СЛІДЧИЙ", "ДЕТЕКТИВ",
            "АДВОКАТ", "ЮРИСТ", "ПОМІЧНИК СУДДІ", "ПОМІЧНИК ПРОКУРОРА",
        ],
        "teacher": [
            "ВЧИТЕЛЬ", "ВИКЛАДАЧ", "ЛЕКТОР", "ДОЦЕНТ", "ПРОФЕСОР",
            "МАЙСТЕР", "ІНСТРУКТОР", "ТРЕНЕР", "НАСТАВНИК", "ОСВІТЯН",
            "ПЕДАГОГ", "ПСИХОЛОГ", "ЛОГОПЕД",
        ],
        "administrative": [
            "РЕФЕРЕНТ", "СПЕЦІАЛІСТ", "ПРОВІДНИЙ", "КОНСУЛЬТАНТ",
            "ЕКСПЕРТ", "ПОМІЧНИК", "СЕКРЕТАР", "БУХГАЛТЕР", "КАСИР",
            "ОФІЦІАНТ", "ОХОРОНЕЦЬ", "ДВОРНИК", "ПРИБИРАЛЬНИК",
        ],
        "security": [
            "ОФІЦЕР", "СЕРЖАНТ", "СТАРШИЙ", "КОМБАТ", "БОЄЦЬ",
            "СПЕЦНАЗ", "РОЗВІДНИК", "НАВІДНИК", "КІНОЛОГ",
            "КОНТРРАЗВЕДНИК", "ОПЕРАЦІЙНИК",
        ],
    }

    def __init__(self):
        """Initialize the role clusterer."""
        self._normalize_keywords()

    def _normalize_keywords(self) -> None:
        """Uppercase all keywords for case-insensitive matching."""
        for cluster, keywords in self.ROLE_CLUSTERS.items():
            self.ROLE_CLUSTERS[cluster] = [kw.upper() for kw in keywords]

    def cluster(self, raw_title: str) -> RoleFamilyMapping:
        """Cluster a raw job title into a role family.

        Parameters
        ----------
        raw_title: Free-text job title (typically Ukrainian).

        Returns
        -------
        RoleFamilyMapping with role_family, confidence, and matched keywords.
        """
        if not raw_title or not raw_title.strip():
            return RoleFamilyMapping(
                raw_title=raw_title or "",
                role_family="other",
                confidence=0.3,  # Low confidence for empty/None titles
                keywords_matched=[],
            )

        # Tokenize and uppercase
        text_upper = raw_title.upper()
        tokens = re.split(r"[\s,\-/]+", text_upper)

        # Find matches across clusters
        cluster_matches: dict[str, list[str]] = {}
        for cluster, keywords in self.ROLE_CLUSTERS.items():
            matched = [kw for kw in keywords if any(kw in tkn for tkn in tokens)]
            if matched:
                cluster_matches[cluster] = matched

        if not cluster_matches:
            return RoleFamilyMapping(
                raw_title=raw_title,
                role_family="other",
                confidence=0.3,  # Low confidence for unmatched
                keywords_matched=[],
            )

        # Select best cluster by match count (with tiebreaking by first cluster definition order)
        best_cluster = max(
            cluster_matches.keys(),
            key=lambda c: (len(cluster_matches[c]), list(self.ROLE_CLUSTERS.keys()).index(c)),
        )

        # Confidence: higher if more keywords matched
        # Base confidence starts at 0.6 for having at least 1 match, increases with more matches
        best_matches = cluster_matches[best_cluster]
        confidence = min(1.0, 0.6 + (len(best_matches) - 1) * 0.2)  # 0.6, 0.8, 1.0 for 1, 2, 3+ matches

        # Collect runner-up clusters for audit
        other_candidates = {c: min(1.0, 0.6 + (len(m) - 1) * 0.2) for c, m in cluster_matches.items()
                            if c != best_cluster}

        return RoleFamilyMapping(
            raw_title=raw_title,
            role_family=best_cluster,
            confidence=confidence,
            keywords_matched=best_matches,
            other_candidates=other_candidates,
        )


# ============================================================================
# Institution Normalization
# ============================================================================

class InstitutionNormalizer:
    """Fuzzy-match and classify institution names.

    Approach:
      1. Load seed institution list from YAML
      2. For each raw institution name:
         a) Fuzzy match against seed entries (Levenshtein + keyword overlap)
         b) If match score high enough, use canonical name
         c) Else, extract institution_type from keywords in raw name
         d) Else, mark as 'unknown' for manual review
    """

    def __init__(self, seed_institutions: list[dict[str, Any]] | None = None):
        """Initialize normalizer with optional seed list.

        Parameters
        ----------
        seed_institutions:
            List of institution dicts from YAML, each with:
              - canonical_name: str
              - aliases: list[str]
              - institution_type: str
        """
        self.seed_institutions = seed_institutions or []
        self.type_keywords = self._extract_type_keywords()

    def _extract_type_keywords(self) -> dict[str, list[str]]:
        """Build a map of institution_type → keywords for type extraction."""
        type_kw: dict[str, list[str]] = {}
        for inst in self.seed_institutions:
            itype = inst.get("institution_type", "unknown")
            canonical = inst.get("canonical_name", "")
            if itype and canonical:
                if itype not in type_kw:
                    type_kw[itype] = []
                # Extract multi-character sequences as keywords
                tokens = re.split(r"[\s\-/]+", canonical.upper())
                type_kw[itype].extend(tokens)

        # Deduplicate within each type
        for itype in type_kw:
            type_kw[itype] = list(set(type_kw[itype]))

        return type_kw

    def _fuzzy_score(
        self,
        raw_name: str,
        canonical_name: str,
        aliases: list[str] | None = None,
    ) -> tuple[float, float]:
        """Compute fuzzy match score (edit distance + keyword overlap).

        Returns
        -------
        (fuzzy_score, overlap_score) both in [0.0, 1.0]
        """
        aliases = aliases or []

        # Normalize for comparison
        raw_norm = raw_name.upper().strip()
        canonical_norm = canonical_name.upper().strip()

        # String similarity via SequenceMatcher
        seq_ratio = SequenceMatcher(None, raw_norm, canonical_norm).ratio()

        # Also check aliases
        best_alias_ratio = 0.0
        for alias in aliases:
            alias_norm = alias.upper().strip()
            alias_ratio = SequenceMatcher(None, raw_norm, alias_norm).ratio()
            best_alias_ratio = max(best_alias_ratio, alias_ratio)

        fuzzy_score = max(seq_ratio, best_alias_ratio)

        # Keyword overlap (Jaccard-style)
        raw_tokens = set(re.split(r"[\s\-/]+", raw_norm))
        canonical_tokens = set(re.split(r"[\s\-/]+", canonical_norm))
        for alias in aliases:
            alias_tokens = set(re.split(r"[\s\-/]+", alias.upper().strip()))
            canonical_tokens.update(alias_tokens)

        if not raw_tokens or not canonical_tokens:
            overlap_score = 1.0 if raw_tokens == canonical_tokens else 0.0
        else:
            intersection = len(raw_tokens & canonical_tokens)
            union = len(raw_tokens | canonical_tokens)
            overlap_score = intersection / union if union > 0 else 0.0

        return fuzzy_score, overlap_score

    def _extract_type_from_keywords(self, raw_name: str) -> tuple[str, list[str]]:
        """Extract institution type from raw name keywords.

        Returns
        -------
        (institution_type, matched_keywords)
        """
        raw_upper = raw_name.upper()
        type_with_matches: dict[str, list[str]] = {}

        for itype, keywords in self.type_keywords.items():
            matched = [kw for kw in keywords if kw in raw_upper]
            if matched:
                type_with_matches[itype] = matched

        if not type_with_matches:
            return "unknown", []

        # Return type with most keyword matches
        best_type = max(type_with_matches.keys(), key=lambda t: len(type_with_matches[t]))
        return best_type, type_with_matches[best_type]

    def normalize(self, raw_name: str | None) -> InstitutionMapping:
        """Normalize a raw institution name.

        Parameters
        ----------
        raw_name: Free-text institution name (typically Ukrainian).

        Returns
        -------
        InstitutionMapping with canonical name, type, and confidence.
        """
        if not raw_name or not raw_name.strip():
            return InstitutionMapping(
                raw_name=raw_name or "",
                canonical_name=None,
                institution_type="unknown",
                confidence=0.0,
                matched_via="unknown",
            )

        # Try fuzzy matching against seed institutions
        best_match = None
        best_score = 0.0
        best_overlap = 0.0

        for seed_inst in self.seed_institutions:
            canonical = seed_inst.get("canonical_name", "")
            aliases = seed_inst.get("aliases", [])
            fuzzy, overlap = self._fuzzy_score(raw_name, canonical, aliases)

            combined = 0.7 * fuzzy + 0.3 * overlap  # Weight fuzzy match more
            if combined > best_score:
                best_score = combined
                best_match = seed_inst
                best_overlap = overlap

        # If strong match found, use it
        if best_match and best_score >= 0.70:
            confidence = min(1.0, 0.75 + (best_score - 0.70) * 0.5)  # Start at 0.75 for 0.70 match
            return InstitutionMapping(
                raw_name=raw_name,
                canonical_name=best_match.get("canonical_name"),
                institution_type=best_match.get("institution_type", "unknown"),
                confidence=confidence,
                matched_via="seed_fuzzy",
                fuzzy_score=best_score,
                overlap_score=best_overlap,
            )

        # If moderate match, still consider it
        if best_match and best_score >= 0.50:
            confidence = 0.60 + (best_score - 0.50) * 0.3  # Start at 0.60 for 0.50 match
            return InstitutionMapping(
                raw_name=raw_name,
                canonical_name=best_match.get("canonical_name"),
                institution_type=best_match.get("institution_type", "unknown"),
                confidence=confidence,
                matched_via="seed_fuzzy",
                fuzzy_score=best_score,
                overlap_score=best_overlap,
            )

        # Fall back to keyword-based type extraction
        extracted_type, matched_kw = self._extract_type_from_keywords(raw_name)
        if extracted_type != "unknown":
            confidence = min(0.8, 0.3 + len(matched_kw) * 0.1)
            return InstitutionMapping(
                raw_name=raw_name,
                canonical_name=None,
                institution_type=extracted_type,
                confidence=confidence,
                matched_via="keyword_extract",
                fuzzy_score=0.0,
                overlap_score=0.0,
            )

        # No match at all
        return InstitutionMapping(
            raw_name=raw_name,
            canonical_name=None,
            institution_type="unknown",
            confidence=0.0,
            matched_via="unknown",
        )


# ============================================================================
# Taxonomy Mapper (post_type → sector, government_level)
# ============================================================================

class TaxonomyMapper:
    """Map post_type and post_category to normalized sector and government_level.

    Uses keyword matching to classify posts into:
      - sector: healthcare, judiciary, education, local_government, etc.
      - government_level: central, local, state_enterprise, commission, other
    """

    def __init__(self, sector_keywords: dict[str, list[list[str]]] | None = None,
                 govt_level_keywords: dict[str, list[list[str]]] | None = None):
        """Initialize mapper with keyword configurations.

        Parameters
        ----------
        sector_keywords:
            Dict[sector -> list of keyword lists]
        govt_level_keywords:
            Dict[govt_level -> list of keyword lists]
        """
        self.sector_keywords = sector_keywords or {}
        self.govt_level_keywords = govt_level_keywords or {}

    def map_sector(self, post_type: str) -> tuple[str, list[str]]:
        """Classify post_type to sector.

        Returns
        -------
        (sector, keywords_matched)
        """
        if not post_type or not post_type.strip():
            return "other", []

        post_upper = post_type.upper()

        # Try each sector in order
        for sector, keyword_groups in self.sector_keywords.items():
            for keyword_group in keyword_groups:
                for keyword in keyword_group:
                    if keyword in post_upper:
                        return sector, keyword_group
        return "other", []

    def map_government_level(self, post_type: str, post_category: str | None = None) -> tuple[str, list[str]]:
        """Classify post_type + post_category to government level.

        Returns
        -------
        (government_level, keywords_matched)
        """
        combined = f"{post_type or ''} {post_category or ''}".upper()

        # Try each level in order
        for level, keyword_groups in self.govt_level_keywords.items():
            for keyword_group in keyword_groups:
                for keyword in keyword_group:
                    if keyword in combined:
                        return level, keyword_group
        return "other", []


# ============================================================================
# Cohort Key Builder
# ============================================================================

class CohortKeyBuilder:
    """Build multi-dimensional cohort keys with fallback hierarchy.

    Cohort dimensions:
      - year: declaration_year
      - sector: from normalized taxonomy
      - government_level: from normalized taxonomy
      - region: primary_region (for area-based features)

    Fallback logic:
      - For income/assets/cash/confidentiality:
        year+sector+government_level → year+sector → year → global
      - For dwelling/agricultural area (region-sensitive):
        year+sector+government_level+region → year+sector+government_level → year+sector → year → global
    """

    def __init__(self, min_cohort_size: int = 30):
        """Initialize builder.

        Parameters
        ----------
        min_cohort_size:
            Minimum declarations required in cohort before fallback.
        """
        self.min_cohort_size = min_cohort_size
        self.fallback_log: list[dict[str, Any]] = []

    def build_key_for_income_assets(
        self,
        declaration_year: int,
        sector: str,
        government_level: str,
    ) -> str:
        """Build cohort key for income/assets/cash/confidentiality features.

        Returns
        -------
        Cohort key string: "2024_healthcare_central"
        """
        return f"{declaration_year}_{sector}_{government_level}"

    def build_key_for_area(
        self,
        declaration_year: int,
        sector: str,
        government_level: str,
        primary_region: str | None = None,
    ) -> str:
        """Build cohort key for area-based features (region-sensitive).

        Returns
        -------
        Cohort key string (with region if available): "2024_healthcare_central_kyiv"
        """
        if primary_region and primary_region.strip():
            return f"{declaration_year}_{sector}_{government_level}_{primary_region.lower()}"
        return f"{declaration_year}_{sector}_{government_level}"

    def get_fallback_chain_income_assets(
        self,
        declaration_year: int,
        sector: str,
        government_level: str,
    ) -> list[str]:
        """Get fallback chain for income/assets features in priority order.

        Returns
        -------
        List of cohort key strings for fallback (best → worst).
        """
        return [
            f"{declaration_year}_{sector}_{government_level}",
            f"{declaration_year}_{sector}",
            f"{declaration_year}",
            "global",
        ]

    def get_fallback_chain_area(
        self,
        declaration_year: int,
        sector: str,
        government_level: str,
        primary_region: str | None = None,
    ) -> list[str]:
        """Get fallback chain for area features (region-sensitive).

        Returns
        -------
        List of cohort key strings for fallback (best → worst).
        """
        chain = []
        if primary_region and primary_region.strip():
            chain.append(f"{declaration_year}_{sector}_{government_level}_{primary_region.lower()}")
        chain.extend([
            f"{declaration_year}_{sector}_{government_level}",
            f"{declaration_year}_{sector}",
            f"{declaration_year}",
            "global",
        ])
        return chain

    def log_fallback_usage(
        self,
        declarant_id: str,
        feature_type: str,
        original_key: str,
        used_key: str,
    ) -> None:
        """Log when fallback was used (for auditing)."""
        self.fallback_log.append({
            "declarant_id": declarant_id,
            "feature_type": feature_type,
            "original_key": original_key,
            "used_key": used_key,
        })


# ============================================================================
# Taxonomy Normalizer (main entry point)
# ============================================================================

class TaxonomyNormalizer:
    """Main entry point for full taxonomy normalization.

    Combines:
      - RoleClusterer
      - InstitutionNormalizer
      - TaxonomyMapper
      - CohortKeyBuilder
    """

    def __init__(
        self,
        role_clusterer: RoleClusterer | None = None,
        institution_normalizer: InstitutionNormalizer | None = None,
        taxonomy_mapper: TaxonomyMapper | None = None,
        cohort_key_builder: CohortKeyBuilder | None = None,
    ):
        """Initialize with component instances."""
        self.role_clusterer = role_clusterer or RoleClusterer()
        self.institution_normalizer = institution_normalizer or InstitutionNormalizer()
        self.taxonomy_mapper = taxonomy_mapper or TaxonomyMapper()
        self.cohort_key_builder = cohort_key_builder or CohortKeyBuilder()

    def normalize(
        self,
        work_post: str,
        work_place: str | None = None,
        post_type: str | None = None,
        post_category: str | None = None,
    ) -> TaxonomyNormalization:
        """Normalize a declarant's personal/professional profile.

        Parameters
        ----------
        work_post: Raw job title (typically Ukrainian).
        work_place: Raw institution/workplace name.
        post_type: Semi-structured post type from e-declaration.
        post_category: Job ranking category (e.g., категорія).

        Returns
        -------
        TaxonomyNormalization with all normalized fields.
        """
        # Cluster role
        role_mapping = self.role_clusterer.cluster(work_post)

        # Normalize institution
        institution_mapping = self.institution_normalizer.normalize(work_place)

        # Map sector and government level
        sector, sector_kw = self.taxonomy_mapper.map_sector(post_type or "")
        govt_level, govt_kw = self.taxonomy_mapper.map_government_level(
            post_type or "", post_category
        )

        # Use institution type as fallback for sector if no post_type match
        if sector == "other" and institution_mapping.institution_type != "unknown":
            sector = institution_mapping.institution_type

        return TaxonomyNormalization(
            work_post_raw=work_post,
            work_place_raw=work_place,
            post_type_raw=post_type or "",
            post_category_raw=post_category,

            role_family=role_mapping.role_family,
            role_family_confidence=role_mapping.confidence,
            sector=sector,
            government_level=govt_level,
            institution_family=institution_mapping.institution_type,
            institution_family_confidence=institution_mapping.confidence,

            role_mapping=role_mapping,
            institution_mapping=institution_mapping,
            sector_keywords_found=sector_kw,
            govt_level_keywords_found=govt_kw,
        )


# ============================================================================
# Configuration loading
# ============================================================================

def load_taxonomy_config(yaml_path: str) -> dict[str, Any]:
    """Load cohort taxonomy configuration from YAML file.

    Parameters
    ----------
    yaml_path: Path to cohort_taxonomy.yaml

    Returns
    -------
    Dict with keys: institutions, sector_keywords, government_level_keywords, cohort_configuration
    """
    if yaml is None:
        logger.warning("PyYAML not available; returning empty config")
        return {
            "institutions": [],
            "sector_keywords": {},
            "government_level_keywords": {},
            "cohort_configuration": {},
        }

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        logger.info(f"Loaded taxonomy config from {yaml_path}")
        return config
    except FileNotFoundError:
        logger.error(f"Taxonomy config file not found: {yaml_path}")
        return {
            "institutions": [],
            "sector_keywords": {},
            "government_level_keywords": {},
            "cohort_configuration": {},
        }
    except yaml.YAMLError as e:
        logger.error(f"Failed to parse YAML config: {e}")
        return {
            "institutions": [],
            "sector_keywords": {},
            "government_level_keywords": {},
            "cohort_configuration": {},
        }


def create_normalizer_from_config(yaml_path: str) -> TaxonomyNormalizer:
    """Convenience function: Load YAML config and create finalizer instance.

    Parameters
    ----------
    yaml_path: Path to cohort_taxonomy.yaml

    Returns
    -------
    Ready-to-use TaxonomyNormalizer.
    """
    config = load_taxonomy_config(yaml_path)

    role_clusterer = RoleClusterer()
    institution_normalizer = InstitutionNormalizer(
        seed_institutions=config.get("institutions", [])
    )
    taxonomy_mapper = TaxonomyMapper(
        sector_keywords=config.get("sector_keywords", {}),
        govt_level_keywords=config.get("government_level_keywords", {}),
    )
    cohort_config = config.get("cohort_configuration", {})
    min_size = cohort_config.get("min_cohort_size", 30)
    cohort_key_builder = CohortKeyBuilder(min_cohort_size=min_size)

    return TaxonomyNormalizer(
        role_clusterer=role_clusterer,
        institution_normalizer=institution_normalizer,
        taxonomy_mapper=taxonomy_mapper,
        cohort_key_builder=cohort_key_builder,
    )
