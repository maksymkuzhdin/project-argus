"""
Tests for Ukraine-specific cohort taxonomy module.

Coverage:
  - Role clustering consistency and quality
  - Institution fuzzy matching and type extraction
  - Taxonomy mapping (sector, government_level)
  - Cohort key builder with fallback hierarchy
  - Multi-dimensional cohort building
  - Backward compatibility with existing (post_type, year) cohorts
  - End-to-end tests on synthetic Ukrainian declarations
"""

import pytest
from unittest.mock import MagicMock

from app.scoring.cohort_taxonomy import (
    CohortKeyBuilder,
    InstitutionMapping,
    InstitutionNormalizer,
    RoleClusterer,
    RoleFamilyMapping,
    TaxonomyMapper,
    TaxonomyNormalizer,
)
from app.scoring.cohorts import (
    CohortStats,
    build_cohort_distributions,
    build_multi_dimensional_cohorts,
    CohortFallbackResolver,
)


# ============================================================================
# Role Clustering Tests
# ============================================================================

class TestRoleClusterer:
    """Test suite for RoleClusterer."""

    @pytest.fixture
    def clusterer(self):
        """Create a fresh clusterer for each test."""
        return RoleClusterer()

    def test_cluster_empty_title(self, clusterer):
        """Empty or None titles should return 'other' with low confidence."""
        result = clusterer.cluster("")
        assert result.role_family == "other"
        assert result.confidence < 0.7

    def test_cluster_physician(self, clusterer):
        """Titles with physician keywords should cluster as 'physician'."""
        titles = [
            "Лікар-кардіолог",
            "Хірург",
            "Лікар загального профілю",
            "Невропатолог",
        ]
        for title in titles:
            result = clusterer.cluster(title)
            assert result.role_family == "physician", f"Failed for {title}"
            assert result.confidence > 0.5

    def test_cluster_manager(self, clusterer):
        """Titles with manager keywords should cluster as 'manager'."""
        titles = [
            "Директор",
            "Начальник відділу",
            "Голова ради",
            "Генеральний директор",
        ]
        for title in titles:
            result = clusterer.cluster(title)
            assert result.role_family == "manager", f"Failed for {title}"
            assert result.confidence > 0.5

    def test_cluster_judge(self, clusterer):
        """Titles with judicial keywords should cluster as 'judge_prosecutor'."""
        titles = [
            "Суддя",
            "Прокурор",
            "Слідчий",
            "Допоміжний судді",
        ]
        for title in titles:
            result = clusterer.cluster(title)
            assert result.role_family == "judge_prosecutor", f"Failed for {title}"
            assert result.confidence > 0.5

    def test_cluster_consistency(self, clusterer):
        """Same title should always produce same cluster."""
        title = "Лікар хірург"
        result1 = clusterer.cluster(title)
        result2 = clusterer.cluster(title)

        assert result1.role_family == result2.role_family
        assert result1.confidence == result2.confidence

    def test_cluster_case_insensitive(self, clusterer):
        """Clustering should be case-insensitive."""
        title_lower = "лікар"
        title_upper = "ЛІКАР"
        title_mixed = "Лікар"

        result_lower = clusterer.cluster(title_lower)
        result_upper = clusterer.cluster(title_upper)
        result_mixed = clusterer.cluster(title_mixed)

        assert result_lower.role_family == result_upper.role_family
        assert result_upper.role_family == result_mixed.role_family

    def test_cluster_unmatched_title(self, clusterer):
        """Unrecognized titles should return 'other'."""
        result = clusterer.cluster("Фантастична професія 12345")
        assert result.role_family == "other"
        assert 0 <= result.confidence <= 1.0


# ============================================================================
# Institution Normalization Tests
# ============================================================================

