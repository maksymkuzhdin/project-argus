"""Layer 3 unsupervised scoring helpers.

This module provides a safe adapter around an optional Isolation Forest model.
If the model artifact is unavailable (or dependencies are missing), callers
receive ``None`` and can continue with deterministic scoring only.
"""

from __future__ import annotations

import math
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Layer3Result:
    """Normalized unsupervised anomaly inference output."""

    anomaly_score: float
    confidence: float
    percentile: float
    top_deviations: list[dict[str, Any]]


_MODEL_CACHE: dict[str, tuple[float, Any]] = {}


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        f = float(value)
        if not math.isfinite(f):
            return default
        return f
    except Exception:
        return default


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
) -> dict[str, float]:
    """Build a stable numeric feature map for Layer 3 inference."""
    income = max(0.0, _to_float(total_income))
    assets = max(0.0, _to_float(total_assets))
    cash = max(0.0, _to_float(cash_holdings))
    bank = max(0.0, _to_float(bank_deposits))

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
    asset_income_ratio = (assets / income) if income > 0 else (10.0 if assets > 0 else 0.0)

    return {
        "total_income": income,
        "total_assets": assets,
        "cash_holdings": cash,
        "bank_deposits": bank,
        "cash_ratio": cash_ratio,
        "asset_income_ratio": asset_income_ratio,
        "unknown_share": unknown_share,
        "confidential_ratio": max(0.0, min(1.0, _to_float(confidential_ratio))),
        "family_ownership_share": family_share,
        "declarant_ownership_share": declarant_share,
        "incomes_count": float(max(0, incomes_count)),
        "real_estate_count": float(max(0, real_estate_count)),
        "vehicles_count": float(max(0, vehicles_count)),
        "monetary_count": float(max(0, monetary_count)),
        "declaration_year": float(declaration_year or 0),
    }


def _load_model(model_path: str) -> Any | None:
    """Load and cache model artifact by path and mtime."""
    p = Path(model_path)
    if not p.exists() or not p.is_file():
        return None

    mtime = p.stat().st_mtime
    cached = _MODEL_CACHE.get(str(p))
    if cached and cached[0] == mtime:
        return cached[1]

    with p.open("rb") as fh:
        artifact = pickle.load(fh)

    _MODEL_CACHE[str(p)] = (mtime, artifact)
    return artifact


def _sigmoid(x: float) -> float:
    # Map raw decision values into a bounded anomaly score.
    return 1.0 / (1.0 + math.exp(-x))


def _extract_top_deviations(
    *,
    feature_order: list[str],
    vector: list[float],
    medians: list[float] | None,
    scales: list[float] | None,
) -> list[dict[str, Any]]:
    if not medians or not scales or len(medians) != len(vector) or len(scales) != len(vector):
        return []

    rows: list[tuple[str, float, float]] = []
    for idx, key in enumerate(feature_order):
        scale = scales[idx]
        if scale is None or scale == 0:
            continue
        z = abs((vector[idx] - medians[idx]) / scale)
        rows.append((key, round(z, 3), round(vector[idx], 3)))

    rows.sort(key=lambda x: x[1], reverse=True)
    top = rows[:3]
    return [
        {
            "feature_name": r[0],
            "deviation": r[1],
            "value": r[2],
        }
        for r in top
    ]


def infer_anomaly(
    *,
    feature_map: dict[str, float],
    model_path: str,
) -> Layer3Result | None:
    """Run inference against a serialized Isolation Forest artifact.

    Expected artifact structure (dict):
    - model: fitted estimator/pipeline with ``decision_function``
    - feature_order: list[str]
    - decision_min, decision_max: optional calibration bounds
    - robust_medians, robust_scales: optional explainability metadata
    """
    artifact = _load_model(model_path)
    if artifact is None:
        return None

    if not isinstance(artifact, dict):
        # Support direct pickled estimator with implicit feature ordering.
        model = artifact
        feature_order = sorted(feature_map.keys())
        decision_min = None
        decision_max = None
        medians = None
        scales = None
    else:
        model = artifact.get("model")
        feature_order = artifact.get("feature_order") or sorted(feature_map.keys())
        decision_min = artifact.get("decision_min")
        decision_max = artifact.get("decision_max")
        medians = artifact.get("robust_medians")
        scales = artifact.get("robust_scales")

    if model is None or not hasattr(model, "decision_function"):
        return None

    vector = [float(feature_map.get(name, 0.0)) for name in feature_order]

    model_vector = vector
    if medians and scales and len(medians) == len(vector) and len(scales) == len(vector):
        model_vector = []
        for idx in range(len(vector)):
            scale = float(scales[idx]) if scales[idx] not in (None, 0) else 1.0
            model_vector.append((vector[idx] - float(medians[idx])) / scale)

    try:
        decision = float(model.decision_function([model_vector])[0])
    except Exception:
        return None

    # Isolation Forest: lower decision value means more anomalous.
    if decision_min is not None and decision_max is not None and decision_max > decision_min:
        norm = (decision - float(decision_min)) / (float(decision_max) - float(decision_min))
        norm = max(0.0, min(1.0, norm))
        anomaly_score = 1.0 - norm
    else:
        anomaly_score = 1.0 - _sigmoid(decision * 4.0)

    anomaly_score = max(0.0, min(1.0, anomaly_score))
    percentile = anomaly_score
    confidence = max(0.5, min(0.99, 0.5 + (abs(anomaly_score - 0.5) * 0.8)))

    top = _extract_top_deviations(
        feature_order=feature_order,
        vector=vector,
        medians=medians,
        scales=scales,
    )

    return Layer3Result(
        anomaly_score=round(anomaly_score, 4),
        confidence=round(confidence, 3),
        percentile=round(percentile, 4),
        top_deviations=top,
    )



def normalize_cohort(
    *,
    work_post: str,
    work_place: str | None,
    source_name: str | None,
    post_type: str | None,
    post_category: str | None = None,
    normalizer: Any | None = None,
) -> dict[str, Any]:
    """Normalize a declaration record into enriched cohort dimensions.
    
    Uses TaxonomyNormalizer to classify institution, role family, sector, and government level.
    Falls back to basic classification if normalizer not available.
    
    Args:
        work_post: Raw job title
        work_place: Raw workplace/organization name
        source_name: Raw source name (currently unused, reserved for future use)
        post_type: Post type field for sector/government level mapping
        post_category: Job category (e.g., категорія)
        normalizer: TaxonomyNormalizer instance (optional)
    
    Returns:
        dict with keys: role_family, institution_type, sector,
                       government_level, confidence, and raw values
    """
    if normalizer is None:
        # Fallback to minimal classification when normalizer not available
        return {
            "role_family": "unknown",
            "institution_type": "unknown",
            "sector": "unknown",
            "government_level": "unknown",
            "confidence": 0.0,
            "work_place": work_place,
        }
    
    # Use TaxonomyNormalizer.normalize() to get all normalized fields
    result = normalizer.normalize(
        work_post=work_post,
        work_place=work_place or "",
        post_type=post_type,
        post_category=post_category,
    )
    
    return {
        "role_family": result.role_family,
        "institution_type": result.institution_family,
        "sector": result.sector,
        "government_level": result.government_level,
        "confidence": result.role_family_confidence * result.institution_family_confidence,
        "work_place": work_place,
        "work_post": work_post,
        "post_type": post_type,
    }
