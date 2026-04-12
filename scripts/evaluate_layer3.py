"""Evaluate trained Layer 3 models and produce diagnostics.

Usage examples:
  python scripts/evaluate_layer3.py --model-dir output/models
  python scripts/evaluate_layer3.py --model-dir output/models --scores-csv output/scores.csv
  python scripts/evaluate_layer3.py --model-dir output/models --scores-csv output/scores.csv --compare-model-dir output/models_prev
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import math
import pickle
import random
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))


def _load_feature_names_from_train_script() -> list[str]:
    train_path = PROJECT_ROOT / "scripts" / "train_layer3.py"
    source = train_path.read_text(encoding="utf-8")
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "FEATURE_NAMES":
            if node.value is not None:
                value = ast.literal_eval(node.value)
                if isinstance(value, list) and all(isinstance(x, str) for x in value):
                    return value
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "FEATURE_NAMES":
                    value = ast.literal_eval(node.value)
                    if isinstance(value, list) and all(isinstance(x, str) for x in value):
                        return value
    raise RuntimeError(f"Could not parse FEATURE_NAMES from {train_path}")


FEATURE_NAMES = _load_feature_names_from_train_script()


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

    base = {
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
    return {name: float(base.get(name, 0.0)) for name in FEATURE_NAMES}


REGISTRY_CANDIDATES = (
    "registry.json",
    "model_registry.json",
    "layer3_registry.json",
    "models_registry.json",
)

ANOMALY_THRESHOLD = 50.0


@dataclass
class ModelMeta:
    model_key: str
    model_path: Path
    n_samples: int | None = None
    n_features: int | None = None
    is_low_data: bool | None = None
    contamination: float | None = None
    sector: str | None = None
    government_level: str | None = None
    year: int | None = None
    registry_entry: dict[str, Any] = field(default_factory=dict)


@dataclass
class LoadedModel:
    meta: ModelMeta
    model: Any
    artifact: dict[str, Any] | None
    feature_order: list[str]
    medians: list[float] | None
    scales: list[float] | None
    decision_min: float | None
    decision_max: float | None


@dataclass
class ScoredRow:
    declaration_id: str
    name: str
    sector: str
    government_level: str
    cohort_key_used: str
    score: float
    row: dict[str, str]


def _warn(msg: str, warnings: list[str]) -> None:
    print(f"[WARN] {msg}")
    warnings.append(msg)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        parsed = float(value)
        if not math.isfinite(parsed):
            return default
        return parsed
    except Exception:
        return default


def _to_int(value: Any) -> int | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(str(value))
    except Exception:
        return None


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.array(values, dtype=float), q))


def _find_registry(model_dir: Path) -> Path | None:
    for filename in REGISTRY_CANDIDATES:
        candidate = model_dir / filename
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _iter_model_entries(registry_data: Any) -> list[dict[str, Any]]:
    if isinstance(registry_data, list):
        return [x for x in registry_data if isinstance(x, dict)]

    if isinstance(registry_data, dict):
        if isinstance(registry_data.get("models"), list):
            return [x for x in registry_data["models"] if isinstance(x, dict)]

        if isinstance(registry_data.get("cohorts"), dict):
            entries: list[dict[str, Any]] = []
            for key, value in registry_data["cohorts"].items():
                if isinstance(value, dict):
                    row = dict(value)
                    row.setdefault("model_key", str(key))
                    entries.append(row)
            return entries

        entries = []
        for key, value in registry_data.items():
            if isinstance(value, dict) and (
                "path" in value or "model_path" in value or "file" in value
            ):
                row = dict(value)
                row.setdefault("model_key", str(key))
                entries.append(row)
        if entries:
            return entries

    return []


def _infer_cohort_fields(model_key: str, entry: dict[str, Any]) -> tuple[str | None, str | None, int | None]:
    sector = entry.get("sector")
    gov = entry.get("government_level")
    year = _to_int(entry.get("year"))

    if sector and gov:
        return str(sector), str(gov), year

    key = str(model_key or "")
    tokens = [t for t in key.split("_") if t]
    inferred_year = year
    inferred_sector: str | None = None
    inferred_gov: str | None = None

    if tokens and tokens[0].isdigit() and len(tokens) >= 3:
        inferred_year = int(tokens[0])
        inferred_sector = tokens[1]
        inferred_gov = tokens[2]
    elif len(tokens) >= 2:
        inferred_sector = tokens[0]
        inferred_gov = tokens[1]

    return (str(sector) if sector else inferred_sector, str(gov) if gov else inferred_gov, inferred_year)


def _build_meta_from_entry(model_dir: Path, entry: dict[str, Any]) -> ModelMeta | None:
    key = (
        entry.get("model_key")
        or entry.get("cohort_key")
        or entry.get("key")
        or entry.get("name")
        or "global"
    )
    raw_path = entry.get("model_path") or entry.get("path") or entry.get("file")

    if not raw_path:
        return None

    model_path = Path(str(raw_path))
    if not model_path.is_absolute():
        model_path = model_dir / model_path

    sector, gov, year = _infer_cohort_fields(str(key), entry)

    n_samples = (
        _to_int(entry.get("n_samples"))
        or _to_int(entry.get("sample_count"))
        or _to_int((entry.get("training") or {}).get("sample_count") if isinstance(entry.get("training"), dict) else None)
    )

    n_features = _to_int(entry.get("n_features"))

    is_low_data_raw = entry.get("is_low_data")
    if is_low_data_raw is None:
        is_low_data_raw = entry.get("low_data")
    is_low_data = None
    if is_low_data_raw is not None:
        is_low_data = bool(is_low_data_raw)

    contamination = entry.get("contamination")
    if contamination is None and isinstance(entry.get("training"), dict):
        contamination = entry["training"].get("contamination")
    contamination_f = _to_float(contamination, default=float("nan"))
    if not math.isfinite(contamination_f):
        contamination_f = None

    return ModelMeta(
        model_key=str(key),
        model_path=model_path,
        n_samples=n_samples,
        n_features=n_features,
        is_low_data=is_low_data,
        contamination=contamination_f,
        sector=sector,
        government_level=gov,
        year=year,
        registry_entry=dict(entry),
    )


def _load_registry_models(model_dir: Path, warnings: list[str]) -> list[ModelMeta]:
    registry_path = _find_registry(model_dir)
    if not registry_path:
        _warn(
            f"No registry JSON found in {model_dir}. Falling back to scanning .pkl files.",
            warnings,
        )
        return []

    try:
        with registry_path.open("r", encoding="utf-8") as fh:
            registry_data = json.load(fh)
    except Exception as exc:
        _warn(f"Failed to load registry at {registry_path}: {exc}", warnings)
        return []

    entries = _iter_model_entries(registry_data)
    if not entries:
        _warn(
            f"Registry {registry_path.name} did not contain recognizable model entries.",
            warnings,
        )
        return []

    metas: list[ModelMeta] = []
    for entry in entries:
        meta = _build_meta_from_entry(model_dir, entry)
        if meta is not None:
            metas.append(meta)

    if not metas:
        _warn(
            f"Registry {registry_path.name} had entries, but none had valid model paths.",
            warnings,
        )
    return metas


def _scan_pkl_models(model_dir: Path, warnings: list[str]) -> list[ModelMeta]:
    pkls = sorted(model_dir.rglob("*.pkl"))
    if not pkls:
        _warn(f"No .pkl models found under {model_dir}", warnings)
        return []

    metas: list[ModelMeta] = []
    for pkl_path in pkls:
        key = "global" if "global" in pkl_path.stem.lower() else pkl_path.stem
        metas.append(ModelMeta(model_key=key, model_path=pkl_path))
    return metas


def _load_single_model(meta: ModelMeta, warnings: list[str]) -> LoadedModel | None:
    if not meta.model_path.exists():
        _warn(f"Model file not found for {meta.model_key}: {meta.model_path}", warnings)
        return None

    try:
        with meta.model_path.open("rb") as fh:
            artifact = pickle.load(fh)
    except Exception as exc:
        _warn(f"Failed to unpickle model {meta.model_key} ({meta.model_path}): {exc}", warnings)
        return None

    artifact_dict: dict[str, Any] | None
    if isinstance(artifact, dict):
        artifact_dict = artifact
        model = artifact.get("model")
    else:
        artifact_dict = None
        model = artifact

    if model is None or not hasattr(model, "decision_function"):
        _warn(
            f"Model {meta.model_key} does not expose decision_function and cannot be evaluated.",
            warnings,
        )
        return None

    if artifact_dict:
        feature_order = list(artifact_dict.get("feature_order") or [])
        medians = artifact_dict.get("robust_medians")
        scales = artifact_dict.get("robust_scales")
        decision_min = artifact_dict.get("decision_min")
        decision_max = artifact_dict.get("decision_max")

        if meta.n_samples is None and isinstance(artifact_dict.get("training"), dict):
            meta.n_samples = _to_int(artifact_dict["training"].get("sample_count"))
        if meta.contamination is None and isinstance(artifact_dict.get("training"), dict):
            c = _to_float(artifact_dict["training"].get("contamination"), default=float("nan"))
            if math.isfinite(c):
                meta.contamination = c
    else:
        feature_order = []
        medians = None
        scales = None
        decision_min = None
        decision_max = None

    if not feature_order:
        # Fallback to current build_feature_vector key order to keep runtime deterministic.
        sample_map = build_feature_vector(
            total_income=0,
            total_assets=0,
            cash_holdings=0,
            bank_deposits=0,
            total_value_fields=0,
            unknown_value_fields=0,
            ownership_declarant=0,
            ownership_family=0,
            ownership_total=0,
            declaration_year=0,
            incomes_count=0,
            real_estate_count=0,
            vehicles_count=0,
            monetary_count=0,
            confidential_ratio=0.0,
        )
        feature_order = sorted(sample_map.keys())

    if meta.n_features is None:
        if feature_order:
            meta.n_features = len(feature_order)
        elif hasattr(model, "n_features_in_"):
            meta.n_features = int(getattr(model, "n_features_in_"))

    if meta.contamination is None and hasattr(model, "contamination"):
        c = _to_float(getattr(model, "contamination"), default=float("nan"))
        if math.isfinite(c):
            meta.contamination = c

    return LoadedModel(
        meta=meta,
        model=model,
        artifact=artifact_dict,
        feature_order=feature_order,
        medians=list(medians) if isinstance(medians, list) else None,
        scales=list(scales) if isinstance(scales, list) else None,
        decision_min=_to_float(decision_min, default=float("nan")) if decision_min is not None else None,
        decision_max=_to_float(decision_max, default=float("nan")) if decision_max is not None else None,
    )


def load_models(model_dir: Path, warnings: list[str]) -> list[LoadedModel]:
    if not model_dir.exists() or not model_dir.is_dir():
        _warn(f"Model directory does not exist: {model_dir}", warnings)
        return []

    metas = _load_registry_models(model_dir, warnings)
    if not metas:
        metas = _scan_pkl_models(model_dir, warnings)

    loaded: list[LoadedModel] = []
    for meta in metas:
        model = _load_single_model(meta, warnings)
        if model is not None:
            loaded.append(model)

    if not loaded:
        _warn(f"No loadable models found in {model_dir}", warnings)
        return []

    # Stable ordering: global first, then cohort keys.
    loaded.sort(key=lambda m: (0 if m.meta.model_key == "global" else 1, m.meta.model_key))
    return loaded


def _build_feature_map_from_csv_row(row: dict[str, str], model: LoadedModel) -> dict[str, float]:
    total_income = _to_float(row.get("total_income"))
    total_assets = _to_float(row.get("total_assets"))

    # Reconstruct what we can from score CSV. Missing fields are approximated with safe defaults.
    fm = build_feature_vector(
        total_income=total_income,
        total_assets=total_assets,
        cash_holdings=_to_float(row.get("cash_holdings")),
        bank_deposits=_to_float(row.get("bank_deposits")),
        total_value_fields=int(_to_float(row.get("total_value_fields"))),
        unknown_value_fields=int(_to_float(row.get("unknown_value_fields"))),
        ownership_declarant=int(_to_float(row.get("ownership_declarant"))),
        ownership_family=int(_to_float(row.get("ownership_family"))),
        ownership_total=int(_to_float(row.get("ownership_total"))),
        declaration_year=_to_int(row.get("declaration_year")) or model.meta.year,
        incomes_count=int(_to_float(row.get("incomes_count"))),
        real_estate_count=int(_to_float(row.get("real_estate_count"))),
        vehicles_count=int(_to_float(row.get("vehicles_count"))),
        monetary_count=int(_to_float(row.get("monetary_count"))),
        confidential_ratio=_to_float(row.get("confidential_ratio")),
    )

    # If CSV has direct per-feature columns, prefer those over derived defaults.
    for feat in model.feature_order:
        if feat in row and str(row.get(feat, "")).strip() != "":
            fm[feat] = _to_float(row.get(feat))
    return fm


def _vectorize(feature_map: dict[str, float], feature_order: list[str]) -> list[float]:
    return [float(feature_map.get(name, 0.0)) for name in feature_order]


def _apply_robust_scaling(vector: list[float], medians: list[float] | None, scales: list[float] | None) -> list[float]:
    if not medians or not scales or len(medians) != len(vector) or len(scales) != len(vector):
        return vector

    transformed: list[float] = []
    for idx in range(len(vector)):
        scale = scales[idx]
        if scale in (None, 0):
            scale = 1.0
        transformed.append((vector[idx] - float(medians[idx])) / float(scale))
    return transformed


def _decision_to_anomaly_100(model: LoadedModel, decisions: np.ndarray) -> np.ndarray:
    if (
        model.decision_min is not None
        and model.decision_max is not None
        and math.isfinite(model.decision_min)
        and math.isfinite(model.decision_max)
        and model.decision_max > model.decision_min
    ):
        norm = (decisions - model.decision_min) / (model.decision_max - model.decision_min)
        norm = np.clip(norm, 0.0, 1.0)
        anomaly = 1.0 - norm
    else:
        anomaly = 1.0 - (1.0 / (1.0 + np.exp(-decisions * 4.0)))
    return np.clip(anomaly * 100.0, 0.0, 100.0)


def predict_scores_for_rows(model: LoadedModel, rows: list[dict[str, str]]) -> list[ScoredRow]:
    if not rows:
        return []

    feature_vectors: list[list[float]] = []
    for row in rows:
        fm = _build_feature_map_from_csv_row(row, model)
        vec = _vectorize(fm, model.feature_order)
        feature_vectors.append(_apply_robust_scaling(vec, model.medians, model.scales))

    decisions = np.array(model.model.decision_function(feature_vectors), dtype=float)
    scores = _decision_to_anomaly_100(model, decisions)

    result: list[ScoredRow] = []
    for row, score in zip(rows, scores):
        result.append(
            ScoredRow(
                declaration_id=str(row.get("declaration_id") or ""),
                name=str(row.get("name") or "Unknown"),
                sector=str(row.get("sector") or "other"),
                government_level=str(row.get("government_level") or "other"),
                cohort_key_used=str(row.get("cohort_key_used") or ""),
                score=float(score),
                row=row,
            )
        )
    return result


def _cohort_match(model: LoadedModel, row: dict[str, str]) -> bool:
    if model.meta.model_key == "global":
        return True

    row_sector = _normalize_text(row.get("sector"))
    row_gov = _normalize_text(row.get("government_level"))

    # Best match: explicit registry metadata.
    if model.meta.sector and model.meta.government_level:
        return (
            row_sector == _normalize_text(model.meta.sector)
            and row_gov == _normalize_text(model.meta.government_level)
        )

    # Fallback: exact cohort_key_used match.
    cohort_key_used = _normalize_text(row.get("cohort_key_used"))
    if cohort_key_used and cohort_key_used == _normalize_text(model.meta.model_key):
        return True

    return False


def select_rows_for_model(model: LoadedModel, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    if model.meta.model_key == "global":
        return rows
    return [r for r in rows if _cohort_match(model, r)]


def read_scores_csv(path: Path, warnings: list[str]) -> list[dict[str, str]]:
    if not path.exists() or not path.is_file():
        _warn(f"Scores CSV not found: {path}", warnings)
        return []

    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = [dict(row) for row in reader]

    if not rows:
        _warn(f"Scores CSV is empty: {path}", warnings)
    return rows


def _format_percentiles(values: list[float]) -> dict[str, float]:
    return {
        "p10": round(_percentile(values, 10), 3),
        "p25": round(_percentile(values, 25), 3),
        "p50": round(_percentile(values, 50), 3),
        "p75": round(_percentile(values, 75), 3),
        "p90": round(_percentile(values, 90), 3),
        "p99": round(_percentile(values, 99), 3),
    }


def _training_matrix_for_permutation(
    model: LoadedModel,
    scored_rows: list[ScoredRow],
) -> np.ndarray:
    # Best effort: use embedded training matrix if present in artifact.
    if model.artifact:
        for key in ("training_matrix", "X_train", "matrix"):
            value = model.artifact.get(key)
            if isinstance(value, list) and value and isinstance(value[0], (list, tuple)):
                arr = np.array(value, dtype=float)
                if arr.ndim == 2 and arr.shape[1] == len(model.feature_order):
                    return arr

    if not scored_rows:
        return np.zeros((0, len(model.feature_order)), dtype=float)

    rows = []
    for row in scored_rows:
        fm = _build_feature_map_from_csv_row(row.row, model)
        vec = _vectorize(fm, model.feature_order)
        vec = _apply_robust_scaling(vec, model.medians, model.scales)
        rows.append(vec)
    return np.array(rows, dtype=float)


def permutation_importance(model: LoadedModel, scored_rows: list[ScoredRow]) -> dict[str, Any]:
    x = _training_matrix_for_permutation(model, scored_rows)
    if x.shape[0] == 0:
        return {
            "rows_used": 0,
            "importance": [],
            "zero_importance_features": [],
        }

    base_decisions = np.array(model.model.decision_function(x), dtype=float)
    base_scores = _decision_to_anomaly_100(model, base_decisions)

    rng = random.Random(42)
    rows_count, cols_count = x.shape
    feature_rows: list[dict[str, Any]] = []
    zero_features: list[str] = []

    for col_idx in range(cols_count):
        shuffled = x.copy()
        col_values = list(shuffled[:, col_idx])
        rng.shuffle(col_values)
        shuffled[:, col_idx] = np.array(col_values, dtype=float)

        pert_decisions = np.array(model.model.decision_function(shuffled), dtype=float)
        pert_scores = _decision_to_anomaly_100(model, pert_decisions)
        delta = pert_scores - base_scores

        mean_abs_delta = float(np.mean(np.abs(delta)))
        mean_delta = float(np.mean(delta))
        direction = "mixed"
        if mean_delta > 1e-9:
            direction = "increase"
        elif mean_delta < -1e-9:
            direction = "decrease"

        feature_name = model.feature_order[col_idx]
        feature_rows.append(
            {
                "feature_name": feature_name,
                "mean_score_delta": round(mean_abs_delta, 6),
                "direction": direction,
                "signed_mean_delta": round(mean_delta, 6),
            }
        )

        if mean_abs_delta <= 1e-12:
            zero_features.append(feature_name)

    feature_rows.sort(key=lambda x: x["mean_score_delta"], reverse=True)
    for idx, row in enumerate(feature_rows, start=1):
        row["rank"] = idx

    return {
        "rows_used": int(rows_count),
        "importance": feature_rows,
        "zero_importance_features": zero_features,
    }


def evaluate_per_model(
    models: list[LoadedModel],
    score_rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    model_reports: list[dict[str, Any]] = []

    for model in models:
        selected_rows = select_rows_for_model(model, score_rows)
        if (
            not selected_rows
            and len(models) == 1
            and model.meta.model_key != "global"
            and not (model.meta.sector and model.meta.government_level)
        ):
            selected_rows = score_rows
        predicted_rows = predict_scores_for_rows(model, selected_rows) if selected_rows else []
        scores = [r.score for r in predicted_rows]
        anomalies = [s for s in scores if s >= ANOMALY_THRESHOLD]

        top = sorted(predicted_rows, key=lambda x: x.score, reverse=True)[:10]
        top_rows = [
            {
                "declaration_id": r.declaration_id,
                "name": r.name,
                "score": round(r.score, 3),
                "sector": r.sector,
                "government_level": r.government_level,
                "cohort_key_used": r.cohort_key_used,
            }
            for r in top
        ]

        imp = permutation_importance(model, predicted_rows)

        model_report = {
            "model_key": model.meta.model_key,
            "model_path": str(model.meta.model_path),
            "n_samples_trained": model.meta.n_samples,
            "n_features": model.meta.n_features,
            "is_low_data": model.meta.is_low_data,
            "contamination": model.meta.contamination,
            "cohort_filter": {
                "sector": model.meta.sector,
                "government_level": model.meta.government_level,
                "year": model.meta.year,
            },
            "scores_summary": {
                "rows_evaluated": len(predicted_rows),
                "anomaly_rate": round((len(anomalies) / len(scores) * 100.0), 3) if scores else None,
                "distribution": _format_percentiles(scores) if scores else None,
                "top10_most_anomalous": top_rows,
            },
            "feature_importance": imp,
        }
        model_reports.append(model_report)

    return model_reports


def _ascii_box_line(values: list[float], width: int = 28) -> str:
    if not values:
        return "(no data)"

    lo = _percentile(values, 10)
    q1 = _percentile(values, 25)
    med = _percentile(values, 50)
    q3 = _percentile(values, 75)
    hi = _percentile(values, 90)

    def pos(v: float) -> int:
        return int(round((v / 100.0) * (width - 1)))

    chars = [" "] * width
    for i in range(pos(lo), pos(hi) + 1):
        if 0 <= i < width:
            chars[i] = "-"
    for i in range(pos(q1), pos(q3) + 1):
        if 0 <= i < width:
            chars[i] = "="
    m = pos(med)
    if 0 <= m < width:
        chars[m] = "|"
    return "".join(chars)


def score_distribution_across_cohorts(
    models: list[LoadedModel],
    score_rows: list[dict[str, str]],
) -> dict[str, Any]:
    if not score_rows:
        return {
            "sector_distributions": {},
            "cohort_table": [],
            "high_mean_cohorts": [],
            "global_mean": None,
            "global_std": None,
        }

    # Assign each declaration to best matching model, else global.
    global_model = next((m for m in models if m.meta.model_key == "global"), None)
    if global_model is None and len(models) == 1:
        global_model = models[0]
    assigned_scores: list[dict[str, Any]] = []

    for row in score_rows:
        selected_model = None
        for model in models:
            if model.meta.model_key == "global":
                continue
            if _cohort_match(model, row):
                selected_model = model
                break
        if selected_model is None:
            selected_model = global_model
        if selected_model is None:
            continue

        scored = predict_scores_for_rows(selected_model, [row])
        if not scored:
            continue

        s = scored[0]
        cohort_key = s.cohort_key_used or selected_model.meta.model_key
        assigned_scores.append(
            {
                "declaration_id": s.declaration_id,
                "sector": s.sector,
                "government_level": s.government_level,
                "cohort_key": cohort_key,
                "score": s.score,
                "model_used": selected_model.meta.model_key,
            }
        )

    if not assigned_scores:
        return {
            "sector_distributions": {},
            "cohort_table": [],
            "high_mean_cohorts": [],
            "global_mean": None,
            "global_std": None,
        }

    all_scores = [x["score"] for x in assigned_scores]
    global_mean = float(np.mean(np.array(all_scores, dtype=float)))
    global_std = float(np.std(np.array(all_scores, dtype=float)))
    high_cut = global_mean + 2.0 * global_std

    by_sector: dict[str, list[float]] = {}
    by_cohort: dict[str, list[dict[str, Any]]] = {}

    for row in assigned_scores:
        by_sector.setdefault(row["sector"], []).append(row["score"])
        by_cohort.setdefault(row["cohort_key"], []).append(row)

    sector_distributions: dict[str, Any] = {}
    for sector, vals in sorted(by_sector.items()):
        sector_distributions[sector] = {
            "n": len(vals),
            "p10": round(_percentile(vals, 10), 3),
            "p25": round(_percentile(vals, 25), 3),
            "p50": round(_percentile(vals, 50), 3),
            "p75": round(_percentile(vals, 75), 3),
            "p90": round(_percentile(vals, 90), 3),
            "ascii_box": _ascii_box_line(vals),
        }

    cohort_table: list[dict[str, Any]] = []
    high_mean_cohorts: list[dict[str, Any]] = []

    for cohort_key, rows in sorted(by_cohort.items()):
        vals = [x["score"] for x in rows]
        mean_score = float(np.mean(np.array(vals, dtype=float)))
        anomaly_rate = float(sum(1 for v in vals if v >= ANOMALY_THRESHOLD) / len(vals) * 100.0)
        entry = {
            "cohort_key": cohort_key,
            "n_declarations": len(rows),
            "mean_score": round(mean_score, 3),
            "p90_score": round(_percentile(vals, 90), 3),
            "anomaly_rate": round(anomaly_rate, 3),
            "model_used": rows[0]["model_used"],
        }
        cohort_table.append(entry)

        if mean_score > high_cut:
            high_mean_cohorts.append(entry)

    return {
        "sector_distributions": sector_distributions,
        "cohort_table": cohort_table,
        "high_mean_cohorts": high_mean_cohorts,
        "global_mean": round(global_mean, 3),
        "global_std": round(global_std, 3),
        "high_cutoff": round(high_cut, 3),
    }


def _predict_all_rows_by_id(models: list[LoadedModel], rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    global_model = next((m for m in models if m.meta.model_key == "global"), None)
    if global_model is None and len(models) == 1:
        global_model = models[0]
    out: dict[str, dict[str, Any]] = {}

    for row in rows:
        model = None
        for candidate in models:
            if candidate.meta.model_key == "global":
                continue
            if _cohort_match(candidate, row):
                model = candidate
                break
        if model is None:
            model = global_model
        if model is None:
            continue

        scored = predict_scores_for_rows(model, [row])
        if not scored:
            continue
        s = scored[0]
        key = s.declaration_id or f"row_{len(out)}"
        out[key] = {
            "declaration_id": s.declaration_id,
            "name": s.name,
            "sector": s.sector,
            "government_level": s.government_level,
            "score": round(s.score, 6),
            "model_used": model.meta.model_key,
        }
    return out


def compare_model_dirs(
    old_models: list[LoadedModel],
    new_models: list[LoadedModel],
    rows: list[dict[str, str]],
) -> dict[str, Any]:
    old_pred = _predict_all_rows_by_id(old_models, rows)
    new_pred = _predict_all_rows_by_id(new_models, rows)

    common_ids = sorted(set(old_pred.keys()) & set(new_pred.keys()))
    if not common_ids:
        return {
            "n_compared": 0,
            "mean_score_delta": None,
            "threshold_cross_rate": None,
            "top_score_increase": [],
            "top_score_decrease": [],
            "cohort_summary": [],
        }

    deltas: list[dict[str, Any]] = []
    threshold_crosses = 0

    for decl_id in common_ids:
        old_row = old_pred[decl_id]
        new_row = new_pred[decl_id]
        delta = float(new_row["score"] - old_row["score"])

        old_flag = old_row["score"] >= ANOMALY_THRESHOLD
        new_flag = new_row["score"] >= ANOMALY_THRESHOLD
        if old_flag != new_flag:
            threshold_crosses += 1

        deltas.append(
            {
                "declaration_id": decl_id,
                "name": new_row["name"],
                "sector": new_row["sector"],
                "government_level": new_row["government_level"],
                "old_score": round(float(old_row["score"]), 6),
                "new_score": round(float(new_row["score"]), 6),
                "score_delta": round(delta, 6),
                "old_model": old_row["model_used"],
                "new_model": new_row["model_used"],
            }
        )

    mean_delta = float(np.mean(np.array([d["score_delta"] for d in deltas], dtype=float)))
    threshold_cross_rate = float(threshold_crosses / len(deltas) * 100.0)

    top_inc = sorted(deltas, key=lambda x: x["score_delta"], reverse=True)[:10]
    top_dec = sorted(deltas, key=lambda x: x["score_delta"])[:10]

    cohort_bucket: dict[str, list[dict[str, Any]]] = {}
    for row in deltas:
        cohort_key = f"{row['sector']}|{row['government_level']}"
        cohort_bucket.setdefault(cohort_key, []).append(row)

    cohort_summary: list[dict[str, Any]] = []
    for cohort_key, bucket in sorted(cohort_bucket.items()):
        old_flags = sum(1 for x in bucket if x["old_score"] >= ANOMALY_THRESHOLD)
        new_flags = sum(1 for x in bucket if x["new_score"] >= ANOMALY_THRESHOLD)
        old_rate = old_flags / len(bucket) * 100.0
        new_rate = new_flags / len(bucket) * 100.0
        cohort_summary.append(
            {
                "cohort": cohort_key,
                "old_anomaly_rate": round(old_rate, 3),
                "new_anomaly_rate": round(new_rate, 3),
                "delta": round(new_rate - old_rate, 3),
                "n": len(bucket),
            }
        )

    return {
        "n_compared": len(deltas),
        "mean_score_delta": round(mean_delta, 6),
        "threshold_cross_rate": round(threshold_cross_rate, 3),
        "top_score_increase": top_inc,
        "top_score_decrease": top_dec,
        "cohort_summary": cohort_summary,
    }


def _print_header(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def _fmt(v: Any) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def print_report(report: dict[str, Any]) -> None:
    _print_header("Project Argus Layer 3 Model Evaluation")

    print("Inputs:")
    print(f"  model_dir: {report['inputs']['model_dir']}")
    print(f"  scores_csv: {report['inputs']['scores_csv'] or 'n/a'}")
    print(f"  compare_model_dir: {report['inputs']['compare_model_dir'] or 'n/a'}")

    if report.get("warnings"):
        print("\nWarnings:")
        for w in report["warnings"]:
            print(f"  - {w}")

    _print_header("Section 1: Per-model diagnostics")
    per_model = report["per_model"]
    if not per_model:
        print("No models were loaded. Nothing to evaluate.")
    for item in per_model:
        print(f"\nModel: {item['model_key']}")
        print(f"  n_samples_trained: {_fmt(item['n_samples_trained'])}")
        print(f"  n_features: {_fmt(item['n_features'])}")
        print(f"  is_low_data: {_fmt(item['is_low_data'])}")
        print(f"  contamination: {_fmt(item['contamination'])}")

        scores_summary = item["scores_summary"]
        rows_eval = scores_summary["rows_evaluated"]
        print(f"  rows_evaluated: {rows_eval}")
        if rows_eval > 0:
            print(f"  anomaly_rate(%): {_fmt(scores_summary['anomaly_rate'])}")
            dist = scores_summary["distribution"]
            if dist:
                print(
                    "  distribution: "
                    f"p10={_fmt(dist['p10'])}, p25={_fmt(dist['p25'])}, p50={_fmt(dist['p50'])}, "
                    f"p75={_fmt(dist['p75'])}, p90={_fmt(dist['p90'])}, p99={_fmt(dist['p99'])}"
                )
            print("  top10_most_anomalous:")
            for row in scores_summary["top10_most_anomalous"]:
                print(
                    f"    {row['declaration_id']:<18} {row['name'][:28]:<28} "
                    f"score={row['score']:.3f} sector={row['sector']} gov={row['government_level']} "
                    f"cohort={row['cohort_key_used']}"
                )
        else:
            print("  No CSV-matched declarations for this model.")

    _print_header("Section 2: Feature importance approximation")
    for item in per_model:
        print(f"\nModel: {item['model_key']}")
        fi = item["feature_importance"]
        print(f"  rows_used_for_permutation: {fi['rows_used']}")
        if fi["rows_used"] == 0:
            print("  Skipped (no data available to reconstruct training matrix).")
            continue

        print("  Rank | Feature Name                  | Mean Score Delta | Direction")
        print("  -----+-------------------------------+------------------+----------")
        for row in fi["importance"]:
            print(
                f"  {row['rank']:>4} | {row['feature_name'][:29]:<29} | "
                f"{row['mean_score_delta']:>16.6f} | {row['direction']}"
            )
        if fi["zero_importance_features"]:
            print("  Zero-importance features (possible constant/all-null columns):")
            for name in fi["zero_importance_features"]:
                print(f"    - {name}")

    _print_header("Section 3: Score distribution across cohorts")
    section3 = report["cohort_distribution"]
    if not section3["cohort_table"]:
        print("No score CSV data available for cohort distribution analysis.")
    else:
        print(
            f"Global mean={_fmt(section3['global_mean'])}, "
            f"std={_fmt(section3['global_std'])}, "
            f"high-mean cutoff={_fmt(section3.get('high_cutoff'))}"
        )
        print("\nSector score distributions (ASCII box from P10..P90, IQR as '='):")
        for sector, data in section3["sector_distributions"].items():
            print(
                f"  {sector:<20} n={data['n']:<4} "
                f"{data['ascii_box']} "
                f"p50={data['p50']:.2f}"
            )

        if section3["high_mean_cohorts"]:
            print("\nFlagged cohorts (mean > global mean + 2 std):")
            for row in section3["high_mean_cohorts"]:
                print(
                    f"  {row['cohort_key']} n={row['n_declarations']} "
                    f"mean={row['mean_score']:.3f} model={row['model_used']}"
                )

        print("\nCohort table:")
        print("  Cohort Key                         | n   | mean   | p90    | anomaly_rate | model_used")
        print("  -----------------------------------+-----+--------+--------+--------------+-----------")
        for row in section3["cohort_table"]:
            print(
                f"  {row['cohort_key'][:35]:<35} | {row['n_declarations']:>3} | "
                f"{row['mean_score']:>6.3f} | {row['p90_score']:>6.3f} | "
                f"{row['anomaly_rate']:>12.3f} | {row['model_used']}"
            )

    _print_header("Section 4: A/B model comparison")
    ab = report.get("ab_comparison")
    if not ab:
        print("A/B comparison not requested.")
    elif ab["n_compared"] == 0:
        print("A/B comparison requested, but no overlapping declaration predictions were found.")
    else:
        print(f"Compared declarations: {ab['n_compared']}")
        print(f"Mean score delta (new - old): {ab['mean_score_delta']:.6f}")
        print(f"Threshold cross rate (50.0): {ab['threshold_cross_rate']:.3f}%")

        print("\nTop 10 largest score increase:")
        for row in ab["top_score_increase"]:
            print(
                f"  {row['declaration_id']:<18} delta={row['score_delta']:+8.3f} "
                f"old={row['old_score']:7.3f} new={row['new_score']:7.3f} {row['name'][:30]}"
            )

        print("\nTop 10 largest score decrease:")
        for row in ab["top_score_decrease"]:
            print(
                f"  {row['declaration_id']:<18} delta={row['score_delta']:+8.3f} "
                f"old={row['old_score']:7.3f} new={row['new_score']:7.3f} {row['name'][:30]}"
            )

        print("\nCohort summary:")
        print("  Cohort                             | Old anomaly rate | New anomaly rate | Delta")
        print("  -----------------------------------+------------------+------------------+-------")
        for row in ab["cohort_summary"]:
            print(
                f"  {row['cohort'][:35]:<35} | {row['old_anomaly_rate']:>16.3f} | "
                f"{row['new_anomaly_rate']:>16.3f} | {row['delta']:>+6.3f}"
            )


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    warnings: list[str] = []

    model_dir = Path(args.model_dir)
    models = load_models(model_dir, warnings)

    score_rows: list[dict[str, str]] = []
    if args.scores_csv:
        score_rows = read_scores_csv(Path(args.scores_csv), warnings)
    else:
        _warn("--scores-csv not provided; only model metadata will be evaluated.", warnings)

    per_model = evaluate_per_model(models, score_rows)
    section3 = score_distribution_across_cohorts(models, score_rows)

    ab_report = None
    if args.compare_model_dir:
        old_models = load_models(Path(args.compare_model_dir), warnings)
        if score_rows and models and old_models:
            ab_report = compare_model_dirs(old_models, models, score_rows)
        else:
            _warn(
                "Skipping A/B comparison because compare models, primary models, or scores CSV are missing.",
                warnings,
            )

    feature_names = sorted(
        FEATURE_NAMES
    )

    return {
        "inputs": {
            "model_dir": str(model_dir),
            "scores_csv": str(args.scores_csv) if args.scores_csv else None,
            "output": str(args.output) if args.output else None,
            "compare_model_dir": str(args.compare_model_dir) if args.compare_model_dir else None,
        },
        "warnings": warnings,
        "feature_names": feature_names,
        "per_model": per_model,
        "cohort_distribution": section3,
        "ab_comparison": ab_report,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Layer 3 models and diagnostics")
    parser.add_argument(
        "--model-dir",
        type=str,
        default="output/models",
        help="Directory containing .pkl models and optional registry JSON.",
    )
    parser.add_argument(
        "--scores-csv",
        type=str,
        default="",
        help="CSV produced by scripts/run_scoring.py --csv",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="Optional path to write machine-readable JSON report.",
    )
    parser.add_argument(
        "--compare-model-dir",
        type=str,
        default="",
        help="Optional second model directory for A/B comparison (treated as old models).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_report(args)
    print_report(report)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print(f"\nJSON report written to: {output_path}")


if __name__ == "__main__":
    main()
