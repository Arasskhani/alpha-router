"""Export / import user chats as versioned JSON (Alpha Router, ChatGPT, Open WebUI)."""

from __future__ import annotations

import datetime as dt
import logging
import time
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.branding import LOGGER_NAMESPACE, PRODUCT_NAME
from app.services import user_chat_storage_service as chat_store

logger = logging.getLogger(f"{LOGGER_NAMESPACE}.security.settings")

MAX_EXPORT_SESSIONS = 500
MAX_IMPORT_SESSIONS = 200
MAX_MESSAGES_PER_SESSION = 2000
MAX_MESSAGE_CHARS = 200_000
MAX_IMPORT_BYTES = 20 * 1024 * 1024
CHAT_EXPORT_FORMAT = "alpha-router-chats"


class ChatImportError(ValueError):
    """User-facing import validation error."""


def _timestamp_to_ms(value: Any) -> int | None:
    """Normalize OpenWebUI/ChatGPT/Alpha Router timestamps to unix milliseconds."""
    if value is None or value is False:
        return None
    try:
        if isinstance(value, str) and value.strip():
            value = float(value.strip())
        if isinstance(value, (int, float)):
            n = float(value)
            if n <= 0:
                return None
            # Seconds vs milliseconds heuristic
            if n < 1_000_000_000_000:
                return int(n * 1000)
            return int(n)
    except (TypeError, ValueError):
        return None
    return None


