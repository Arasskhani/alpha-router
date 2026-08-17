"""Governed Tool Registry, policy resolution, and bounded execution contracts."""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import math
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.agent import AgentVersion
from app.models.agent_tool import AgentTool, AgentToolAuditEvent, AgentToolVersion
from app.models.model_catalog import AIModel
from app.services.agent_policy_service import AgentToolPolicy, resolve_agent_policies

EFFECT_READ_ONLY = "read_only"
EFFECT_SIDE_EFFECTING = "side_effecting"
APPROVAL_NEVER = "never"
APPROVAL_REQUIRED = "required"

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_HANDLER_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
_PERMISSION_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
_SECRET_REF_RE = re.compile(r"^(?:secret|vault|kms)://[A-Za-z0-9_./:-]{1,220}$")
_SENSITIVE_KEY_RE = re.compile(
    r"(?:^|[_-])(?:api[_-]?key|password|passwd|secret|token|credential|"
    r"private[_-]?key|access[_-]?key)(?:$|[_-])",
    re.IGNORECASE,
)
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
)
_MAX_SCHEMA_BYTES = 64 * 1024
_MAX_SCHEMA_DEPTH = 16
_MAX_SCHEMA_PROPERTIES = 256


class ToolRegistryError(ValueError):
    """Base error for invalid or unavailable registered tools."""


class ToolPolicyDenied(PermissionError):
    """Tool invocation is not permitted by immutable Agent policy."""


class ToolApprovalRequired(ToolPolicyDenied):
    """A side-effecting call needs explicit user consent."""


class ToolLimitExceeded(RuntimeError):
    """A bounded Agent turn exhausted time, hops, calls, or cost."""


class ToolExecutionFailed(RuntimeError):
    """A validated tool handler failed or returned an invalid payload."""


class ToolTransientError(RuntimeError):
    """A handler may raise this to opt into a bounded retry."""


def normalize_tool_slug(value: str) -> str:
    slug = (value or "").strip().lower().replace("_", "-").replace(" ", "-")
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug or len(slug) > 128 or not _SLUG_RE.fullmatch(slug):
        raise ToolRegistryError(
            "Tool slug must contain lowercase letters, numbers, and single hyphens"
        )
    return slug


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _schema_stats(value: Any, *, depth: int = 0) -> tuple[int, int]:
    if depth > _MAX_SCHEMA_DEPTH:
        raise ToolRegistryError("Tool JSON Schema exceeds the maximum nesting depth")
    if isinstance(value, dict):
        property_count = len(value.get("properties") or {})
        total = property_count
        maximum = depth
        for child in value.values():
            child_properties, child_depth = _schema_stats(child, depth=depth + 1)
            total += child_properties
            maximum = max(maximum, child_depth)
        return total, maximum
    if isinstance(value, list):
        total = 0
        maximum = depth
        for child in value:
            child_properties, child_depth = _schema_stats(child, depth=depth + 1)
            total += child_properties
            maximum = max(maximum, child_depth)
        return total, maximum
    return 0, depth


def _walk_schema(value: Any, *, input_schema: bool) -> None:
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and not ref.startswith("#"):
            raise ToolRegistryError("Remote JSON Schema references are not allowed")
        properties = value.get("properties")
        if input_schema and isinstance(properties, dict):
            sensitive = sorted(
                str(name) for name in properties if _SENSITIVE_KEY_RE.search(str(name))
            )
            if sensitive:
                raise ToolRegistryError(
                    "Credentials must use secret_ref and cannot be model-supplied "
                    f"tool arguments: {sensitive}"
                )
        for child in value.values():
            _walk_schema(child, input_schema=input_schema)
    elif isinstance(value, list):
        for child in value:
            _walk_schema(child, input_schema=input_schema)


def validate_tool_json_schema(
    schema: dict,
    *,
    input_schema: bool,
) -> dict:
    if not isinstance(schema, dict):
        raise ToolRegistryError("Tool schemas must be JSON objects")
    encoded = _canonical_json(schema).encode("utf-8")
    if len(encoded) > _MAX_SCHEMA_BYTES:
        raise ToolRegistryError("Tool JSON Schema exceeds 64 KiB")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ToolRegistryError(f"Invalid Tool JSON Schema: {exc.message}") from exc
    if schema.get("type") != "object":
        raise ToolRegistryError("Tool input and output schemas must have type=object")
    if schema.get("additionalProperties") is not False:
        raise ToolRegistryError(
            "Tool schemas must explicitly set additionalProperties=false"
        )
    property_count, _ = _schema_stats(schema)
    if property_count > _MAX_SCHEMA_PROPERTIES:
        raise ToolRegistryError("Tool JSON Schema contains too many properties")
    _walk_schema(schema, input_schema=input_schema)
    return json.loads(encoded.decode("utf-8"))