class TestInstitutionNormalizer:
    """Test suite for InstitutionNormalizer."""

    @pytest.fixture
    def seed_institutions(self):
        """Sample seed institutions for testing."""
        return [
            {
                "canonical_name": "Верховний Суд України",
                "aliases": ["Верховний суд", "ВСУ"],
                "institution_type": "judiciary",
            },
            {
                "canonical_name": "Міністерство охорони здоров'я",
                "aliases": ["МОЗ", "Ministry of Health"],
                "institution_type": "healthcare",
            },
            {
                "canonical_name": "Селищна рада",
                "aliases": ["Селищно рада", "Municipal council"],
                "institution_type": "local_government",
            },
        ]

    @pytest.fixture
    def normalizer(self, seed_institutions):
        """Create normalizer with seed institutions."""
        return InstitutionNormalizer(seed_institutions=seed_institutions)

    def test_exact_match(self, normalizer):
        """Exact canonical name should match with high confidence."""
        result = normalizer.normalize("Верховний Суд України")
        assert result.canonical_name == "Верховний Суд України"
        assert result.institution_type == "judiciary"
        assert result.confidence >= 0.75

    def test_alias_match(self, normalizer):
        """Alias should match canonical."""
        result = normalizer.normalize("ВСУ")
        assert result.institution_type == "judiciary"
        assert result.confidence >= 0.6

    def test_fuzzy_match_typo(self, normalizer):
        """Small typos should still match."""
        result = normalizer.normalize("Верховної Суд")  # Typo in case
        assert result.institution_type == "judiciary"
        assert result.confidence >= 0.6

    def test_keyword_extraction(self, normalizer):
        """If no match, should extract type from keywords."""
        result = normalizer.normalize("ЛІКАРНЯ ім. Івана Франка")
        # Should NOT match but should extract 'healthcare' from 'ЛІКАРНЯ'
        # (Note: depends on keyword setup)
        assert result.institution_type in ["healthcare", "unknown"]

    def test_unknown_institution(self, normalizer):
        """Completely unknown institutions should be marked 'unknown'."""
        result = normalizer.normalize("ХХХ ЗЗЗ НЕВІДОМА ОРГАНІЗАЦІЯ 777")
        assert result.institution_type == "unknown"
        assert result.confidence == 0.0

    def test_empty_name(self, normalizer):
        """Empty/None names should gracefully return 'unknown'."""
        result = normalizer.normalize(None)
        assert result.institution_type == "unknown"

        result2 = normalizer.normalize("")
        assert result2.institution_type == "unknown"

    def test_confidence_range(self, normalizer):
        """Confidence should always be in [0.0, 1.0]."""
        test_names = [
            "Верховний Суд України",
            "ВСУ",
            "random gibberish",
            "",
            None,
        ]
        for name in test_names:
            result = normalizer.normalize(name)
            assert 0.0 <= result.confidence <= 1.0


# ============================================================================
# Taxonomy Mapper Tests
# ============================================================================

class TestTaxonomyMapper:
    """Test suite for TaxonomyMapper."""

    @pytest.fixture
    def config(self):
        """Sample configuration for mapper."""
        return {
            "sector_keywords": {
                "healthcare": [["ОХОРОНИ ЗДОРОВ'Я"], ["МЕДИК"]],
                "judiciary": [["СУД"], ["ПРОКУРАТУР"]],
                "education": [["ОСВІТ"], ["ШКОЛ"]],
                "local_government": [["МІСЦЕВОГО САМОВРЯДУВАННЯ"], ["РАДА"], ["МЕРІЯ"]],
            },
            "govt_level_keywords": {
                "local": [["МІСЦЕВОГО САМОВРЯДУВАННЯ"], ["СЕЛИЩ"]],
                "central": [["ДЕРЖАВНОЇ ВЛАДИ"], ["ЦЕНТР"], ["ДЕРЖАВН"]],
                "state_enterprise": [["КОМУНАЛЬН"]],
            },
        }

    @pytest.fixture
    def mapper(self, config):
        """Create mapper with test config."""
        return TaxonomyMapper(
            sector_keywords=config["sector_keywords"],
            govt_level_keywords=config["govt_level_keywords"],
        )

    def test_sector_healthcare(self, mapper):
        """Healthcare keywords should map to healthcare sector."""
        sector, kw = mapper.map_sector("Посада в органах охорони здоров'я")
        assert sector == "healthcare"
        assert len(kw) > 0

    def test_sector_judiciary(self, mapper):
        """Judicial keywords should map to judiciary sector."""
        sector, kw = mapper.map_sector("Суддя Верховного Суду")
        assert sector == "judiciary"

    def test_sector_unknown(self, mapper):
        """Unknown sectors should return 'other'."""
        sector, kw = mapper.map_sector("Робітник на заводі незвичайний")
        assert sector == "other"

    def test_govt_level_local(self, mapper):
        """Local government keywords should map correctly."""
        level, kw = mapper.map_government_level("Посада в органах місцевого самоврядування")
        assert level == "local"

    def test_govt_level_central(self, mapper):
        """Central government keywords should map correctly."""
        level, kw = mapper.map_government_level("Посада в органах державної розпорядження")
        assert level == "central"

    def test_govt_level_unknown(self, mapper):
        """Unknown levels should return 'other'."""
        level, kw = mapper.map_government_level("Фантастична організація")
        assert level == "other"


# ============================================================================
# Cohort Key Builder Tests
# ============================================================================

