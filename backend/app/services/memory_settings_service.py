"""Admin-configured automatic memory knobs stored in system_settings."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.models.system import SystemSetting
from app.services.model_capabilities import model_kinds, model_media_flags
from app.services.model_tool_compatibility_service import is_auto_router_model_id

MEMORY_CATEGORIES = (
    "identity",
    "preference",
    "health",
    "work",
    "family",
    "goal",
    "constraint",
    "schedule",
    "financial",
    "other",
)
CORE_CATEGORIES = frozenset({"identity", "constraint", "health"})
SENSITIVITY_VALUES = ("normal", "sensitive")
DEFAULT_SENSITIVE_CATEGORIES = ("health", "financial")

# Project memory is shared with every member, so it uses its own work-oriented
# taxonomy instead of the personal one above.
PROJECT_MEMORY_CATEGORIES = (
    "decision",
    "convention",
    "requirement",
    "stack",
    "schedule",
    "responsibility",
    "stakeholder",
    "constraint",
    "preference",
    "other",
)
# Never stored in project scope, whatever the admin allow-list says. A member
# would not expect teammates to read these back out of a shared prompt.
PROJECT_DENIED_CATEGORIES = frozenset({"health", "financial", "personal", "family", "identity"})

SETTING_KEYS = {
    "memory_feature_enabled": "true",
    "memory_extraction_model_id": "",
    "memory_embedding_model": "",
    "memory_embedding_dimensions": "",
    "memory_extract_debounce_seconds": "30",
    "memory_extract_max_wait_seconds": "600",
    "memory_extract_min_new_messages": "2",
    "memory_max_per_user": "200",
    "memory_inject_max_items": "12",
    "memory_inject_max_chars": "2500",
    "memory_core_items": "6",
    "memory_semantic_top_k": "8",
    "memory_lexical_top_k": "6",
    "memory_min_similarity": "0.25",
    "memory_retrieval_timeout_ms": "600",
    "memory_allowed_sensitive_categories": json.dumps(list(DEFAULT_SENSITIVE_CATEGORIES)),
    "memory_stale_archive_days": "540",
    "memory_soft_delete_purge_days": "30",
    "memory_suppression_days": "180",
    "memory_qdrant_collection_version": "1",
    "project_memory_feature_enabled": "true",
    "project_memory_max_per_project": "500",
    "project_memory_inject_max_items": "60",
    "project_memory_inject_max_chars": "8000",
    "project_memory_manual_items": "30",
    "project_memory_extract_debounce_seconds": "45",
    "project_memory_extract_max_wait_seconds": "900",
    "project_memory_extract_min_new_messages": "2",
    "project_memory_semantic_top_k": "12",
    "project_memory_lexical_top_k": "8",
    "project_memory_min_similarity": "0.25",
}


class MemorySettingsError(ValueError):
    """Invalid memory configuration."""


def _as_bool(value: str | None, default: bool) -> bool:
    token = (value or "").strip().lower()
    if token in ("1", "true", "yes", "on"):
        return True
    if token in ("0", "false", "no", "off"):
        return False
    return default


def _as_int(value: str | None, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(value).strip()) if value is not None and str(value).strip() else default
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _as_float(value: str | None, default: float, *, minimum: float, maximum: float) -> float:
    try:
        parsed = float(str(value).strip()) if value is not None and str(value).strip() else default
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _as_string_list(value: str | None, default: list[str]) -> list[str]:
    raw = (value or "").strip()
    if not raw:
        return list(default)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = [part.strip() for part in raw.split(",")]
    if not isinstance(parsed, list):
        return list(default)
    out: list[str] = []
    allowed = set(MEMORY_CATEGORIES) | {"financial"}
    for item in parsed:
        token = str(item or "").strip().lower()
        if token in allowed and token not in out:
            out.append(token)
    return out


def model_supports_text_chat(model: AIModel) -> bool:
    if is_auto_router_model_id(model.external_id):
        return True
    media = model_media_flags(
        external_id=model.external_id or "",
        is_image_model=bool(model.is_image_model),
        is_video_model=bool(getattr(model, "is_video_model", False)),
        pricing_raw=model.pricing_raw,
        provider_type=model.provider_type,
    )
    kinds = model_kinds(
        external_id=model.external_id or "",
        is_image_model=media["is_image_model"],
        is_video_model=media["is_video_model"],
        pricing_raw=model.pricing_raw,
        provider_type=model.provider_type,
    )
    if not kinds:
        return True
    return "text" in kinds


def model_supports_embeddings(model: AIModel) -> bool:
    kinds = model_kinds(
        external_id=model.external_id or "",
        is_image_model=bool(model.is_image_model),
        is_video_model=bool(getattr(model, "is_video_model", False)),
        pricing_raw=model.pricing_raw,
        provider_type=model.provider_type,
    )
    return "embeddings" in kinds


async def _load_raw(db: AsyncSession) -> dict[str, str]:
    rows = {}
    for key, default in SETTING_KEYS.items():
        row = await db.get(SystemSetting, key)
        rows[key] = row.value if row is not None and row.value is not None else default
    return rows


def parse_memory_settings(raw: dict[str, str]) -> dict[str, Any]:
    embedding_model = (raw.get("memory_embedding_model") or "").strip()
    extraction_raw = (raw.get("memory_extraction_model_id") or "").strip()
    extraction_id: int | None
    try:
        extraction_id = int(extraction_raw) if extraction_raw else None
    except (TypeError, ValueError):
        extraction_id = None
    if extraction_id is not None and extraction_id <= 0:
        extraction_id = None
    dims_raw = (raw.get("memory_embedding_dimensions") or "").strip()
    embedding_dimensions = _as_int(dims_raw, 0, minimum=0, maximum=65_536) if dims_raw else 0
    return {
        "feature_enabled": _as_bool(raw.get("memory_feature_enabled"), True),
        "extraction_model_id": extraction_id,
        "embedding_model": embedding_model,
        "embedding_dimensions": embedding_dimensions or None,
        "extract_debounce_seconds": _as_int(raw.get("memory_extract_debounce_seconds"), 30, minimum=5, maximum=3600),
        "extract_max_wait_seconds": _as_int(raw.get("memory_extract_max_wait_seconds"), 600, minimum=30, maximum=7200),
        "extract_min_new_messages": _as_int(raw.get("memory_extract_min_new_messages"), 2, minimum=1, maximum=20),
        "max_per_user": _as_int(raw.get("memory_max_per_user"), 200, minimum=10, maximum=500),
        "inject_max_items": _as_int(raw.get("memory_inject_max_items"), 12, minimum=1, maximum=50),
        "inject_max_chars": _as_int(raw.get("memory_inject_max_chars"), 2500, minimum=200, maximum=8000),
        "core_items": _as_int(raw.get("memory_core_items"), 6, minimum=0, maximum=20),
        "semantic_top_k": _as_int(raw.get("memory_semantic_top_k"), 8, minimum=0, maximum=40),
        "lexical_top_k": _as_int(raw.get("memory_lexical_top_k"), 6, minimum=0, maximum=40),
        "min_similarity": _as_float(raw.get("memory_min_similarity"), 0.25, minimum=0.0, maximum=1.0),
        "retrieval_timeout_ms": _as_int(raw.get("memory_retrieval_timeout_ms"), 600, minimum=50, maximum=5000),
        "allowed_sensitive_categories": _as_string_list(
            raw.get("memory_allowed_sensitive_categories"),
            list(DEFAULT_SENSITIVE_CATEGORIES),
        ),
        "stale_archive_days": _as_int(raw.get("memory_stale_archive_days"), 540, minimum=0, maximum=3650),
        "soft_delete_purge_days": _as_int(raw.get("memory_soft_delete_purge_days"), 30, minimum=1, maximum=365),
        "suppression_days": _as_int(raw.get("memory_suppression_days"), 180, minimum=1, maximum=3650),
        "qdrant_collection_version": _as_int(raw.get("memory_qdrant_collection_version"), 1, minimum=1, maximum=10_000),
        "project_feature_enabled": _as_bool(raw.get("project_memory_feature_enabled"), True),
        "project_max_per_project": _as_int(raw.get("project_memory_max_per_project"), 500, minimum=10, maximum=2000),
        "project_inject_max_items": _as_int(raw.get("project_memory_inject_max_items"), 60, minimum=1, maximum=200),
        "project_inject_max_chars": _as_int(
            raw.get("project_memory_inject_max_chars"), 8000, minimum=200, maximum=24_000
        ),
        "project_manual_items": _as_int(raw.get("project_memory_manual_items"), 30, minimum=0, maximum=200),
        "project_extract_debounce_seconds": _as_int(
            raw.get("project_memory_extract_debounce_seconds"),
            45,
            minimum=5,
            maximum=3600,
        ),
        "project_extract_max_wait_seconds": _as_int(
            raw.get("project_memory_extract_max_wait_seconds"),
            900,
            minimum=30,
            maximum=7200,
        ),
        "project_extract_min_new_messages": _as_int(
            raw.get("project_memory_extract_min_new_messages"), 2, minimum=1, maximum=20
        ),
        "project_semantic_top_k": _as_int(raw.get("project_memory_semantic_top_k"), 12, minimum=0, maximum=60),
        "project_lexical_top_k": _as_int(raw.get("project_memory_lexical_top_k"), 8, minimum=0, maximum=60),
        "project_min_similarity": _as_float(raw.get("project_memory_min_similarity"), 0.25, minimum=0.0, maximum=1.0),
    }


async def get_memory_settings(db: AsyncSession) -> dict[str, Any]:
    return parse_memory_settings(await _load_raw(db))


async def _upsert_setting(db: AsyncSession, key: str, value: str | None) -> None:
    row = await db.get(SystemSetting, key)
    if row is None:
        db.add(SystemSetting(key=key, value=value))
    else:
        row.value = value
    await db.flush()


async def _assert_extraction_model(db: AsyncSession, model_id: int) -> AIModel:
    model = await db.get(AIModel, int(model_id))
    if model is None:
        raise MemorySettingsError("Extraction model not found")
    if not bool(model.is_enabled) or bool(model.admin_disabled):
        raise MemorySettingsError("Extraction model must be enabled")
    if not model_supports_text_chat(model):
        raise MemorySettingsError("Extraction model must support text chat")
    if model.connection_id is not None:
        conn = await db.get(Connection, model.connection_id)
        if conn is None or not bool(conn.is_active):
            raise MemorySettingsError("Extraction model connection must be active")
    return model


async def _assert_embedding_model(db: AsyncSession, spec: str, dimensions: int | None) -> tuple[str, str, int | None]:
    raw = (spec or "").strip()
    if ":" in raw:
        provider, model = raw.split(":", 1)
    else:
        raise MemorySettingsError("Embedding model must be 'provider:external_id'")
    provider = provider.strip().lower()
    model = model.strip()
    if not provider or not model:
        raise MemorySettingsError("Embedding model must be 'provider:external_id'")
    from app.services.knowledge_embedding_service import (
        resolve_embedding_model,
        suggested_embedding_dimensions,
    )

    try:
        resolved = await resolve_embedding_model(db, provider=provider, model=model)
    except ValueError as exc:
        raise MemorySettingsError(str(exc)) from exc
    if not model_supports_embeddings(resolved.catalog_model):
        raise MemorySettingsError("Embedding model must support embeddings")
    suggested = suggested_embedding_dimensions(resolved.catalog_model.external_id or model)
    if dimensions is None or int(dimensions) < 1:
        dimensions = suggested
    elif int(dimensions) > 65_536:
        raise MemorySettingsError("Embedding dimensions are out of range")
    return provider, resolved.catalog_model.external_id, int(dimensions)


def _raw_from_values(values: dict[str, Any]) -> dict[str, str]:
    """Serialize parsed settings back to their system_settings string form."""
    return {
        "memory_feature_enabled": "true" if values["feature_enabled"] else "false",
        "memory_extraction_model_id": (
            "" if not values.get("extraction_model_id") else str(values["extraction_model_id"])
        ),
        "memory_embedding_model": str(values.get("embedding_model") or ""),
        "memory_embedding_dimensions": (
            "" if not values.get("embedding_dimensions") else str(int(values["embedding_dimensions"]))
        ),
        "memory_extract_debounce_seconds": str(values["extract_debounce_seconds"]),
        "memory_extract_max_wait_seconds": str(values["extract_max_wait_seconds"]),
        "memory_extract_min_new_messages": str(values["extract_min_new_messages"]),
        "memory_max_per_user": str(values["max_per_user"]),
        "memory_inject_max_items": str(values["inject_max_items"]),
        "memory_inject_max_chars": str(values["inject_max_chars"]),
        "memory_core_items": str(values["core_items"]),
        "memory_semantic_top_k": str(values["semantic_top_k"]),
        "memory_lexical_top_k": str(values["lexical_top_k"]),
        "memory_min_similarity": str(values["min_similarity"]),
        "memory_retrieval_timeout_ms": str(values["retrieval_timeout_ms"]),
        "memory_allowed_sensitive_categories": json.dumps(values["allowed_sensitive_categories"]),
        "memory_stale_archive_days": str(values["stale_archive_days"]),
        "memory_soft_delete_purge_days": str(values["soft_delete_purge_days"]),
        "memory_suppression_days": str(values["suppression_days"]),
        "memory_qdrant_collection_version": str(values["qdrant_collection_version"]),
        "project_memory_feature_enabled": ("true" if values["project_feature_enabled"] else "false"),
        "project_memory_max_per_project": str(values["project_max_per_project"]),
        "project_memory_inject_max_items": str(values["project_inject_max_items"]),
        "project_memory_inject_max_chars": str(values["project_inject_max_chars"]),
        "project_memory_manual_items": str(values["project_manual_items"]),
        "project_memory_extract_debounce_seconds": str(values["project_extract_debounce_seconds"]),
        "project_memory_extract_max_wait_seconds": str(values["project_extract_max_wait_seconds"]),
        "project_memory_extract_min_new_messages": str(values["project_extract_min_new_messages"]),
        "project_memory_semantic_top_k": str(values["project_semantic_top_k"]),
        "project_memory_lexical_top_k": str(values["project_lexical_top_k"]),
        "project_memory_min_similarity": str(values["project_min_similarity"]),
    }


async def update_memory_settings(db: AsyncSession, updates: dict[str, Any]) -> dict[str, Any]:
    current = await get_memory_settings(db)
    merged = dict(current)
    mapping = {
        "feature_enabled": "memory_feature_enabled",
        "extraction_model_id": "memory_extraction_model_id",
        "embedding_model": "memory_embedding_model",
        "embedding_dimensions": "memory_embedding_dimensions",
        "extract_debounce_seconds": "memory_extract_debounce_seconds",
        "extract_max_wait_seconds": "memory_extract_max_wait_seconds",
        "extract_min_new_messages": "memory_extract_min_new_messages",
        "max_per_user": "memory_max_per_user",
        "inject_max_items": "memory_inject_max_items",
        "inject_max_chars": "memory_inject_max_chars",
        "core_items": "memory_core_items",
        "semantic_top_k": "memory_semantic_top_k",
        "lexical_top_k": "memory_lexical_top_k",
        "min_similarity": "memory_min_similarity",
        "retrieval_timeout_ms": "memory_retrieval_timeout_ms",
        "allowed_sensitive_categories": "memory_allowed_sensitive_categories",
        "stale_archive_days": "memory_stale_archive_days",
        "soft_delete_purge_days": "memory_soft_delete_purge_days",
        "suppression_days": "memory_suppression_days",
        "qdrant_collection_version": "memory_qdrant_collection_version",
        "project_feature_enabled": "project_memory_feature_enabled",
        "project_max_per_project": "project_memory_max_per_project",
        "project_inject_max_items": "project_memory_inject_max_items",
        "project_inject_max_chars": "project_memory_inject_max_chars",
        "project_manual_items": "project_memory_manual_items",
        "project_extract_debounce_seconds": "project_memory_extract_debounce_seconds",
        "project_extract_max_wait_seconds": "project_memory_extract_max_wait_seconds",
        "project_extract_min_new_messages": "project_memory_extract_min_new_messages",
        "project_semantic_top_k": "project_memory_semantic_top_k",
        "project_lexical_top_k": "project_memory_lexical_top_k",
        "project_min_similarity": "project_memory_min_similarity",
    }
    unknown = sorted(set(updates) - set(mapping))
    if unknown:
        raise MemorySettingsError(f"Unknown setting: {unknown[0]}")
    for field, value in updates.items():
        if value is None and field in ("extraction_model_id", "embedding_model", "embedding_dimensions"):
            merged[field] = None if field != "embedding_model" else ""
            continue
        merged[field] = value

    parsed = parse_memory_settings(_raw_from_values(merged))
    if parsed["extraction_model_id"] is not None:
        await _assert_extraction_model(db, int(parsed["extraction_model_id"]))
    if parsed["embedding_model"]:
        provider, external_id, dims = await _assert_embedding_model(
            db, parsed["embedding_model"], parsed["embedding_dimensions"]
        )
        parsed["embedding_model"] = f"{provider}:{external_id}"
        parsed["embedding_dimensions"] = dims

    for key, value in _raw_from_values(parsed).items():
        await _upsert_setting(db, key, value)
    return parsed


def parse_embedding_spec(spec: str) -> tuple[str, str] | None:
    raw = (spec or "").strip()
    if ":" not in raw:
        return None
    provider, model = raw.split(":", 1)
    provider = provider.strip().lower()
    model = model.strip()
    if not provider or not model:
        return None
    return provider, model