def _normalize_rate_limit_policy(value: dict | None) -> dict:
    raw = dict(value or {})
    unknown = set(raw) - {"calls_per_minute", "calls_per_user_per_minute"}
    if unknown:
        raise ToolRegistryError(f"Unknown rate-limit fields: {sorted(unknown)}")
    normalized: dict[str, int] = {}
    for key, item in raw.items():
        amount = int(item)
        if amount < 1 or amount > 10_000:
            raise ToolRegistryError("Tool rate limits must be between 1 and 10000")
        normalized[key] = amount
    return normalized


def _normalize_cost_policy(value: dict | None) -> dict:
    raw = dict(value or {})
    unknown = set(raw) - {"estimated_cost_usd", "maximum_cost_usd"}
    if unknown:
        raise ToolRegistryError(f"Unknown tool cost fields: {sorted(unknown)}")
    normalized: dict[str, float] = {}
    for key, item in raw.items():
        amount = float(item)
        if not math.isfinite(amount) or amount < 0.0 or amount > 100.0:
            raise ToolRegistryError(
                "Tool cost bounds must be finite values from 0 to 100"
            )
        normalized[key] = amount
    estimated = normalized.get("estimated_cost_usd", 0.0)
    maximum = normalized.get("maximum_cost_usd", estimated)
    if maximum < estimated:
        raise ToolRegistryError("maximum_cost_usd cannot be below estimated_cost_usd")
    if raw:
        normalized["estimated_cost_usd"] = estimated
        normalized["maximum_cost_usd"] = maximum
    return normalized


def _normalize_model_compatibility(value: dict | None) -> dict:
    raw = dict(value or {})
    unknown = set(raw) - {
        "allowed_model_ids",
        "allowed_provider_types",
        "requires_native_tool_calling",
    }
    if unknown:
        raise ToolRegistryError(
            f"Unknown model compatibility fields: {sorted(unknown)}"
        )
    models = tuple(
        dict.fromkeys(
            " ".join(str(item).split())
            for item in raw.get("allowed_model_ids", [])
            if str(item).strip()
        )
    )
    providers = tuple(
        dict.fromkeys(
            str(item).strip().lower()
            for item in raw.get("allowed_provider_types", [])
            if str(item).strip()
        )
    )
    if len(models) > 128 or len(providers) > 32:
        raise ToolRegistryError(
            "Tool model compatibility allowlists exceed safe limits"
        )
    return {
        "allowed_model_ids": list(models),
        "allowed_provider_types": list(providers),
        "requires_native_tool_calling": bool(
            raw.get("requires_native_tool_calling", False)
        ),
    }


def _version_fingerprint(
    *,
    tool_id: str,
    version_number: int,
    payload: dict[str, Any],
) -> str:
    canonical = {
        "tool_id": tool_id,
        "version_number": version_number,
        **payload,
    }
    return hashlib.sha256(_canonical_json(canonical).encode("utf-8")).hexdigest()


async def _audit(
    db: AsyncSession,
    *,
    event_type: str,
    tool_id: str | None,
    tool_version_id: str | None = None,
    actor_user_id: int | None = None,
    reason: str | None = None,
    payload: dict | None = None,
) -> None:
    db.add(
        AgentToolAuditEvent(
            id=str(uuid.uuid4()),
            tool_id=tool_id,
            tool_version_id=tool_version_id,
            actor_user_id=actor_user_id,
            event_type=event_type,
            reason=reason,
            payload=payload or {},
        )
    )


async def _lock_tool(db: AsyncSession, tool_id: str) -> AgentTool:
    tool = (
        await db.execute(
            select(AgentTool).where(AgentTool.id == tool_id).with_for_update()
        )
    ).scalar_one_or_none()
    if tool is None:
        raise ToolRegistryError("Tool no longer exists")
    return tool