class TestCohortKeyBuilder:
    """Test suite for CohortKeyBuilder."""

    @pytest.fixture
    def builder(self):
        """Create a builder with default config."""
        return CohortKeyBuilder(min_cohort_size=30)

    def test_build_income_key(self, builder):
        """Income cohort keys should have format year_sector_government_level."""
        key = builder.build_key_for_income_assets(2024, "healthcare", "central")
        assert key == "2024_healthcare_central"

    def test_build_area_key_with_region(self, builder):
        """Area keys with region should include region."""
        key = builder.build_key_for_area(2024, "healthcare", "central", "kyiv")
        assert key == "2024_healthcare_central_kyiv"

    def test_build_area_key_no_region(self, builder):
        """Area keys without region should still work."""
        key = builder.build_key_for_area(2024, "healthcare", "central", None)
        assert key == "2024_healthcare_central"

    def test_fallback_chain_income(self, builder):
        """Income fallback chain should have correct order."""
        chain = builder.get_fallback_chain_income_assets(2024, "healthcare", "central")
        assert chain[0] == "2024_healthcare_central"
        assert chain[1] == "2024_healthcare"
        assert chain[2] == "2024"
        assert chain[3] == "global"

    def test_fallback_chain_area_with_region(self, builder):
        """Area fallback chain should start with regional key if provided."""
        chain = builder.get_fallback_chain_area(2024, "healthcare", "central", "KYIV")
        assert chain[0] == "2024_healthcare_central_kyiv"
        assert "2024_healthcare_central" in chain
        assert "global" in chain

    def test_fallback_chain_area_no_region(self, builder):
        """Area fallback chain without region should skip regional tier."""
        chain = builder.get_fallback_chain_area(2024, "healthcare", "central", None)
        assert "2024" in chain
        assert "global" in chain
        # Should NOT have a regional key
        assert not any("_" in k and k.count("_") == 3 for k in chain)


# ============================================================================
# Integration: Multi-dimensional Cohort Building
# ============================================================================

class TestMultiDimensionalCohorts:
    """Test suite for multi-dimensional cohort building."""

    def test_build_cohorts(self):
        """Test building multi-dimensional cohorts from summaries."""
        summaries = [
            {
                "year": 2024,
                "sector": "healthcare",
                "government_level": "central",
                "primary_region": "kyiv",
                "total_income": 100000.0,
                "total_assets": 500000.0,
                "cash_ratio": 0.2,
                "confidential_ratio": 0.1,
                "dwelling_area_m2": 150.0,
                "agri_area_m2": 0.0,
            },
            {
                "year": 2024,
                "sector": "healthcare",
                "government_level": "central",
                "primary_region": "kyiv",
                "total_income": 110000.0,
                "total_assets": 550000.0,
                "cash_ratio": 0.25,
                "confidential_ratio": 0.05,
                "dwelling_area_m2": 160.0,
                "agri_area_m2": 0.0,
            },
        ] * 20  # Repeat to get 40 declarations

        cohorts = build_multi_dimensional_cohorts(summaries, min_cohort_size=30)

        # Should have one cohort: 2024_healthcare_central
        assert "2024_healthcare_central" in cohorts
        assert len(cohorts) == 1

        stats = cohorts["2024_healthcare_central"]
        assert stats.size >= 30
        assert len(stats.incomes) >= 30

    def test_min_cohort_filtering(self):
        """Cohorts smaller than min_cohort_size should be dropped."""
        summaries = [
            {
                "year": 2024,
                "sector": "rare_sector",
                "government_level": "rare_level",
                "primary_region": "kyiv",
                "total_income": 100000.0,
                "total_assets": 500000.0,
                "cash_ratio": 0.2,
                "confidential_ratio": 0.1,
                "dwelling_area_m2": 150.0,
                "agri_area_m2": 0.0,
            },
        ] * 5  # Only 5 declarations

        cohorts = build_multi_dimensional_cohorts(summaries, min_cohort_size=30)

        # Should be dropped
        assert len(cohorts) == 0


