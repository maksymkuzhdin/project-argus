"""Layer 3 unsupervised scoring helpers.

This module provides a safe adapter around an optional Isolation Forest model.
If the model artifact is unavailable (or dependencies are missing), callers
receive ``None`` and can continue with deterministic scoring only.
"""

from __future__ import annotations

import json
import logging
import math
import pickle
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.train_layer3 import FEATURE_NAMES  # type: ignore[import-not-found]
from app.config import settings


@dataclass
class Layer3Result:
    """Normalized unsupervised anomaly inference output."""

    anomaly_score: float
    confidence: float
    percentile: float
    top_deviations: list[dict[str, Any]]


_MODEL_CACHE: dict[str, tuple[float, Any]] = {}
_REGISTRY_SINGLETON: dict[str, Any] | None = None
_REGISTRY_MODEL_DIR: Path | None = None
_REGISTRY_MTIME: float | None = None
_REGISTRY_MISSING_WARNED: set[str] = set()

logger = logging.getLogger(__name__)


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
    income_yoy_delta_pct: float = 0.0,
    assets_yoy_delta_pct: float = 0.0,
    cash_ratio_yoy_delta: float = 0.0,
    confidential_ratio_yoy_delta: float = 0.0,
    asset_income_ratio_delta: float = 0.0,
    new_property_count: float = 0.0,
    dropped_property_count: float = 0.0,
    max_single_asset_jump_pct: float = 0.0,
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

    feature_map = {
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


def _model_dir_from_path(model_path: str) -> Path:
    raw = Path(model_path)
    if raw.suffix.lower() == ".pkl":
        return raw.parent
    return raw


def _load_registry_singleton(model_dir: Path) -> dict[str, Any] | None:
    global _REGISTRY_SINGLETON, _REGISTRY_MODEL_DIR, _REGISTRY_MTIME

    registry_path = model_dir / "layer3_registry.json"
    cache_valid = (
        _REGISTRY_MODEL_DIR == model_dir
        and _REGISTRY_SINGLETON is not None
        and registry_path.exists()
    )
    if cache_valid:
        try:
            mtime = registry_path.stat().st_mtime
        except OSError:
            mtime = None
        if mtime is not None and _REGISTRY_MTIME == mtime:
            return _REGISTRY_SINGLETON

    if not registry_path.exists():
        key = str(registry_path)
        if key not in _REGISTRY_MISSING_WARNED:
            logger.warning(
                "Layer 3 registry not found at %s; falling back to legacy single-model behavior.",
                registry_path,
            )
            _REGISTRY_MISSING_WARNED.add(key)
        _REGISTRY_SINGLETON = None
        _REGISTRY_MODEL_DIR = model_dir
        _REGISTRY_MTIME = None
        return None

    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        if not isinstance(registry, dict):
            raise ValueError("Registry content must be a JSON object")
    except Exception as exc:
        logger.warning(
            "Failed to load Layer 3 registry at %s (%s); using legacy single-model behavior.",
            registry_path,
            exc,
        )
        _REGISTRY_SINGLETON = None
        _REGISTRY_MODEL_DIR = model_dir
        _REGISTRY_MTIME = None
        return None

    _REGISTRY_SINGLETON = registry
    _REGISTRY_MODEL_DIR = model_dir
    _REGISTRY_MTIME = registry_path.stat().st_mtime
    return registry


def _resolve_model_from_path(
    *,
    model_path: str,
    sector: str | None,
    government_level: str | None,
) -> Any | None:
    base = Path(model_path)

    if base.is_file() and base.suffix.lower() == ".pkl":
        logger.info("Layer 3 model selected: %s (legacy single-model)", base.name)
        return _load_model(str(base))

    model_dir = _model_dir_from_path(model_path)
    registry = _load_registry_singleton(model_dir)

    # Backward compatibility: no registry means use model_path exactly as before.
    if registry is None:
        legacy_path = Path(model_path)
        if legacy_path.exists() and legacy_path.is_file():
            logger.info("Layer 3 model selected: %s (legacy single-model fallback)", legacy_path.name)
            return _load_model(str(legacy_path))
        return None

    cohort_key = f"{_slug(sector)}_{_slug(government_level)}"
    fallback_used = False
    selected_path: Path | None = None

    cohorts = registry.get("cohorts") if isinstance(registry, dict) else None
    if isinstance(cohorts, dict):
        entry = cohorts.get(cohort_key)
        if isinstance(entry, dict):
            rel = entry.get("path")
            if isinstance(rel, str):
                candidate = model_dir / rel
                if candidate.exists():
                    selected_path = candidate

    if selected_path is None:
        fallback_used = True
        global_info = registry.get("global") if isinstance(registry, dict) else None
        if isinstance(global_info, dict):
            rel = global_info.get("path")
            if isinstance(rel, str):
                candidate = model_dir / rel
                if candidate.exists():
                    selected_path = candidate

    if selected_path is None:
        fallback_used = True
        fallback = model_dir / "layer3_global.pkl"
        if fallback.exists():
            selected_path = fallback

    if selected_path is None:
        logger.warning(
            "Layer 3 model resolution failed for cohort=%s (sector=%s, government_level=%s).",
            cohort_key,
            sector,
            government_level,
        )
        return None

    logger.info(
        "Layer 3 model selected: %s | cohort=%s | fallback=%s",
        selected_path.name,
        cohort_key,
        fallback_used,
    )
    return _load_model(str(selected_path))


def resolve_model(sector: str | None, government_level: str | None) -> Any | None:
    """Resolve and load the best Layer 3 model using configured model path + registry.

    Prefers cohort-specific models and falls back to global when needed.
    """
    configured_path = str(getattr(settings, "layer3_model_path", "") or "").strip()
    if not configured_path:
        return None
    return _resolve_model_from_path(
        model_path=configured_path,
        sector=sector,
        government_level=government_level,
    )


def _prime_registry_cache() -> None:
    configured_path = str(getattr(settings, "layer3_model_path", "") or "").strip()
    if not configured_path:
        return
    p = Path(configured_path)
    if p.suffix.lower() == ".pkl":
        return
    _load_registry_singleton(_model_dir_from_path(configured_path))


_prime_registry_cache()


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
    sector: str | None = None,
    government_level: str | None = None,
) -> Layer3Result | None:
    """Run inference against a serialized Isolation Forest artifact.

    Expected artifact structure (dict):
    - model: fitted estimator/pipeline with ``decision_function``
    - feature_order: list[str]
    - decision_min, decision_max: optional calibration bounds
    - robust_medians, robust_scales: optional explainability metadata
    """
    configured_path = str(getattr(settings, "layer3_model_path", "") or "")
    chosen_model_path = str(model_path or configured_path)
    if chosen_model_path == configured_path:
        artifact = resolve_model(sector, government_level)
    else:
        artifact = _resolve_model_from_path(
            model_path=chosen_model_path,
            sector=sector,
            government_level=government_level,
        )
    if artifact is None:
        return None

    if not isinstance(artifact, dict):
        # Support direct pickled estimator with implicit feature ordering.
        model = artifact
        feature_order = list(FEATURE_NAMES)
        decision_min = None
        decision_max = None
        medians = None
        scales = None
    else:
        model = artifact.get("model")
        feature_order = artifact.get("feature_order") or list(FEATURE_NAMES)
        decision_min = artifact.get("decision_min")
        decision_max = artifact.get("decision_max")
        medians = artifact.get("robust_medians")
        scales = artifact.get("robust_scales")

    # New artifacts store the sklearn Pipeline directly.
    if not isinstance(artifact, dict):
        try:
            scaler = getattr(artifact, "named_steps", {}).get("scaler")
            medians = list(getattr(scaler, "center_", [])) if scaler is not None else None
            scales = list(getattr(scaler, "scale_", [])) if scaler is not None else None
        except Exception:
            medians = None
            scales = None

    if model is None or not hasattr(model, "decision_function"):
        return None

    vector = [float(feature_map.get(name, 0.0)) for name in feature_order]
    model_vector = vector

    # Legacy dict artifacts require manual robust normalization.
    if isinstance(artifact, dict) and medians and scales and len(medians) == len(vector) and len(scales) == len(vector):
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