async def _lock_tool_version(
    db: AsyncSession,
    version_id: str,
) -> AgentToolVersion:
    version = (
        await db.execute(
            select(AgentToolVersion)
            .where(AgentToolVersion.id == version_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if version is None:
        raise ToolRegistryError("Tool version no longer exists")
    return version


async def create_agent_tool(
    db: AsyncSession,
    *,
    name: str,
    slug: str,
    description: str | None = None,
    created_by_user_id: int | None = None,
) -> AgentTool:
    clean_name = " ".join((name or "").split())
    if not clean_name or len(clean_name) > 255:
        raise ToolRegistryError("Tool name is required and limited to 255 characters")
    clean_slug = normalize_tool_slug(slug)
    existing = (
        await db.execute(select(AgentTool.id).where(AgentTool.slug == clean_slug))
    ).scalar_one_or_none()
    if existing is not None:
        raise ToolRegistryError(f"Tool slug already exists: {clean_slug}")
    tool = AgentTool(
        id=str(uuid.uuid4()),
        slug=clean_slug,
        name=clean_name,
        description=(description or "").strip() or None,
        status="draft",
        created_by_user_id=created_by_user_id,
    )
    db.add(tool)
    await db.flush()
    await _audit(
        db,
        event_type="agent_tool.created",
        tool_id=tool.id,
        actor_user_id=created_by_user_id,
        payload={"slug": clean_slug, "name": clean_name},
    )
    return tool


def _normalized_version_payload(
    *,
    input_schema: dict,
    output_schema: dict,
    handler_key: str,
    effect_type: str,
    required_permission: str | None,
    timeout_seconds: int | None,
    max_retries: int,
    idempotent: bool,
    approval_mode: str,
    secret_ref: str | None,
    model_compatibility: dict | None,
    rate_limit_policy: dict | None,
    cost_policy: dict | None,
) -> dict[str, Any]:
    settings = get_settings()
    clean_handler = (handler_key or "").strip().lower()
    if not _HANDLER_RE.fullmatch(clean_handler):
        raise ToolRegistryError("handler_key is invalid")
    effect = (effect_type or "").strip().lower()
    if effect not in {EFFECT_READ_ONLY, EFFECT_SIDE_EFFECTING}:
        raise ToolRegistryError("effect_type must be read_only or side_effecting")
    approval = (approval_mode or "").strip().lower()
    if approval not in {APPROVAL_NEVER, APPROVAL_REQUIRED}:
        raise ToolRegistryError("approval_mode must be never or required")
    if effect == EFFECT_SIDE_EFFECTING and approval != APPROVAL_REQUIRED:
        raise ToolRegistryError("Side-effecting tools require explicit user approval")
    if effect == EFFECT_SIDE_EFFECTING and not idempotent:
        raise ToolRegistryError("Side-effecting tools must implement idempotency")
    retries = int(max_retries)
    if retries < 0 or retries > 3:
        raise ToolRegistryError("max_retries must be between 0 and 3")
    if retries and not idempotent:
        raise ToolRegistryError("Only idempotent tools may be retried")
    timeout = int(timeout_seconds or settings.agent_tool_default_timeout_seconds)
    if timeout < 1 or timeout > 120:
        raise ToolRegistryError("Tool timeout must be between 1 and 120 seconds")
    permission = (required_permission or "").strip().lower() or None
    if permission and not _PERMISSION_RE.fullmatch(permission):
        raise ToolRegistryError("required_permission is invalid")
    clean_secret_ref = (secret_ref or "").strip() or None
    if clean_secret_ref and not _SECRET_REF_RE.fullmatch(clean_secret_ref):
        raise ToolRegistryError(
            "secret_ref must be an opaque secret://, vault://, or kms:// reference"
        )
    return {
        "input_schema": validate_tool_json_schema(
            input_schema,
            input_schema=True,
        ),
        "output_schema": validate_tool_json_schema(
            output_schema,
            input_schema=False,
        ),
        "handler_key": clean_handler,
        "effect_type": effect,
        "required_permission": permission,
        "timeout_seconds": timeout,
        "max_retries": retries,
        "idempotent": bool(idempotent),
        "approval_mode": approval,
        "secret_ref": clean_secret_ref,
        "model_compatibility": _normalize_model_compatibility(model_compatibility),
        "rate_limit_policy": _normalize_rate_limit_policy(rate_limit_policy),
        "cost_policy": _normalize_cost_policy(cost_policy),
    }


async def create_agent_tool_version(
    db: AsyncSession,
    tool: AgentTool,
    *,
    input_schema: dict,
    output_schema: dict,
    handler_key: str,
    effect_type: str = EFFECT_READ_ONLY,
    required_permission: str | None = None,
    timeout_seconds: int | None = None,
    max_retries: int = 0,
    idempotent: bool = True,
    approval_mode: str = APPROVAL_NEVER,
    secret_ref: str | None = None,
    model_compatibility: dict | None = None,
    rate_limit_policy: dict | None = None,
    cost_policy: dict | None = None,
    change_summary: str | None = None,
    created_by_user_id: int | None = None,
) -> AgentToolVersion:
    payload = _normalized_version_payload(
        input_schema=input_schema,
        output_schema=output_schema,
        handler_key=handler_key,
        effect_type=effect_type,
        required_permission=required_permission,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        idempotent=idempotent,
        approval_mode=approval_mode,
        secret_ref=secret_ref,
        model_compatibility=model_compatibility,
        rate_limit_policy=rate_limit_policy,
        cost_policy=cost_policy,
    )
    tool = await _lock_tool(db, tool.id)
    next_number = (
        int(
            (
                await db.execute(
                    select(func.max(AgentToolVersion.version_number)).where(
                        AgentToolVersion.tool_id == tool.id
                    )
                )
            ).scalar_one_or_none()
            or 0
        )
        + 1
    )
    version = AgentToolVersion(
        id=str(uuid.uuid4()),
        tool_id=tool.id,
        version_number=next_number,
        status="draft",
        fingerprint=_version_fingerprint(
            tool_id=tool.id,
            version_number=next_number,
            payload=payload,
        ),
        change_summary=(change_summary or "").strip() or None,
        created_by_user_id=created_by_user_id,
        last_modified_by_user_id=created_by_user_id,
        **payload,
    )
    db.add(version)
    await db.flush()
    await _audit(
        db,
        event_type="agent_tool.version.created",
        tool_id=tool.id,
        tool_version_id=version.id,
        actor_user_id=created_by_user_id,
        payload={"version_number": next_number},
    )
    return version


async def update_agent_tool_draft(
    db: AsyncSession,
    version: AgentToolVersion,
    *,
    actor_user_id: int | None,
    change_summary: str | None = None,
    **changes: Any,
) -> AgentToolVersion:
    version = await _lock_tool_version(db, version.id)
    if version.status != "draft":
        raise ToolRegistryError("Only draft Tool versions can be edited")
    current = {
        "input_schema": version.input_schema,
        "output_schema": version.output_schema,
        "handler_key": version.handler_key,
        "effect_type": version.effect_type,
        "required_permission": version.required_permission,
        "timeout_seconds": version.timeout_seconds,
        "max_retries": version.max_retries,
        "idempotent": version.idempotent,
        "approval_mode": version.approval_mode,
        "secret_ref": version.secret_ref,
        "model_compatibility": version.model_compatibility,
        "rate_limit_policy": version.rate_limit_policy,
        "cost_policy": version.cost_policy,
    }
    unknown = set(changes) - set(current)
    if unknown:
        raise ToolRegistryError(f"Unknown Tool version fields: {sorted(unknown)}")
    current.update(changes)
    payload = _normalized_version_payload(**current)
    for key, value in payload.items():
        setattr(version, key, value)
    if change_summary is not None:
        version.change_summary = change_summary.strip() or None
    version.fingerprint = _version_fingerprint(
        tool_id=version.tool_id,
        version_number=version.version_number,
        payload=payload,
    )
    version.last_modified_by_user_id = actor_user_id
    await _audit(
        db,
        event_type="agent_tool.version.updated",
        tool_id=version.tool_id,
        tool_version_id=version.id,
        actor_user_id=actor_user_id,
        payload={"fingerprint": version.fingerprint},
    )
    return version


async def submit_agent_tool_version(
    db: AsyncSession,
    version: AgentToolVersion,
    *,
    actor_user_id: int | None,
) -> AgentToolVersion:
    version = await _lock_tool_version(db, version.id)
    if version.status != "draft":
        raise ToolRegistryError("Only draft Tool versions can be submitted")
    payload = _normalized_version_payload(
        input_schema=version.input_schema,
        output_schema=version.output_schema,
        handler_key=version.handler_key,
        effect_type=version.effect_type,
        required_permission=version.required_permission,
        timeout_seconds=version.timeout_seconds,
        max_retries=version.max_retries,
        idempotent=version.idempotent,
        approval_mode=version.approval_mode,
        secret_ref=version.secret_ref,
        model_compatibility=version.model_compatibility,
        rate_limit_policy=version.rate_limit_policy,
        cost_policy=version.cost_policy,
    )
    for key, value in payload.items():
        setattr(version, key, value)
    version.fingerprint = _version_fingerprint(
        tool_id=version.tool_id,
        version_number=version.version_number,
        payload=payload,
    )
    version.status = "review"
    version.submitted_by_user_id = actor_user_id
    version.submitted_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    await _audit(
        db,
        event_type="agent_tool.version.submitted",
        tool_id=version.tool_id,
        tool_version_id=version.id,
        actor_user_id=actor_user_id,
        payload={"fingerprint": version.fingerprint},
    )
    return version


async def get_active_agent_tool_version(
    db: AsyncSession,
    tool_id: str,
) -> AgentToolVersion | None:
    return (
        await db.execute(
            select(AgentToolVersion).where(
                AgentToolVersion.tool_id == tool_id,
                AgentToolVersion.active_scope_key == f"tool:{tool_id}",
                AgentToolVersion.status == "published",
            )
        )
    ).scalar_one_or_none()


async def publish_agent_tool_version(
    db: AsyncSession,
    version: AgentToolVersion,
    *,
    actor_user_id: int,
    allow_same_actor: bool = False,
) -> AgentToolVersion:
    tool = await _lock_tool(db, version.tool_id)
    version = await _lock_tool_version(db, version.id)
    if version.status != "review":
        raise ToolRegistryError("Tool version must be in review before publish")
    reviewed_payload = _normalized_version_payload(
        input_schema=version.input_schema,
        output_schema=version.output_schema,
        handler_key=version.handler_key,
        effect_type=version.effect_type,
        required_permission=version.required_permission,
        timeout_seconds=version.timeout_seconds,
        max_retries=version.max_retries,
        idempotent=version.idempotent,
        approval_mode=version.approval_mode,
        secret_ref=version.secret_ref,
        model_compatibility=version.model_compatibility,
        rate_limit_policy=version.rate_limit_policy,
        cost_policy=version.cost_policy,
    )
    reviewed_fingerprint = _version_fingerprint(
        tool_id=version.tool_id,
        version_number=version.version_number,
        payload=reviewed_payload,
    )
    if reviewed_fingerprint != version.fingerprint:
        raise ToolRegistryError(
            "Reviewed Tool version changed after submission; create a new review"
        )
    maker_actor_ids = {
        int(candidate)
        for candidate in (
            version.created_by_user_id,
            version.last_modified_by_user_id,
            version.submitted_by_user_id,
        )
        if candidate is not None
    }
    if not allow_same_actor and int(actor_user_id) in maker_actor_ids:
        raise ToolRegistryError(
            "Maker-checker violation: a Tool version author or submitter "
            "cannot publish it"
        )
    current = await get_active_agent_tool_version(db, tool.id)
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    if current is not None and current.id != version.id:
        current.active_scope_key = None
        current.status = "archived"
        current.archived_at = now
        await db.flush()
    version.status = "published"
    version.active_scope_key = f"tool:{tool.id}"
    version.published_by_user_id = actor_user_id
    version.published_at = now
    version.archived_at = None
    tool.status = "active"
    await _audit(
        db,
        event_type="agent_tool.version.published",
        tool_id=tool.id,
        tool_version_id=version.id,
        actor_user_id=actor_user_id,
        payload={
            "version_number": version.version_number,
            "fingerprint": version.fingerprint,
        },
    )
    return version


async def rollback_agent_tool_version(
    db: AsyncSession,
    target: AgentToolVersion,
    *,
    actor_user_id: int,
    reason: str,
) -> AgentToolVersion:
    clean_reason = " ".join((reason or "").split())
    if not clean_reason:
        raise ToolRegistryError("Tool rollback reason is required")
    await _lock_tool(db, target.tool_id)
    target = await _lock_tool_version(db, target.id)
    if target.status not in {"published", "archived"} or target.published_at is None:
        raise ToolRegistryError(
            "Only a previously published Tool version can be restored"
        )
    current = await get_active_agent_tool_version(db, target.tool_id)
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    if current is not None and current.id != target.id:
        current.active_scope_key = None
        current.status = "archived"
        current.archived_at = now
        await db.flush()
    target.status = "published"
    target.active_scope_key = f"tool:{target.tool_id}"
    target.published_by_user_id = actor_user_id
    target.published_at = now
    target.archived_at = None
    await _audit(
        db,
        event_type="agent_tool.version.rolled_back",
        tool_id=target.tool_id,
        tool_version_id=target.id,
        actor_user_id=actor_user_id,
        reason=clean_reason,
        payload={
            "restored_version_number": target.version_number,
            "replaced_version_id": (
                current.id if current is not None and current.id != target.id else None
            ),
        },
    )
    return target


@dataclass(frozen=True)
class ResolvedAgentTool:
    tool: AgentTool
    version: AgentToolVersion
    required: bool

    def as_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.tool.slug.replace("-", "_"),
                "description": self.tool.description or self.tool.name,
                "parameters": self.version.input_schema,
            },
        }


async def resolve_agent_tools(
    db: AsyncSession,
    policy: AgentToolPolicy,
) -> tuple[ResolvedAgentTool, ...]:
    resolved: list[ResolvedAgentTool] = []
    denied = set(policy.denied_tools)
    for grant in policy.tools:
        if grant.slug in denied:
            raise ToolPolicyDenied(f"Tool is explicitly denied: {grant.slug}")
        tool = (
            await db.execute(select(AgentTool).where(AgentTool.slug == grant.slug))
        ).scalar_one_or_none()
        if tool is None or tool.status != "active":
            if grant.required:
                raise ToolRegistryError(
                    f"Required Agent tool is unavailable: {grant.slug}"
                )
            continue
        if grant.version_id:
            version = await db.get(AgentToolVersion, grant.version_id)
            valid = (
                version is not None
                and version.tool_id == tool.id
                and version.status in {"published", "archived"}
                and version.published_at is not None
            )
            if not valid:
                if grant.required:
                    raise ToolRegistryError(
                        f"Pinned Agent tool version is unavailable: {grant.slug}"
                    )
                continue
        else:
            version = await get_active_agent_tool_version(db, tool.id)
            if version is None:
                if grant.required:
                    raise ToolRegistryError(
                        f"Required Agent tool has no active version: {grant.slug}"
                    )
                continue
        resolved.append(
            ResolvedAgentTool(tool=tool, version=version, required=grant.required)
        )
    return tuple(resolved)


async def validate_agent_tool_bindings(
    db: AsyncSession,
    agent_version: AgentVersion,
) -> tuple[ResolvedAgentTool, ...]:
    policies = resolve_agent_policies(agent_version)
    return await resolve_agent_tools(db, policies.tools)


def assert_tool_model_compatible(spec: ResolvedAgentTool, model: AIModel) -> None:
    policy = dict(spec.version.model_compatibility or {})
    allowed_models = {
        str(value) for value in policy.get("allowed_model_ids", []) if str(value)
    }
    allowed_providers = {
        str(value).strip().lower()
        for value in policy.get("allowed_provider_types", [])
        if str(value).strip()
    }
    references = {str(model.id), f"model::{model.id}", model.external_id}
    if allowed_models and references.isdisjoint(allowed_models):
        raise ToolPolicyDenied(
            f"Model {model.external_id} is not compatible with tool {spec.tool.slug}"
        )
    if (
        allowed_providers
        and (model.provider_type or "").strip().lower() not in allowed_providers
    ):
        raise ToolPolicyDenied(
            f"Provider {model.provider_type} is not compatible with tool {spec.tool.slug}"
        )


@dataclass(frozen=True)
class ToolHandlerResult:
    payload: dict[str, Any]
    cost_usd: float = 0.0


@dataclass(frozen=True)
class ToolExecutionContext:
    correlation_id: str
    user_id: int | None
    permissions: frozenset[str] = frozenset()
    user_approved: bool = False
    idempotency_key: str | None = None


@dataclass(frozen=True)
class ToolGuardrailRequest:
    stage: str
    tool_id: str
    tool_version_id: str
    execution_id: str
    user_id: int | None
    correlation_id: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class ToolGuardrailDecision:
    allowed: bool
    reason_code: str


class ToolExecutionGuardrails(Protocol):
    async def evaluate(
        self,
        request: ToolGuardrailRequest,
    ) -> ToolGuardrailDecision: ...


class AllowAuditToolExecutionGuardrails:
    """Default mandatory hook boundary for deployments without a custom engine."""

    async def evaluate(
        self,
        request: ToolGuardrailRequest,
    ) -> ToolGuardrailDecision:
        return ToolGuardrailDecision(
            allowed=True,
            reason_code=f"{request.stage}_policy_allow",
        )


@dataclass
class ToolExecutionBudget:
    max_calls: int
    max_hops: int
    max_total_seconds: int
    max_cost_usd: float
    calls: int = 0
    spent_usd: float = 0.0
    _started_at: float = field(default_factory=time.monotonic)

    @classmethod
    def from_policy(cls, policy: AgentToolPolicy) -> ToolExecutionBudget:
        return cls(
            max_calls=policy.max_calls_per_turn,
            max_hops=policy.max_hops_per_turn,
            max_total_seconds=policy.max_total_seconds,
            max_cost_usd=policy.max_cost_usd,
        )

    def begin(self, *, hop: int, estimated_cost_usd: float) -> None:
        if time.monotonic() - self._started_at > self.max_total_seconds:
            raise ToolLimitExceeded("Agent tool time budget exhausted")
        if hop < 0 or hop >= self.max_hops:
            raise ToolLimitExceeded("Agent tool hop limit exhausted")
        if self.calls >= self.max_calls:
            raise ToolLimitExceeded("Agent tool call limit exhausted")
        if self.spent_usd + estimated_cost_usd > self.max_cost_usd:
            raise ToolLimitExceeded("Agent tool cost budget exhausted")
        self.calls += 1
        self.spent_usd += estimated_cost_usd

    def settle(self, *, estimated_cost_usd: float, actual_cost_usd: float) -> None:
        self.spent_usd = max(0.0, self.spent_usd - estimated_cost_usd) + actual_cost_usd
        if self.spent_usd > self.max_cost_usd:
            raise ToolLimitExceeded("Agent tool actual cost exceeded the turn budget")


@dataclass(frozen=True)
class ToolExecutionResult:
    execution_id: str
    payload: dict[str, Any]
    attempts: int
    elapsed_seconds: float
    cost_usd: float
    redacted_paths: tuple[str, ...]
    guardrail_reason_codes: tuple[str, ...]
    cached: bool = False


class ToolInvocationLedger(Protocol):
    async def load_completed(
        self,
        *,
        idempotency_key: str,
        tool_version_id: str,
    ) -> dict[str, Any] | None: ...

    async def claim(
        self,
        *,
        idempotency_key: str,
        tool_version_id: str,
        correlation_id: str,
    ) -> bool: ...

    async def complete(
        self,
        *,
        idempotency_key: str,
        tool_version_id: str,
        result: dict[str, Any],
    ) -> None: ...

    async def fail(
        self,
        *,
        idempotency_key: str,
        tool_version_id: str,
        error_code: str,
    ) -> None: ...


class ToolRateLimiter(Protocol):
    async def consume(
        self,
        *,
        tool_version_id: str,
        user_id: int | None,
        calls_per_minute: int | None,
        calls_per_user_per_minute: int | None,
    ) -> bool: ...


ToolHandler = Callable[
    [dict[str, Any], ToolExecutionContext],
    Awaitable[dict[str, Any] | ToolHandlerResult],
]


def _validate_instance(schema: dict, payload: dict, *, label: str) -> None:
    try:
        Draft202012Validator(schema).validate(payload)
    except ValidationError as exc:
        path = ".".join(str(value) for value in exc.absolute_path) or "<root>"
        raise ToolExecutionFailed(f"Invalid {label} at {path}: {exc.message}") from exc


def _sanitize_payload(value: Any, *, path: str = "$") -> tuple[Any, list[str]]:
    redacted: list[str] = []
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if _SENSITIVE_KEY_RE.search(key_text):
                output[key_text] = "[REDACTED]"
                redacted.append(child_path)
                continue
            output[key_text], child_redacted = _sanitize_payload(item, path=child_path)
            redacted.extend(child_redacted)
        return output, redacted
    if isinstance(value, list):
        output_list: list[Any] = []
        for index, item in enumerate(value):
            sanitized, child_redacted = _sanitize_payload(item, path=f"{path}[{index}]")
            output_list.append(sanitized)
            redacted.extend(child_redacted)
        return output_list, redacted
    if isinstance(value, str) and any(
        pattern.search(value) for pattern in _SENSITIVE_VALUE_PATTERNS
    ):
        return "[REDACTED]", [path]
    return value, redacted


def _cost_bounds(spec: ResolvedAgentTool) -> tuple[float, float]:
    policy = spec.version.cost_policy or {}
    estimated = float(policy.get("estimated_cost_usd", 0.0))
    maximum = float(policy.get("maximum_cost_usd", estimated))
    if not math.isfinite(estimated) or estimated < 0:
        estimated = 0.0
    if not math.isfinite(maximum) or maximum < estimated:
        maximum = estimated
    return estimated, maximum


async def _evaluate_tool_guardrail(
    guardrails: ToolExecutionGuardrails,
    request: ToolGuardrailRequest,
    *,
    timeout_seconds: int,
) -> ToolGuardrailDecision:
    try:
        async with asyncio.timeout(max(1, min(timeout_seconds, 10))):
            decision = await guardrails.evaluate(request)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        raise ToolPolicyDenied(
            f"Tool guardrail unavailable at {request.stage}"
        ) from exc
    if not isinstance(decision, ToolGuardrailDecision):
        raise ToolPolicyDenied(
            f"Tool guardrail returned an invalid decision at {request.stage}"
        )
    if not decision.allowed:
        raise ToolPolicyDenied(
            f"Tool guardrail denied execution at {request.stage}: "
            f"{decision.reason_code}"
        )
    return decision


async def execute_agent_tool(
    *,
    spec: ResolvedAgentTool,
    model: AIModel,
    arguments: dict[str, Any],
    context: ToolExecutionContext,
    handler: ToolHandler,
    budget: ToolExecutionBudget,
    hop: int,
    ledger: ToolInvocationLedger | None = None,
    rate_limiter: ToolRateLimiter | None = None,
    guardrails: ToolExecutionGuardrails | None = None,
) -> ToolExecutionResult:
    """Validate and execute one bounded call; side effects require durable idempotency."""

    version = spec.version
    execution_id = str(uuid.uuid4())
    guardrails = guardrails or AllowAuditToolExecutionGuardrails()
    guardrail_reason_codes: list[str] = []
    assert_tool_model_compatible(spec, model)
    if (
        version.required_permission
        and version.required_permission not in context.permissions
    ):
        raise ToolPolicyDenied(
            f"Missing required permission for tool {spec.tool.slug}: "
            f"{version.required_permission}"
        )
    rate_policy = dict(version.rate_limit_policy or {})
    if rate_policy:
        if rate_limiter is None:
            raise ToolPolicyDenied(
                f"Tool {spec.tool.slug} requires a configured rate limiter"
            )
        allowed = await rate_limiter.consume(
            tool_version_id=version.id,
            user_id=context.user_id,
            calls_per_minute=rate_policy.get("calls_per_minute"),
            calls_per_user_per_minute=rate_policy.get("calls_per_user_per_minute"),
        )
        if not allowed:
            raise ToolLimitExceeded(f"Tool {spec.tool.slug} rate limit exceeded")
    if version.effect_type == EFFECT_SIDE_EFFECTING:
        if version.approval_mode != APPROVAL_REQUIRED or not context.user_approved:
            raise ToolApprovalRequired(
                f"Tool {spec.tool.slug} requires explicit user approval"
            )
        if not context.idempotency_key:
            raise ToolPolicyDenied(f"Tool {spec.tool.slug} requires an idempotency key")
        if ledger is None:
            raise ToolPolicyDenied(
                "Side-effecting tools require a durable invocation ledger"
            )
    _validate_instance(version.input_schema, arguments, label="tool input")
    _, sensitive_input_paths = _sanitize_payload(arguments)
    if sensitive_input_paths:
        raise ToolPolicyDenied(
            "Credential-like values cannot be supplied through model tool arguments"
        )
    pre_decision = await _evaluate_tool_guardrail(
        guardrails,
        ToolGuardrailRequest(
            stage="pre_tool_execution",
            tool_id=spec.tool.id,
            tool_version_id=version.id,
            execution_id=execution_id,
            user_id=context.user_id,
            correlation_id=context.correlation_id,
            payload=arguments,
        ),
        timeout_seconds=int(version.timeout_seconds),
    )
    guardrail_reason_codes.append(pre_decision.reason_code)

    _, maximum_cost = _cost_bounds(spec)
    budget.begin(hop=hop, estimated_cost_usd=maximum_cost)
    started = time.monotonic()
    claimed = False
    if version.effect_type == EFFECT_SIDE_EFFECTING:
        assert context.idempotency_key is not None
        assert ledger is not None
        cached = await ledger.load_completed(
            idempotency_key=context.idempotency_key,
            tool_version_id=version.id,
        )
        if cached is not None:
            _validate_instance(
                version.output_schema, cached, label="cached tool output"
            )
            sanitized, redacted = _sanitize_payload(cached)
            post_decision = await _evaluate_tool_guardrail(
                guardrails,
                ToolGuardrailRequest(
                    stage="post_tool_execution",
                    tool_id=spec.tool.id,
                    tool_version_id=version.id,
                    execution_id=execution_id,
                    user_id=context.user_id,
                    correlation_id=context.correlation_id,
                    payload=sanitized,
                ),
                timeout_seconds=int(version.timeout_seconds),
            )
            guardrail_reason_codes.append(post_decision.reason_code)
            budget.settle(estimated_cost_usd=maximum_cost, actual_cost_usd=0.0)
            return ToolExecutionResult(
                execution_id=execution_id,
                payload=sanitized,
                attempts=0,
                elapsed_seconds=time.monotonic() - started,
                cost_usd=0.0,
                redacted_paths=tuple(redacted),
                guardrail_reason_codes=tuple(guardrail_reason_codes),
                cached=True,
            )
        claimed = await ledger.claim(
            idempotency_key=context.idempotency_key,
            tool_version_id=version.id,
            correlation_id=context.correlation_id,
        )
        if not claimed:
            raise ToolExecutionFailed(
                "An invocation with this idempotency key is already in progress"
            )

    attempts = 0
    try:
        while True:
            attempts += 1
            try:
                async with asyncio.timeout(int(version.timeout_seconds)):
                    raw_result = await handler(arguments, context)
                break
            except ToolTransientError:
                if not version.idempotent or attempts > int(version.max_retries):
                    raise
                await asyncio.sleep(min(0.25 * (2 ** (attempts - 1)), 1.0))
        if isinstance(raw_result, ToolHandlerResult):
            payload = raw_result.payload
            actual_cost = float(raw_result.cost_usd)
        else:
            payload = raw_result
            actual_cost = 0.0
        if (
            not isinstance(payload, dict)
            or not math.isfinite(actual_cost)
            or actual_cost < 0.0
        ):
            raise ToolExecutionFailed("Tool handler returned an invalid result")
        if actual_cost > maximum_cost:
            raise ToolExecutionFailed(
                "Tool handler exceeded its registered cost ceiling"
            )
        _validate_instance(version.output_schema, payload, label="tool output")
        sanitized, redacted = _sanitize_payload(payload)
        encoded = _canonical_json(sanitized).encode("utf-8")
        maximum_output_bytes = max(
            1_024,
            min(1024 * 1024, get_settings().agent_tool_max_output_bytes),
        )
        if len(encoded) > maximum_output_bytes:
            raise ToolExecutionFailed("Tool output exceeds the configured size limit")
        post_decision = await _evaluate_tool_guardrail(
            guardrails,
            ToolGuardrailRequest(
                stage="post_tool_execution",
                tool_id=spec.tool.id,
                tool_version_id=version.id,
                execution_id=execution_id,
                user_id=context.user_id,
                correlation_id=context.correlation_id,
                payload=sanitized,
            ),
            timeout_seconds=int(version.timeout_seconds),
        )
        guardrail_reason_codes.append(post_decision.reason_code)
        if claimed:
            assert context.idempotency_key is not None
            assert ledger is not None
            await ledger.complete(
                idempotency_key=context.idempotency_key,
                tool_version_id=version.id,
                result=sanitized,
            )
        budget.settle(
            estimated_cost_usd=maximum_cost,
            actual_cost_usd=actual_cost,
        )
        return ToolExecutionResult(
            execution_id=execution_id,
            payload=sanitized,
            attempts=attempts,
            elapsed_seconds=time.monotonic() - started,
            cost_usd=actual_cost,
            redacted_paths=tuple(redacted),
            guardrail_reason_codes=tuple(guardrail_reason_codes),
        )
    except asyncio.CancelledError:
        if claimed:
            assert context.idempotency_key is not None
            assert ledger is not None
            await ledger.fail(
                idempotency_key=context.idempotency_key,
                tool_version_id=version.id,
                error_code="cancelled",
            )
        raise
    except TimeoutError as exc:
        if claimed:
            assert context.idempotency_key is not None
            assert ledger is not None
            await ledger.fail(
                idempotency_key=context.idempotency_key,
                tool_version_id=version.id,
                error_code="timeout",
            )
        raise ToolExecutionFailed(f"Tool {spec.tool.slug} timed out") from exc
    except Exception as exc:
        if claimed:
            assert context.idempotency_key is not None
            assert ledger is not None
            await ledger.fail(
                idempotency_key=context.idempotency_key,
                tool_version_id=version.id,
                error_code=type(exc).__name__.lower()[:64],
            )
        if isinstance(
            exc,
            (ToolExecutionFailed, ToolPolicyDenied, ToolLimitExceeded),
        ):
            raise
        raise ToolExecutionFailed(f"Tool {spec.tool.slug} failed") from exc
