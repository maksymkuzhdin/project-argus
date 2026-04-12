from __future__ import annotations

import sys
import types
from decimal import Decimal
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

if "scripts.train_layer3" not in sys.modules:
    scripts_pkg = types.ModuleType("scripts")
    train_layer3 = types.ModuleType("scripts.train_layer3")
    train_layer3.FEATURE_NAMES = []
    sys.modules.setdefault("scripts", scripts_pkg)
    sys.modules["scripts.train_layer3"] = train_layer3

from app.config import settings
from app.scoring.cohort_taxonomy import TaxonomyNormalizer, create_normalizer_from_config
from app.scoring.layer3 import normalize_cohort
from app.scoring.rules import ScoringResult, score_declaration
from app.services import pipeline as pipeline_service


def _taxonomy_yaml_path() -> str:
    return str(Path(__file__).resolve().parents[1] / "app" / "scoring" / "cohort_taxonomy.yaml")


@pytest.mark.parametrize(
    "fixture_decl",
    [
        {
            "work_post": "Міністр фінансів України",
            "work_place": "Кабінет Міністрів України",
            "post_type": "Посада в органах державної влади",
            "post_category": "А",
        },
        {
            "work_post": "Міський голова",
            "work_place": "Київська міська рада",
            "post_type": "Посада в органах місцевого самоврядування",
            "post_category": "Б",
        },
        {
            "work_post": "Народний депутат України",
            "work_place": "Верховна Рада України",
            "post_type": "Посада в законодавчому органі",
            "post_category": "А",
        },
        {
            "work_post": "Суддя Верховного Суду",
            "work_place": "Верховний Суд України",
            "post_type": "Посада в органах судової влади",
            "post_category": "А",
        },
        {
            "work_post": "Прокурор",
            "work_place": "Офіс Генерального прокурора",
            "post_type": "Посада в органах прокуратури",
            "post_category": "Б",
        },
        {
            "work_post": "Головний державний інспектор митниці",
            "work_place": "Державна митна служба України",
            "post_type": "Посада в органах державної влади",
            "post_category": "Б",
        },
    ],
)
def test_taxonomy_normalizer_known_institutions(fixture_decl: dict[str, str]) -> None:
    normalizer = create_normalizer_from_config(_taxonomy_yaml_path())

    result = normalizer.normalize(
        work_post=fixture_decl["work_post"],
        work_place=fixture_decl["work_place"],
        post_type=fixture_decl["post_type"],
        post_category=fixture_decl["post_category"],
    )

    has_known_dimension = result.sector != "other" or result.government_level != "other"
    assert has_known_dimension
    assert max(result.role_family_confidence, result.institution_family_confidence) > 0.3


def test_normalize_cohort_returns_complete_dict() -> None:
    result = normalize_cohort(
        work_post="Міністр",
        work_place="Кабінет Міністрів України",
        source_name=None,
        post_type="1",
        normalizer=TaxonomyNormalizer(),
    )

    required_keys = {
        "role_family",
        "institution_type",
        "sector",
        "government_level",
        "confidence",
    }
    assert required_keys.issubset(result.keys())
    for key in required_keys:
        assert result[key] is not None


def test_score_declaration_passes_cohort_to_layer3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "layer3_enabled", True)
    monkeypatch.setattr(settings, "layer3_model_path", "missing-model.pkl")

    captured: dict[str, object] = {}

    def _fake_infer_anomaly(**kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr("app.scoring.rules.layer3_inference.infer_anomaly", _fake_infer_anomaly)

    result = score_declaration(
        total_income=Decimal("120000"),
        total_assets=Decimal("300000"),
        cash_holdings=Decimal("70000"),
        bank_deposits=Decimal("50000"),
        total_value_fields=10,
        unknown_value_fields=1,
        largest_acquisition_cost=Decimal("10000"),
        ownership_declarant=1,
        ownership_family=0,
        ownership_total=1,
        incomes=[{"amount": Decimal("120000"), "person_ref": "1", "amount_status": None}],
        monetary_assets=[{"amount": Decimal("70000"), "asset_type": "Готівка", "currency_code": "UAH", "person_ref": "1", "amount_status": None}],
        real_estate=[],
        vehicles=[],
        family_members=[],
        declaration_year=2024,
        declaration_sector="executive",
        declaration_gov_level="national",
    )

    assert result is not None
    assert captured["sector"] == "executive"
    assert captured["government_level"] == "national"


def test_pipeline_populates_sector_from_taxonomy(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_score_declaration(**kwargs):
        captured.update(kwargs)
        return ScoringResult(total_score=0.0)

    monkeypatch.setattr(pipeline_service, "score_declaration", _fake_score_declaration)

    raw = {
        "id": "tax-pipeline-1",
        "declaration_year": 2024,
        "declaration_type": 1,
        "data": {
            "step_1": {
                "data": {
                    "firstname": "Іван",
                    "lastname": "Іваненко",
                    "middlename": "Іванович",
                    "workPost": "Прокурор",
                    "workPlace": "Офіс Генерального прокурора",
                    "postType": "Посада в органах прокуратури",
                    "postCategory": "Б",
                }
            },
            "step_2": {"isNotApplicable": 1, "data": []},
            "step_3": {"isNotApplicable": 1, "data": []},
            "step_6": {"isNotApplicable": 1, "data": []},
            "step_11": {"isNotApplicable": 1, "data": []},
            "step_12": {"isNotApplicable": 1, "data": []},
            "step_17": {"isNotApplicable": 1, "data": []},
        },
    }

    full = pipeline_service.process_declaration_full(raw)

    assert full["cohort_taxonomy"] is not None
    assert full["cohort_taxonomy"]["sector"] not in {None, "other", "unknown"}
    assert full["cohort_taxonomy"]["government_level"] not in {None, "unknown"}
    assert captured.get("cohort_key_used") != "unknown_unknown"
