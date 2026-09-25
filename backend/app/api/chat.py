"""In-app chat using enabled models (admin + user)."""

import asyncio
import json
import re
from typing import Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.api.deps import get_current_user, require_active_user
from app.branding import CHAT_CLIENT_APP, EXTENSION_CLIENT_APP
from app.config import get_settings
from app.database import get_db
from app.models.chat import ChatSession
from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.models.user import User
from app.services.client_ip import resolve_client_ip
from app.services.extension_access import AGENT_TOOL, permitted_extension_tools
from app.services.extension_page_context import (
    MAX_PAGE_CHARS,
    MAX_PAGE_IMAGES,
    MAX_PAGE_SITES,
    PageContextRefused,
    PageShare,
    check_agent_model,
    check_page_shares,
    page_share_events,
    page_shares,
)
from app.services.extension_settings import load_extension_settings
from app.services.attachment_extract import processed_attachment_payload_async
from app.services.attachment_from_media_service import attachments_from_existing_media
from app.services.attachment_policy import (
    AttachmentPolicyError,
    media_response_type_and_disposition,
    resolve_attachment_mime,
    validate_attachment_size,
)
from app.services.bounded_io import BoundedIOError, clamp_limit, read_upload_bounded
from app.services.budget_service import (
    budget_request_blocked,
    ensure_budget_period,
    get_user_budget_state,
)
from app.services.chat_docx_service import ChatExportError as DocxExportError
from app.services.chat_docx_service import render_chat_docx
from app.services.chat_export_service import (
    ChatExportError,
    build_download_content_disposition,
    build_pdf_content_disposition,
    render_chat_pdf,
)
from app.services.chat_markers import BROWSER_TOOL_CHOICE_BODY_KEY, BROWSER_TOOLS_BODY_KEY, PAGE_CONTEXT_BODY_KEY
from app.services.chat_session_access import resolve_owned_chat_session
from app.services.chat_title_service import generate_chat_title
from app.services.chat_tool_access_service import assert_tool_for_user, permitted_tool_keys
from app.services.chat_tool_registry import CHAT_TOOLS
from app.services.chat_xlsx_service import ChatExportError as XlsxExportError
from app.services.chat_xlsx_service import render_chat_xlsx
from app.services.image_prompt_service import (
    ENHANCE_CONTEXTS,
    ENHANCE_MODES,
    PromptEnhanceError,
    enhance_image_generation_prompt,
    enhance_user_prompt,
)
from app.services.media_authorization_service import (
    MediaAccessAction,
    load_authorized_media_asset,
)
from app.services.private_mode_service import effective_private_mode
from app.services.model_access_service import (
    filter_models_for_subject,
    resolve_access_subject,
)
from app.services.model_capabilities import (
    image_generation_capabilities,
    model_kinds,
    model_media_flags,
    speech_generation_capabilities,
    supports_vision,
    video_generation_capabilities,
)
from app.services.model_tool_compatibility_service import (
    compatibility_map_for_models,
    compatibility_payload,
    is_auto_router_model_id,
    is_code_interpreter_candidate,
)
from app.services.project_media_service import (
    ProjectMediaValidationError,
    persist_scoped_chat_media,
)
from app.services.proxy_service import (
    STREAM_SSE_HEADERS,
    preflight_stream_chat,
    stream_chat,
)
from app.services.resource_access_service import resolve_resource_access_subject
from app.services.storage_service import (
    list_user_media,
    media_public_url,
    read_media_bytes,
    read_media_range,
    store_generated_media,
    unlink_storage_if_unreferenced,
)
from app.services.system_default_models import get_all_default_model_ids
from app.services.transcription_service import transcribe_audio_bytes
from app.services.upload_file_policy import (
    KIND_DOCUMENT,
    KIND_FILE,
    check_content,
    classify,
    load_policy,
)
from app.services.upload_screening import UploadRejected, screen_upload
from app.services.user_chat_storage_service import load_user_prefs

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.get("/models")
async def chat_models(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conn_count = (await db.execute(select(func.count()).select_from(Connection))).scalar() or 0
    if conn_count == 0:
        # No connections -> no usable models. Orphan catalog rows (FK cascade
        # off) are removed by DELETE /api/admin/connections/{id}; a GET must
        # never write.
        return []

    rows = (
        (
            await db.execute(
                select(AIModel)
                .join(Connection, Connection.id == AIModel.connection_id)
                .where(AIModel.is_enabled == True, Connection.is_active == True)  # noqa: E712
            )
        )
        .scalars()
        .all()
    )
    subject = await resolve_access_subject(db, user_id=user.id)
    rows = await filter_models_for_subject(db, list(rows), subject)
    compatibility = await compatibility_map_for_models(db, rows)
    system_defaults = await get_all_default_model_ids(db)
    default_id = system_defaults.get("chat")
    return [
        {
            "id": f"model::{m.id}",
            "name": m.display_name or m.external_id,
            "external_id": m.external_id,
            "is_system_default": default_id is not None and int(m.id) == int(default_id),
            # Admin-chosen defaults per capability, so the client stops falling
            # back to "first capable model in catalog order".
            "default_kinds": [
                key for key, value in system_defaults.items() if value is not None and int(value) == int(m.id)
            ],
            "code_interpreter": compatibility_payload(
                compatibility.get((int(m.connection_id), m.external_id)),
                static_candidate=is_code_interpreter_candidate(m),
                auto_router=is_auto_router_model_id(m.external_id),
            ),
            # The snapshot goes to every helper unconditionally. Passing None
            # when the model is not classified as that kind told the helper
            # "this provider published nothing", which sent it to its id-based
            # fallback -- so a model this same payload reports as
            # is_image_model=false could come back supports_text_to_image=true
            # purely because of its name. A helper that can read the provider's
            # answer must always be given it.
            **image_generation_capabilities(
                external_id=m.external_id or "",
                is_image_model=media["is_image_model"],
                pricing_raw=m.pricing_raw,
            ),
            **video_generation_capabilities(
                external_id=m.external_id or "",
                is_video_model=media["is_video_model"],
                pricing_raw=m.pricing_raw,
            ),
            **speech_generation_capabilities(
                external_id=m.external_id or "",
                is_speech_model=media["is_speech_model"],
                pricing_raw=m.pricing_raw,
            ),
            "supports_vision": supports_vision(
                external_id=m.external_id or "",
                is_image_model=media["is_image_model"],
                pricing_raw=m.pricing_raw,
                provider_type=m.provider_type,
            ),
            "kinds": model_kinds(
                external_id=m.external_id or "",
                is_image_model=media["is_image_model"],
                is_video_model=media["is_video_model"],
                pricing_raw=m.pricing_raw,
                provider_type=m.provider_type,
            ),
            **media,
        }
        for m in rows
        for media in [
            model_media_flags(
                external_id=m.external_id or "",
                is_image_model=bool(m.is_image_model),
                is_video_model=bool(getattr(m, "is_video_model", False)),
                pricing_raw=m.pricing_raw,
                provider_type=m.provider_type,
            )
        ]
    ]


class ChatToolsIn(BaseModel):
    web_search: bool = False
    web_search_depth: str = "medium"
    web_fetch: bool = False
    image_generation: bool = False
    video_generation: bool = False
    speech_generation: bool = False
    code_interpreter: bool = False


class ExtensionPageSiteIn(BaseModel):
    """A site whose page content the request carries: its host (``URL.hostname``), how many
    characters of text, and how many screenshots."""

    host: str = Field(..., min_length=1, max_length=253)
    chars: int = Field(..., ge=0, le=MAX_PAGE_CHARS)
    images: int = Field(0, ge=0, le=MAX_PAGE_IMAGES)


class ExtensionPageContextIn(BaseModel):
    sites: list[ExtensionPageSiteIn] = Field(..., min_length=1, max_length=MAX_PAGE_SITES)


#: Tools one step of the browser agent may offer the model, and their size as JSON.
MAX_BROWSER_TOOLS = 32
MAX_BROWSER_TOOLS_BYTES = 32 * 1024


class BrowserToolFunctionIn(BaseModel):
    """One of the agent's tools as the OpenAI API describes a function: name, what it does, its arguments."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    description: str = Field("", max_length=4000)
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})

    @field_validator("parameters")
    @classmethod
    def _an_object_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        if value.get("type") != "object":
            raise ValueError("A tool's parameters are a JSON schema of type object.")
        return value


class BrowserToolIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["function"]
    function: BrowserToolFunctionIn


class ChatRequest(BaseModel):
    model: str | None = None
    messages: list[dict]
    stream: bool = True
    web_search: bool = False
    tools: ChatToolsIn | None = None
    chat_session_id: str | None = None
    persist_chat: bool = False
    private_mode: bool = False
    project_id: str | None = None
    user_message: dict | None = None
    assistant_client_message_id: str | None = None
    alpharouter: dict | None = None
    agent_id: str | None = None
    agent_slug: str | None = None
    agent_version_id: str | None = None
    agent_auto_route: bool | None = None
    include_citations: bool | None = None
    #: The browser extension's declaration of the pages in ``messages``; refused from anyone else.
    extension_page_context: ExtensionPageContextIn | None = None
    #: The browser extension agent's tools for this step; the reply streams the model's tool calls.
    browser_tools: list[BrowserToolIn] | None = Field(None, min_length=1, max_length=MAX_BROWSER_TOOLS)
    browser_tool_choice: Literal["auto", "none", "required"] | None = None

    @model_validator(mode="after")
    def _browser_tools_shape(self) -> "ChatRequest":
        if self.browser_tools is None:
            if self.browser_tool_choice is not None:
                raise ValueError("browser_tool_choice goes with browser_tools.")
            return self
        names = [tool.function.name for tool in self.browser_tools]
        if len(set(names)) != len(names):
            raise ValueError("Each browser tool needs a name of its own.")
        size = len(json.dumps([tool.model_dump() for tool in self.browser_tools], separators=(",", ":")).encode())
        if size > MAX_BROWSER_TOOLS_BYTES:
            raise ValueError(f"The browser tools come to more than {MAX_BROWSER_TOOLS_BYTES // 1024} KB.")
        return self


#: Fields that hand a turn to an Agent Studio agent, which chooses its own model and tools.
_AGENT_FIELDS = ("alpharouter", "agent_id", "agent_slug", "agent_version_id", "agent_auto_route", "include_citations")


def _extension_session_id(request: Request) -> str | None:
    return getattr(request.state, "extension_session_id", None)


def _client_app(request: Request) -> str:
    return EXTENSION_CLIENT_APP if _extension_session_id(request) else CHAT_CLIENT_APP


def _page_context_conflict(body: ChatRequest, tools: dict) -> str | None:
    """Why the declared pages cannot go with the rest of this request, if they cannot.

    An agent picks its own model, which the page-content list would never see;
    tools could carry page text to a search engine or a fetched URL; a project
    chat is read by teammates. The extension sends none of these with a page.
    """
    if any(getattr(body, key) is not None for key in _AGENT_FIELDS):
        return "Pages cannot be shared with an agent."
    if body.project_id:
        return "Pages cannot be shared in a project chat."
    if body.web_search or any(value is True for value in tools.values()):
        return "Pages cannot be shared together with tools."
    return None


def _browser_tools_conflict(body: ChatRequest, tools: dict) -> str | None:
    """Why the agent's tools cannot go with the rest of this request, if they cannot.

    A step of the browser agent is one model call and nothing else: an Agent
    Studio agent would choose its own model and tools, chat tools and Code
    Interpreter would run beside the agent's, and a step is never saved to a
    chat (the panel keeps the run; each step's reservation stands alone).
    Pages reach the agent through its own tools, never as declared pages.
    """
    if any(getattr(body, key) is not None for key in _AGENT_FIELDS):
        return "The browser agent cannot run with an Agent Studio agent."
    if body.web_search or any(value is True for value in tools.values()):
        return "The browser agent cannot use chat tools."
    if body.extension_page_context is not None:
        return "The browser agent reads pages with its own tools."
    if (
        body.persist_chat
        or body.chat_session_id
        or body.project_id
        or body.user_message is not None
        or body.assistant_client_message_id
    ):
        return "Browser agent steps are not saved to a chat."
    return None


async def _browser_agent_tools(
    db: AsyncSession,
    request: Request,
    body: ChatRequest,
    payload: dict,
    tools: dict,
    user: User,
) -> None:
    """The agent's tools for this step, checked before anything is spent and handed to the turn.

    Only a connected browser whose user may use the agent can offer them, and
    only to a model the administrator's lists allow; the model is checked as
    the turn will resolve it and then pinned in the payload.
    """
    if body.browser_tools is None:
        return
    if not _extension_session_id(request):
        raise HTTPException(
            status_code=400,
            detail={"code": "extension_only", "message": "Only the browser extension can offer browser tools."},
        )
    conflict = _browser_tools_conflict(body, tools)
    if conflict:
        raise HTTPException(status_code=400, detail={"code": "browser_tools_conflict", "message": conflict})
    if AGENT_TOOL not in await permitted_extension_tools(db, user):
        raise HTTPException(
            status_code=403,
            detail={"code": "agent_not_permitted", "message": "The browser agent is not enabled for your account."},
        )
    try:
        model = await check_agent_model(db, model_ref=str(body.model or ""), settings=await load_extension_settings(db))
    except PageContextRefused as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail()) from None
    if model is not None:
        payload["model"] = f"model::{model.id}"
    payload[BROWSER_TOOLS_BODY_KEY] = [tool.model_dump() for tool in body.browser_tools]
    if body.browser_tool_choice is not None:
        payload[BROWSER_TOOL_CHOICE_BODY_KEY] = body.browser_tool_choice


async def _project_chat_conflict(db: AsyncSession, chat_session_id: str | None) -> str | None:
    """A project chat is read by teammates, whether the request names the project or only the chat."""
    sid = (chat_session_id or "").strip()
    if not sid:
        return None
    project_id = (await db.execute(select(ChatSession.project_id).where(ChatSession.id == sid))).scalar_one_or_none()
    return "Pages cannot be shared in a project chat." if project_id else None


async def _declared_page_shares(
    db: AsyncSession,
    request: Request,
    body: ChatRequest,
    payload: dict,
    tools: dict,
) -> list[PageShare]:
    """The pages the extension says it sent, checked against the admin's rules before anything is spent.

    The model is checked as the turn will resolve it and then pinned in the
    payload, so the turn goes to exactly the model that was checked.
    """
    context = body.extension_page_context
    if context is None:
        return []
    if not _extension_session_id(request):
        raise HTTPException(
            status_code=400,
            detail={"code": "extension_only", "message": "Only the browser extension can share pages."},
        )
    conflict = _page_context_conflict(body, tools) or await _project_chat_conflict(db, body.chat_session_id)
    if conflict:
        raise HTTPException(status_code=400, detail={"code": "page_context_conflict", "message": conflict})
    try:
        shares = page_shares((site.host, site.chars, site.images) for site in context.sites)
        model = await check_page_shares(
            db,
            shares,
            model_ref=str(body.model or ""),
            settings=await load_extension_settings(db),
        )
    except PageContextRefused as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail()) from None
    if model is not None:
        payload["model"] = f"model::{model.id}"
    return shares


class ChatTitleIn(BaseModel):
    model: str
    messages: list[dict]


class EnhancePromptIn(BaseModel):
    model: str
    prompt: str
    mode: str  # "improve" | "translate" | "translate_improve"
    context: str = "image"  # "image" | "chat"


class EnhanceImagePromptIn(BaseModel):
    model: str
    prompt: str
    mode: str  # "improve" | "translate" | "translate_improve"


class AttachFromMediaIn(BaseModel):
    media_ids: list[int] = Field(..., min_length=1, max_length=500)
    chat_session_id: str | None = None
    project_id: str | None = None


class MediaStoreIn(BaseModel):
    kind: str = "image"
    data_url: str | None = None
    source_url: str | None = None
    file_name: str | None = None
    model: str | None = None
    prompt: str | None = None
    chat_session_id: str | None = None
    metadata: dict | None = None


@router.get("/tools")
async def chat_tools(
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """The chat tools this account may use.

    The composer draws its menu from this rather than from a list baked into
    the client, so a tool added to the registry appears without a frontend
    change and a tool an administrator has restricted does not appear at all.
    """
    subject = await resolve_resource_access_subject(db, user_id=user.id)
    permitted = await permitted_tool_keys(db, subject)
    return [
        {
            "key": spec.key,
            "title": spec.title,
            "description": spec.description,
            "icon": spec.icon,
            "permitted": spec.key in permitted,
        }
        for spec in CHAT_TOOLS
    ]


@router.post("/session-title")
async def chat_session_title(
    request: Request,
    body: ChatTitleIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Short overview title from conversation start (not the first user message verbatim)."""
    title = await generate_chat_title(db, user, body.model, body.messages, client_app=_client_app(request))
    return {"title": title}


@router.post("/enhance-prompt")
async def enhance_prompt(
    body: EnhancePromptIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Lightly improve or translate a user prompt (image or chat context)."""
    if body.mode not in ENHANCE_MODES:
        raise HTTPException(status_code=400, detail="Invalid enhancement mode")
    if body.context not in ENHANCE_CONTEXTS:
        raise HTTPException(status_code=400, detail="Invalid enhancement context")
    try:
        text = await enhance_user_prompt(db, user, body.model, body.prompt, body.mode, context=body.context)
    except PromptEnhanceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"prompt": text}


@router.post("/enhance-image-prompt")
async def enhance_image_prompt(
    body: EnhanceImagePromptIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Legacy endpoint — image context only."""
    if body.mode not in ENHANCE_MODES:
        raise HTTPException(status_code=400, detail="Invalid enhancement mode")
    try:
        text = await enhance_image_generation_prompt(db, user, body.model, body.prompt, body.mode)
    except PromptEnhanceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"prompt": text}


@router.post("/completions")
async def chat_completions(
    request: Request,
    body: ChatRequest,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    tools = body.tools.model_dump() if body.tools else {}
    payload = {
        "model": body.model,
        "messages": body.messages,
        "stream": True,
        "web_search": body.web_search or tools.get("web_search", False),
        "tools": tools,
        "user": user.email or user.username,
        "chat_session_id": body.chat_session_id,
        "persist_chat": body.persist_chat,
        "private_mode": bool(body.private_mode) and not body.project_id,
        "project_id": body.project_id,
        "user_message": body.user_message,
        "assistant_client_message_id": body.assistant_client_message_id,
    }
    for key in (
        "alpharouter",
        "agent_id",
        "agent_slug",
        "agent_version_id",
        "agent_auto_route",
        "include_citations",
    ):
        value = getattr(body, key)
        if value is not None:
            payload[key] = value
    client_app = _client_app(request)
    await _browser_agent_tools(db, request, body, payload, tools, user)
    shares = await _declared_page_shares(db, request, body, payload, tools)
    if shares:
        payload[PAGE_CONTEXT_BODY_KEY] = [share.host for share in shares]
    resolved = await preflight_stream_chat(
        db,
        payload,
        user_id=user.id,
        skip_budget=False,
        source="alpha_router_chat",
        client_app=client_app,
    )
    if shares:
        # Only once the turn is going ahead: a refused request shared nothing.
        db.add_all(
            page_share_events(
                shares,
                user=user,
                ip=resolve_client_ip(request),
                session_id=_extension_session_id(request),
                model=resolved.ai_model,
                model_ref=str(payload.get("model") or ""),
                private=effective_private_mode(payload),
            )
        )
    try:
        await db.commit()
    except BaseException:
        permit = getattr(resolved, "code_interpreter_capacity_permit", None)
        if permit is not None:
            from app.services.code_interpreter_capacity_service import (
                release_code_interpreter_turn,
            )

            await release_code_interpreter_turn(permit)
        raise
    gen = stream_chat(
        request,
        payload,
        user_id=user.id,
        username=user.username,
        source="alpha_router_chat",
        client_app=client_app,
        skip_budget=False,
        resolved=resolved,
    )
    permit = getattr(resolved, "code_interpreter_capacity_permit", None)

    async def release_capacity_fallback() -> None:
        if permit is not None:
            from app.services.code_interpreter_capacity_service import (
                release_code_interpreter_turn,
            )

            await release_code_interpreter_turn(permit)

    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers=STREAM_SSE_HEADERS,
        background=BackgroundTask(release_capacity_fallback) if permit is not None else None,
    )


@router.post("/voice")
async def voice_message(
    file: UploadFile = File(...),
    chat_session_id: str | None = Form(None),
    language: str | None = Form(None),
    duration_seconds: float | None = Form(None),
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Transcribe a recording and return the text. The recording is not kept.

    The audio lives only as long as this request: it is read into memory,
    screened, handed to the transcription provider, and dropped when the
    handler returns. It used to be written to the user's Media as well —
    an ``audio`` asset per dictation, counted against their quota — although
    nothing ever read it back: the response carried ``url: null`` from the
    start and the composer takes only the text. Keeping a recording of a
    person's voice that no feature uses is storage spent on a privacy
    liability, so it is no longer stored. Recordings kept before this change
    stay in Media until their owner or the retention policy removes them.
    """
    await assert_tool_for_user(db, "speech_to_text", user_id=user.id)
    await resolve_owned_chat_session(db, user=user, chat_session_id=chat_session_id)
    budget, usage = await get_user_budget_state(db, user)
    if blocked := budget_request_blocked(budget, usage):
        raise HTTPException(status_code=402, detail=blocked)

    try:
        voice_limit = clamp_limit(
            get_settings().max_voice_upload_bytes,
            minimum=1024 * 1024,
            maximum=25 * 1024 * 1024,
        )
        raw = await read_upload_bounded(file, max_bytes=voice_limit)
    except BoundedIOError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    mime = (file.content_type or "audio/webm").split(";")[0].strip() or "audio/webm"
    filename = file.filename or "voice.webm"
    try:
        await screen_upload(raw, filename)
    except UploadRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    # The user's own pick, when they made one. It is re-validated downstream
    # against their ACL, so an unusable value falls through to the system default.
    prefs = await load_user_prefs(db, user.id)
    preferred_model_ref = (prefs.get("transcription_model") or "").strip() or None

    try:
        transcript = await transcribe_audio_bytes(
            db,
            raw,
            filename=filename,
            mime_type=mime,
            language=language,
            user_id=user.id,
            username=user.username,
            client_duration_seconds=duration_seconds,
            preferred_model_ref=preferred_model_ref,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        import logging

        # A "clean" failure (provider rejected the model, no speech, bad audio)
        # used to return 400 with no server-side trace at all, which made these
        # invisible in the logs while the client only saw a generic notice.
        logging.getLogger("app.api.chat").warning("Transcription rejected: %s", exc, exc_info=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # Log the full provider error server-side; return a generic message so
        # upstream STT provider internals are not leaked to the chat client.
        import logging

        logging.getLogger("app.api.chat").exception("Transcription failed")
        raise HTTPException(status_code=502, detail="Transcription failed. Please try again.") from exc

    return {
        # Nothing is stored, so there is no asset to name. The keys stay so a
        # client built against the older response (a tab left open across a
        # deploy) keeps parsing it; ``media_pending`` is always false now.
        "id": None,
        "url": None,
        "transcript": transcript,
        "mime_type": mime,
        "media_pending": False,
        "media_error": None,
    }


@router.get("/attachment-limits")
async def get_attachment_limits(
    _: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Public transfer limits needed by the chat composer."""
    from app.services.transfer_limits_service import (
        get_transfer_limits,
        transfer_limits_public_view,
    )

    return transfer_limits_public_view(await get_transfer_limits(db))


@router.get("/attachment-policy")
async def attachment_policy(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_user),
) -> dict[str, object]:
    """What the composer may offer, so a refusal is explained before the upload.

    The server decides; this only lets the UI say "not allowed" at once
    instead of after the bytes have travelled. Both lists are returned so the
    picker can explain either mode. Limits come from Transfer size limits.
    """
    from app.services.transfer_limits_service import get_transfer_limits
    from app.services.upload_file_policy import load_policy

    policy = await load_policy(db)
    transfer = await get_transfer_limits(db)
    return {
        "mode": policy.mode,
        "blocked": sorted(policy.blocked),
        "allowed": sorted(policy.allowed),
        "max_attachments": int(transfer["max_chat_attachments_count"]),
        "max_upload_mb": int(transfer["max_upload_file_mb"]),
    }


@router.post("/attachments/process")
async def process_attachments(
    files: list[UploadFile] = File(...),
    chat_session_id: str | None = Form(None),
    project_id: str | None = Form(None),
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Validate, store, and extract content from chat attachments."""
    await ensure_budget_period(db, user)
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    scoped_project_id = (project_id or "").strip() or None
    # 404 unless the caller owns the session or can write in its project.
    session = await resolve_owned_chat_session(db, user=user, chat_session_id=chat_session_id)
    if not scoped_project_id and session is not None and session.project_id:
        scoped_project_id = session.project_id

    out: list[dict] = []
    total_bytes = 0
    from app.services.transfer_limits_service import get_transfer_limits

    transfer = await get_transfer_limits(db)
    max_count = int(transfer["max_chat_attachments_count"])
    if len(files) > max_count:
        raise HTTPException(
            status_code=400,
            detail=f"You can attach up to {max_count} files at once.",
        )
    attachment_limit = clamp_limit(
        int(transfer["max_upload_file_bytes"]),
        minimum=1024 * 1024,
        maximum=1024 * 1024 * 1024,
    )
    total_limit = clamp_limit(
        int(transfer["max_chat_attachments_total_bytes"]),
        minimum=attachment_limit,
        maximum=2048 * 1024 * 1024,
    )
    # The operator's upload policy, loaded once per request rather than once
    # per file: it is the same answer for every file in one message.
    upload_policy = await load_policy(db)
    for upload in files:
        filename = upload.filename or "attachment"
        try:
            # Name first, bytes second: a blocked name is refused before up to
            # a gigabyte is read into memory. The content signature check
            # needs the bytes, so it runs once they are in hand.
            ext, kind = classify(filename, upload_policy)
            remaining = total_limit - total_bytes
            if remaining <= 0:
                raise BoundedIOError(
                    f"Attachments exceed the total per-message limit ({max(1, total_limit // (1024 * 1024))} MB)."
                )
            raw = await read_upload_bounded(
                upload,
                max_bytes=min(attachment_limit, remaining),
            )
            validate_attachment_size(len(raw), max_bytes=attachment_limit)
            check_content(raw, ext=ext, kind=kind)
            total_bytes += len(raw)
        except BoundedIOError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except AttachmentPolicyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        # Archive-bomb structure check and ClamAV before the bytes are stored
        # or handed to a parser (same gate Knowledge uploads pass through).
        try:
            await screen_upload(raw, filename)
        except UploadRejected as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

        mime = resolve_attachment_mime(
            filename=filename,
            kind=kind,
            client_mime=upload.content_type,
        )
        # Media libraries know image|video|document|other. A ``file`` is stored
        # as a document — served as a download with an extension-derived type,
        # which is exactly what an unknown format must be — while the chat
        # payload keeps ``file`` so the model and the UI describe it honestly.
        storage_kind = KIND_DOCUMENT if kind == KIND_FILE else kind
        try:
            url = await persist_scoped_chat_media(
                db,
                user=user,
                project_id=scoped_project_id,
                kind=storage_kind,
                blob=raw,
                mime=mime,
                file_name=filename,
                source_prompt=filename,
                chat_session_id=chat_session_id,
                metadata={"attachment": True},
            )
        except ProjectMediaValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            status_code = 413 if "limit" in str(exc).lower() or "quota" in str(exc).lower() else 400
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        out.append(
            await processed_attachment_payload_async(
                filename=filename,
                kind=kind,
                mime_type=mime,
                url=url,
                raw=raw,
            )
        )

    return {"attachments": out}


@router.post("/attachments/from-media")
async def attachments_from_media(
    body: AttachFromMediaIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Reference existing Media library files as chat attachments (no second persist)."""
    await ensure_budget_period(db, user)
    attachments = await attachments_from_existing_media(
        db,
        user,
        body.media_ids,
        chat_session_id=body.chat_session_id,
        project_id=body.project_id,
    )
    return {"attachments": attachments}


@router.post("/media/store")
async def store_media(
    body: MediaStoreIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        asset = await store_generated_media(
            db,
            user_id=user.id,
            username=user.username,
            kind=body.kind or "image",
            source_model=body.model,
            source_prompt=body.prompt,
            chat_session_id=body.chat_session_id,
            data_url=body.data_url,
            source_url=body.source_url,
            file_name_hint=body.file_name,
            metadata=body.metadata or {},
        )
    except UploadRejected as exc:
        # Before ValueError: UploadRejected is one, and it carries its own status.
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except ValueError as exc:
        detail = str(exc)
        if "quota" in detail.lower() or "limit" in detail.lower() or "too large" in detail.lower():
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "id": asset.id,
        "kind": asset.kind,
        "file_name": asset.file_name,
        "mime_type": asset.mime_type,
        "size_bytes": asset.size_bytes,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
        "expires_at": asset.expires_at.isoformat() if asset.expires_at else None,
        "url": media_public_url(asset.id),
    }


@router.get("/media")
async def user_media(
    limit: int = 200,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await list_user_media(db, user.id, limit=min(500, max(1, limit)))
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "mime_type": r.mime_type,
            "file_name": r.file_name,
            "size_bytes": r.size_bytes,
            "source_model": r.source_model,
            "source_prompt": r.source_prompt,
            "chat_session_id": r.chat_session_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            "url": media_public_url(r.id),
        }
        for r in rows
    ]


@router.get("/media/{asset_id}/file")
async def media_file(
    asset_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await load_authorized_media_asset(
        db,
        user,
        asset_id,
        action=MediaAccessAction.READ,
    )
    media_type, content_disposition = media_response_type_and_disposition(
        file_name=row.file_name or "download",
        kind=getattr(row, "kind", None),
        stored_mime=row.mime_type,
    )
    headers = {
        "Content-Disposition": content_disposition,
        "Accept-Ranges": "bytes",
    }
    range_header = (request.headers.get("range") or "").strip()
    kind = (getattr(row, "kind", None) or "").strip().lower()
    if range_header.lower().startswith("bytes=") and kind in {"video", "audio"}:
        # Single-range support for HTML5 media seekers. Only the requested
        # window is fetched from object storage; reading the whole file to
        # slice it in Python made every seek in a long video a full download.
        spec = range_header.split("=", 1)[1].strip()
        if "," not in spec and re.fullmatch(r"\d*-\d*", spec) and spec != "-":
            from app.services.object_storage_service import InvalidRangeError

            try:
                chunk, start, end, total = await read_media_range(row, spec)
            except FileNotFoundError:
                raise HTTPException(404, detail="File not found") from None
            except InvalidRangeError:
                headers["Content-Range"] = f"bytes */{int(getattr(row, 'size_bytes', 0) or 0)}"
                return Response(status_code=416, headers=headers)
            headers.update(
                {
                    "Content-Range": f"bytes {start}-{end}/{total}",
                    "Content-Length": str(len(chunk)),
                }
            )
            return Response(
                content=chunk,
                status_code=206,
                media_type=media_type,
                headers=headers,
            )

    try:
        data = await read_media_bytes(row)
    except FileNotFoundError:
        raise HTTPException(404, detail="File not found") from None
    headers["Content-Length"] = str(len(data))
    return Response(
        content=data,
        media_type=media_type,
        headers=headers,
    )


@router.delete("/media/{asset_id}")
async def delete_media(
    asset_id: int,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    row = await load_authorized_media_asset(
        db,
        user,
        asset_id,
        action=MediaAccessAction.DELETE,
    )
    storage_path = row.storage_path
    await db.delete(row)
    await db.flush()
    await unlink_storage_if_unreferenced(db, storage_path)
    return {"ok": True}


class ChatExportPdfIn(BaseModel):
    content: str
    title: str | None = None


@router.post("/export/pdf")
async def export_chat_pdf(
    payload: ChatExportPdfIn,
    user: User = Depends(require_active_user),
):
    """Export an assistant chat message (markdown) to a PDF file.

    The content is the caller's own chat content; it is HTML-escaped before
    markdown parsing, JavaScript is disabled in the render context, and all
    sub-resource requests are aborted (anti-SSRF). See ``chat_export_service``.
    """
    if not payload.content or not payload.content.strip():
        raise HTTPException(status_code=400, detail="content must not be empty")
    try:
        pdf_bytes = await render_chat_pdf(
            content=payload.content,
            title=payload.title,
        )
    except ChatExportError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": build_pdf_content_disposition(payload.title),
            "Cache-Control": "no-store",
        },
    )


class ChatExportDocxIn(BaseModel):
    content: str
    title: str | None = None


@router.post("/export/docx")
async def export_chat_docx(
    payload: ChatExportDocxIn,
    user: User = Depends(require_active_user),
):
    """Export an assistant chat message (markdown) to a Word .docx file.

    ``python-docx`` only constructs the OpenXML package (no code execution, no
    network). See ``chat_docx_service``.
    """
    if not payload.content or not payload.content.strip():
        raise HTTPException(status_code=400, detail="content must not be empty")
    try:
        docx_bytes = await asyncio.to_thread(render_chat_docx, content=payload.content, title=payload.title)
    except DocxExportError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": build_download_content_disposition(payload.title, "docx"),
            "Cache-Control": "no-store",
        },
    )


class ChatExportXlsxIn(BaseModel):
    content: str
    title: str | None = None


@router.post("/export/xlsx")
async def export_chat_xlsx(
    payload: ChatExportXlsxIn,
    user: User = Depends(require_active_user),
):
    """Export an assistant chat message (markdown) to an Excel .xlsx file.

    ``openpyxl`` only constructs the OpenXML package (no code execution, no
    network). See ``chat_xlsx_service``.
    """
    if not payload.content or not payload.content.strip():
        raise HTTPException(status_code=400, detail="content must not be empty")
    try:
        xlsx_bytes = await asyncio.to_thread(render_chat_xlsx, content=payload.content, title=payload.title)
    except XlsxExportError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": build_download_content_disposition(payload.title, "xlsx"),
            "Cache-Control": "no-store",
        },
    )