def finalize_imported_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mark imported history as completed so the UI does not treat it as streaming.

    Alpha Router treats an assistant message without ``receivedAt`` as an in-flight
    generation (STOP button). Imported chats must always finalize that field.
    """
    now_ms = int(time.time() * 1000)
    total = len(messages)
    out: list[dict[str, Any]] = []
    for idx, raw in enumerate(messages):
        if not isinstance(raw, dict):
            continue
        role = "user" if str(raw.get("role") or "user") == "user" else "assistant"
        # Prefer source timestamps; otherwise stagger so order stays visible.
        fallback = now_ms - max(0, total - idx) * 1000
        ts = (
            _timestamp_to_ms(raw.get("receivedAt"))
            or _timestamp_to_ms(raw.get("sentAt"))
            or _timestamp_to_ms(raw.get("timestamp"))
            or fallback
        )
        msg: dict[str, Any] = {
            "role": role,
            "content": _clip_content(raw.get("content")),
            "modelId": raw.get("modelId"),
            "modelName": raw.get("modelName"),
            "streaming": False,
        }
        if role == "user":
            msg["sentAt"] = _timestamp_to_ms(raw.get("sentAt")) or ts
        else:
            msg["receivedAt"] = _timestamp_to_ms(raw.get("receivedAt")) or ts
            sent = _timestamp_to_ms(raw.get("sentAt"))
            if sent is not None:
                msg["sentAt"] = sent
        out.append(msg)
    return out


def _clip_content(value: Any) -> str:
    text = str(value or "")
    if len(text) > MAX_MESSAGE_CHARS:
        return text[:MAX_MESSAGE_CHARS]
    return text


async def export_user_chats(db: AsyncSession, user_id: int) -> dict[str, Any]:
    sessions: list[dict[str, Any]] = []
    offset = 0
    page_size = 200
    while len(sessions) < MAX_EXPORT_SESSIONS:
        batch, _total, _older = await chat_store.list_chat_sessions(
            db,
            user_id,
            limit=min(page_size, MAX_EXPORT_SESSIONS - len(sessions)),
            offset=offset,
            exclude_empty_old=False,
        )
        if not batch:
            break
        sessions.extend(batch)
        offset += len(batch)
        if len(batch) < page_size:
            break
    exported: list[dict[str, Any]] = []
    for meta in sessions[:MAX_EXPORT_SESSIONS]:
        sid = str(meta.get("id") or "")
        if not sid:
            continue
        messages: list[dict[str, Any]] = []
        before: int | None = None
        # Walk pages newest→oldest then reverse for chronological export
        page_stack: list[list[dict[str, Any]]] = []
        for _ in range(20):
            batch, has_more = await chat_store.list_session_messages(
                db, user_id, sid, limit=200, before=before
            )
            if not batch:
                break
            page_stack.append(batch)
            before = int(batch[0].get("sequence") or 0)
            if not has_more:
                break
        for page in reversed(page_stack):
            messages.extend(page)
        if len(messages) > MAX_MESSAGES_PER_SESSION:
            messages = messages[:MAX_MESSAGES_PER_SESSION]
        exported.append(
            {
                "id": sid,
                "title": meta.get("title") or "Chat",
                "model": meta.get("model") or "",
                "createdAt": meta.get("createdAt"),
                "updatedAt": meta.get("updatedAt"),
                "messages": [
                    {
                        "role": m.get("role") or "user",
                        "content": m.get("content") or "",
                        "modelId": m.get("modelId"),
                        "modelName": m.get("modelName"),
                        "sentAt": m.get("sentAt"),
                        "receivedAt": m.get("receivedAt"),
                    }
                    for m in messages
                ],
            }
        )

    return {
        "format": CHAT_EXPORT_FORMAT,
        "version": 1,
        "exported_at": dt.datetime.utcnow().isoformat() + "Z",
        "sessions": exported,
    }


def detect_import_format(payload: Any) -> str:
    if isinstance(payload, dict):
        fmt = str(payload.get("format") or "").lower()
        if fmt == CHAT_EXPORT_FORMAT and isinstance(payload.get("sessions"), list):
            return CHAT_EXPORT_FORMAT
        # Open WebUI: often { "chats": [...] } or list of chat objects with "chat"/"messages"
        if isinstance(payload.get("chats"), list):
            return "openwebui"
        if "mapping" in payload and ("title" in payload or "create_time" in payload):
            return "chatgpt"
    if isinstance(payload, list):
        if not payload:
            raise ChatImportError("Empty import file")
        first = payload[0]
        if isinstance(first, dict):
            if "mapping" in first:
                return "chatgpt"
            if "chat" in first or "messages" in first or "history" in first:
                return "openwebui"
            if isinstance(first.get("messages"), list) and ("title" in first or "id" in first):
                return "openwebui"
    raise ChatImportError("Unrecognized chat export format")


def _normalize_alpha_router_sessions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    sessions = payload.get("sessions")
    if not isinstance(sessions, list):
        raise ChatImportError(f"Invalid {PRODUCT_NAME} export: missing sessions array")
    return sessions


def _chatgpt_messages_from_mapping(mapping: dict[str, Any]) -> list[dict[str, Any]]:
    """Linearize ChatGPT conversation mapping into user/assistant messages."""
    # Find root / current node chain
    nodes = mapping if isinstance(mapping, dict) else {}
    # Prefer walking children from the root message
    root_id = None
    for nid, node in nodes.items():
        if not isinstance(node, dict):
            continue
        parent = node.get("parent")
        if parent is None:
            root_id = nid
            break
    messages: list[dict[str, Any]] = []
    current = root_id
    seen: set[str] = set()
    while current and current in nodes and current not in seen:
        seen.add(current)
        node = nodes[current]
        msg = node.get("message") if isinstance(node, dict) else None
        if isinstance(msg, dict):
            role = str((msg.get("author") or {}).get("role") or msg.get("role") or "")
            content_obj = msg.get("content")
            text = ""
            if isinstance(content_obj, dict):
                parts = content_obj.get("parts")
                if isinstance(parts, list):
                    text = "\n".join(str(p) for p in parts if p is not None)
                else:
                    text = str(content_obj.get("text") or "")
            elif isinstance(content_obj, str):
                text = content_obj
            if text.strip() and role in ("user", "assistant", "system"):
                entry = {
                    "role": "assistant" if role != "user" else "user",
                    "content": _clip_content(text),
                }
                create_time = msg.get("create_time")
                ts = _timestamp_to_ms(create_time)
                if ts is not None:
                    entry["timestamp"] = ts
                messages.append(entry)
        children = node.get("children") if isinstance(node, dict) else None
        if isinstance(children, list) and children:
            current = children[-1]
        else:
            break
    return messages


def _parse_chatgpt(payload: Any) -> list[dict[str, Any]]:
    items = payload if isinstance(payload, list) else [payload]
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "Imported chat")[:512]
        mapping = item.get("mapping")
        if not isinstance(mapping, dict):
            continue
        messages = _chatgpt_messages_from_mapping(mapping)
        if not messages:
            continue
        out.append({"title": title, "messages": messages, "model": ""})
    return out


def _openwebui_messages(chat_obj: Any) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if isinstance(chat_obj, dict):
        # Newer OWUI: chat.messages or history.messages
        hist = chat_obj.get("history")
        if isinstance(hist, dict) and isinstance(hist.get("messages"), dict):
            # message map — order by timestamp if present
            vals = list(hist["messages"].values())
            vals.sort(key=lambda m: float((m or {}).get("timestamp") or 0) if isinstance(m, dict) else 0)
            for m in vals:
                if not isinstance(m, dict):
                    continue
                role = str(m.get("role") or "user")
                content = m.get("content")
                if isinstance(content, list):
                    # multimodal parts
                    texts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            texts.append(str(part.get("text") or ""))
                        elif isinstance(part, str):
                            texts.append(part)
                    content = "\n".join(texts)
                if content is None:
                    continue
                entry: dict[str, Any] = {
                    "role": "user" if role == "user" else "assistant",
                    "content": _clip_content(content),
                }
                ts = _timestamp_to_ms(m.get("timestamp"))
                if ts is not None:
                    entry["timestamp"] = ts
                messages.append(entry)
            return messages
        raw_msgs = chat_obj.get("messages")
        if isinstance(raw_msgs, list):
            for m in raw_msgs:
                if not isinstance(m, dict):
                    continue
                role = str(m.get("role") or "user")
                entry = {
                    "role": "user" if role == "user" else "assistant",
                    "content": _clip_content(m.get("content")),
                }
                ts = _timestamp_to_ms(m.get("timestamp"))
                if ts is not None:
                    entry["timestamp"] = ts
                messages.append(entry)
    return messages


def _parse_openwebui(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("chats"), list):
        items = payload["chats"]
    elif isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = [payload]
    else:
        raise ChatImportError("Invalid Open WebUI export")

    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or "Imported chat")[:512]
        chat_obj = item.get("chat") if isinstance(item.get("chat"), dict) else item
        messages = _openwebui_messages(chat_obj)
        if not messages:
            continue
        model = ""
        if isinstance(chat_obj, dict):
            models = chat_obj.get("models")
            if isinstance(models, list) and models:
                model = str(models[0] or "")
            else:
                model = str(chat_obj.get("model") or "")
        out.append({"title": title, "messages": messages, "model": model[:512]})
    return out


def parse_import_sessions(payload: Any) -> tuple[str, list[dict[str, Any]]]:
    fmt = detect_import_format(payload)
    if fmt == CHAT_EXPORT_FORMAT:
        if not isinstance(payload, dict):
            raise ChatImportError(f"Invalid {PRODUCT_NAME} export")
        raw = _normalize_alpha_router_sessions(payload)
        sessions: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            msgs_in = item.get("messages")
            if not isinstance(msgs_in, list):
                continue
            messages = []
            for m in msgs_in[:MAX_MESSAGES_PER_SESSION]:
                if not isinstance(m, dict):
                    continue
                role = str(m.get("role") or "user")
                messages.append(
                    {
                        "role": "user" if role == "user" else "assistant",
                        "content": _clip_content(m.get("content")),
                        "modelId": m.get("modelId"),
                        "modelName": m.get("modelName"),
                        "sentAt": m.get("sentAt"),
                        "receivedAt": m.get("receivedAt"),
                    }
                )
            if not messages:
                continue
            sessions.append(
                {
                    "title": str(item.get("title") or "Imported chat")[:512],
                    "messages": messages,
                    "model": str(item.get("model") or "")[:512],
                }
            )
        return fmt, sessions
    if fmt == "chatgpt":
        return fmt, _parse_chatgpt(payload)
    if fmt == "openwebui":
        return fmt, _parse_openwebui(payload)
    raise ChatImportError("Unrecognized chat export format")


async def import_user_chats(db: AsyncSession, user_id: int, payload: Any) -> dict[str, Any]:
    fmt, sessions = parse_import_sessions(payload)
    if len(sessions) > MAX_IMPORT_SESSIONS:
        raise ChatImportError(f"Too many chats (max {MAX_IMPORT_SESSIONS})")

    imported = 0
    skipped = 0
    await chat_store.ensure_user_chat_store(db, user_id)

    for item in sessions:
        messages = item.get("messages") or []
        if not messages:
            skipped += 1
            continue
        if len(messages) > MAX_MESSAGES_PER_SESSION:
            messages = messages[:MAX_MESSAGES_PER_SESSION]
        new_id = str(uuid.uuid4())
        try:
            await chat_store.create_chat_session(
                db,
                user_id,
                {
                    "id": new_id,
                    "title": item.get("title") or "Imported chat",
                    "model": item.get("model") or "",
                },
            )
            # Always new IDs — never reuse foreign message ids
            # Finalize timestamps so UI does not show STOP / streaming for history.
            finalized = finalize_imported_messages(messages)
            clean_msgs = []
            for m in finalized:
                clean_msgs.append(
                    {
                        "role": m["role"],
                        "content": m.get("content") or "",
                        "clientMessageId": str(uuid.uuid4()),
                        "modelId": m.get("modelId"),
                        "modelName": m.get("modelName"),
                        "sentAt": m.get("sentAt"),
                        "receivedAt": m.get("receivedAt"),
                        "streaming": False,
                    }
                )
            # append in chunks
            chunk = 50
            for i in range(0, len(clean_msgs), chunk):
                await chat_store.append_session_messages(
                    db, user_id, new_id, clean_msgs[i : i + chunk]
                )
            imported += 1
        except Exception:
            logger.exception("Failed importing chat for user_id=%s", user_id)
            skipped += 1

    return {
        "imported": imported,
        "skipped": skipped,
        "format": fmt,
        "message": f"Imported {imported} chat(s) from {fmt}"
        + (f", skipped {skipped}" if skipped else "")
        + ".",
    }