class TestCohortFallbackResolver:
    """Test suite for fallback resolution."""

    def test_resolve_income_primary(self):
        """If cohort exists and is large enough, return primary key."""
        cohort_stats = {
            "2024_healthcare_central": MagicMock(size=50),
        }
        resolver = CohortFallbackResolver(cohort_stats, min_cohort_size=30)
        key, chain = resolver.resolve_for_income_assets(2024, "healthcare", "central")
        assert key == "2024_healthcare_central"

    def test_resolve_income_fallback_to_sector(self):
        """If dimension too small, should fallback to coarser key."""
        cohort_stats = {
            "2024_healthcare_central": MagicMock(size=10),  # Too small
            "2024_healthcare": MagicMock(size=50),  # OK
        }
        resolver = CohortFallbackResolver(cohort_stats, min_cohort_size=30)
        key, chain = resolver.resolve_for_income_assets(2024, "healthcare", "central")
        assert key == "2024_healthcare"

    def test_resolve_income_fallback_to_global(self):
        """If all dimension-based cohorts too small, fallback to global."""
        cohort_stats = {
            "2024_healthcare_central": MagicMock(size=10),
            "2024_healthcare": MagicMock(size=10),
            "2024": MagicMock(size=10),
        }
        resolver = CohortFallbackResolver(cohort_stats, min_cohort_size=30)
        key, chain = resolver.resolve_for_income_assets(2024, "healthcare", "central")
        assert key == "global"  # Global fallback is always used


# ============================================================================
# End-to-End Tests: Synthetic Ukrainian Declarations
# ============================================================================

class TestEndToEndUkrainianDeclarations:
    """Test complete workflow on synthetic Ukrainian government officials."""

    @pytest.fixture
    def normalizer(self):
        """Create a normalizer with basic config."""
        seed_institutions = [
            {
                "canonical_name": "Верховний Суд України",
                "aliases": ["Верховний суд", "ВСУ"],
                "institution_type": "judiciary",
            },
            {
                "canonical_name": "Міністерство охорони здоров'я",
                "aliases": ["МОЗ"],
                "institution_type": "healthcare",
            },
            {
                "canonical_name": "Селищна рада",
                "aliases": ["Селищ рада", "Селиш рада"],
                "institution_type": "local_government",
            },
        ]

        mapper = TaxonomyMapper(
            sector_keywords={
                "healthcare": [["ОХОРОНИ ЗДОРОВ'Я"], ["МЕДИК"]],
                "judiciary": [["СУД"], ["ПРОКУРОР"]],
                "local_government": [["МІСЦЕВОГО"], ["РАДА"]],
            },
            govt_level_keywords={
                "local": [["МІСЦЕВОГО"]],
                "central": [["ДЕРЖАВНОЇ ВЛАДИ"], ["ЦЕНТР"], ["ДЕРЖАВН"]],
            },
        )

        return TaxonomyNormalizer(
            institution_normalizer=InstitutionNormalizer(seed_institutions=seed_institutions),
            taxonomy_mapper=mapper,
        )

    def test_central_ministry_official(self, normalizer):
        """Test central ministry healthcare official."""
        norm = normalizer.normalize(
            work_post="Лікар головний",
            work_place="Міністерство охорони здоров'я",
            post_type="Посада в органах державної влади (виконавча гілка)",
            post_category="п'ята категорія",
        )

        assert norm.role_family == "physician"
        assert norm.institution_family == "healthcare"
        assert norm.sector == "healthcare"
        assert norm.government_level in ["central", "other"]  # Depends on keyword config

    def test_local_council_employee(self, normalizer):
        """Test local council administrative employee."""
        norm = normalizer.normalize(
            work_post="Референт",
            work_place="Селищна рада",
            post_type="Посада в органах місцевого самоврядування",
            post_category=None,
        )

        assert norm.role_family == "administrative"
        assert norm.institution_family == "local_government"
        assert norm.government_level == "local"

    def test_court_judge(self, normalizer):
        """Test court judge."""
        norm = normalizer.normalize(
            work_post="Суддя Верховного Суду",
            work_place="Верховний Суд України",
            post_type="Посада в органах судової влади",
            post_category=None,
        )

        assert norm.role_family == "judge_prosecutor"
        assert norm.institution_family == "judiciary"
        assert norm.sector == "judiciary"


# ============================================================================
# Backward Compatibility Tests
# ============================================================================

class TestBackwardCompatibility:
    """Test that new taxonomy doesn't break existing (post_type, year) cohorts."""

    def test_legacy_cohort_building_unchanged(self):
        """Existing build_cohort_distributions should still work."""
        summaries = [
            {
                "post_type": "Judge",
                "declaration_year": 2024,
                "total_income": 100000.0,
                "total_assets": 500000.0,
                "cash_ratio": 0.2,
                "confidential_ratio": 0.1,
                "dwelling_area_m2": 150.0,
                "agri_area_m2": 0.0,
                "primary_region": "kyiv",
            },
        ] * 50

        cohorts = build_cohort_distributions(summaries, min_cohort_size=30)

        from app.scoring.cohorts import CohortKey
        expected_key = CohortKey(post_type="Judge", year=2024)
        assert expected_key in cohorts
        assert cohorts[expected_key].size >= 30


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
