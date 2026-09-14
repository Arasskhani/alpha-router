"""Agent request parsing and fail-closed streaming integration tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from contextlib import ExitStack

from app.services import chat_turn_context, proxy_service, turn_settlement
from app.services.agent_chat_integration_service import (
    AgentRequestError,
    PreparedAgentTurn,
    parse_agent_request,
)
from app.services.agent_runtime_service import AgentCompletionReview
from app.services.knowledge_citation_service import (
    CitationVerification,
    KnowledgeCitation,
)


class _FakeDeltaChunk:
    def __init__(self, text: str) -> None:
        self.choices = [SimpleNamespace(delta=SimpleNamespace(content=text))]


def _request() -> MagicMock:
    request = MagicMock()
    request.client = SimpleNamespace(host="127.0.0.1")
    request.is_disconnected = AsyncMock(return_value=False)
    return request


def _session_context() -> tuple[AsyncMock, MagicMock]:
    db = AsyncMock()
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=db)
    context.__aexit__ = AsyncMock(return_value=None)
    return db, context


def test_parse_agent_request_supports_gateway_extension_and_rejects_conflicts():
    options = parse_agent_request(
        {
            "alpharouter": {
                "agent": {"slug": "legal-consultant"},
                "include_citations": False,
                "session_id": "external-session-1",
            }
        }
    )
    assert options is not None
    assert options.agent_slug == "legal-consultant"
    assert options.agent_id is None
    assert options.auto_route is False
    assert options.include_citations is False
    assert options.external_session_id == "external-session-1"

    with pytest.raises(AgentRequestError, match="Only one"):
        parse_agent_request(
            {
                "agent_id": "agent-1",
                "agent_slug": "legal-consultant",
            }
        )


def test_parse_agent_request_explicit_opt_out_skips_agent_path():
    assert parse_agent_request({"agent_auto_route": False}) is None
    assert parse_agent_request({}) is None


def test_agent_citation_metadata_only_exposes_verified_citations():
    citation = KnowledgeCitation(
        citation_id="citation-1",
        chunk_id="chunk-1",
        document_id="document-1",
        document_version_id="version-1",
        knowledge_base_id="kb-1",
        release_id="release-1",
        title="Approved policy",
        file_name="policy.pdf",
        mime_type="application/pdf",
        page_number=4,
        section="Eligibility",
        authority="canonical",
        classification="internal",
        effective_from="2026-01-01",
        effective_to=None,
        content_hash="a" * 64,
    )
    turn = PreparedAgentTurn(
        plan=SimpleNamespace(retrieval=SimpleNamespace(context=SimpleNamespace(citations=(citation,)))),
        options=SimpleNamespace(include_citations=True),
        run_id="run-citations",
        chat_session_id=None,
    )
    review = AgentCompletionReview(
        status="ready",
        display_text="Supported [[cite:citation-1]]",
        safe_response=None,
        reason_code="completion_verified",
        guardrail_decisions=(),
        citation_verification=CitationVerification(
            valid=True,
            cited_ids=("citation-1",),
            unknown_ids=(),
            missing_required=False,
            malformed=False,
        ),
    )

    payload = proxy_service._agent_citation_metadata(turn, review)

    assert payload == [
        {
            "citation_id": "citation-1",
            "marker": "[[cite:citation-1]]",
            "title": "Approved policy",
            "file_name": "policy.pdf",
            "mime_type": "application/pdf",
            "page_number": 4,
            "section": "Eligibility",
            "authority": "canonical",
            "effective_from": "2026-01-01",
            "effective_to": None,
            "document_version_id": "version-1",
        }
    ]


async def _test_non_generating_plan_returns_only_safe_response() -> None:
    db, context = _session_context()
    finalize_run = AsyncMock()
    plan = SimpleNamespace(
        status="route_required",
        safe_response="Please choose a specialist Agent.",
        selected_model_id=None,
        target=None,
        routing_outcome="clarification",
        total_planning_latency_ms=7,
    )
    turn = PreparedAgentTurn(
        plan=plan,
        options=SimpleNamespace(),
        run_id="run-route-required",
        chat_session_id=None,
    )
    resolved = SimpleNamespace(
        ai_model=None,
        api_key=None,
        base_url="",
        provider_type="",
        model_id="",
        agent_turn=turn,
    )

    with (
        patch.object(proxy_service, "AsyncSessionLocal", return_value=context),
        patch.object(chat_turn_context, "AsyncSessionLocal", return_value=context),
        patch.object(turn_settlement, "AsyncSessionLocal", return_value=context),
        patch.object(chat_turn_context, "finalize_agent_run", finalize_run),
        patch.object(turn_settlement, "finalize_agent_run", finalize_run),
        patch.object(
            proxy_service,
            "acompletion",
            AsyncMock(side_effect=AssertionError("provider must not be called")),
        ),
    ):
        output = [
            chunk
            async for chunk in proxy_service.stream_chat(
                _request(),
                {
                    "messages": [{"role": "user", "content": "Help"}],
                    "_agent_run_id": turn.run_id,
                },
                user_id=1,
                username="user",
                source="gateway",
                skip_budget=True,
                resolved=resolved,
            )
        ]

    text = b"".join(output).decode()
    assert "Please choose a specialist Agent." in text
    assert '"agent_status":"route_required"' in text
    assert text.endswith("data: [DONE]\n\n")
    finalize_run.assert_awaited_once()
    assert finalize_run.await_args.kwargs["status"] == "route_required"
    assert finalize_run.await_args.kwargs["output_displayed"] is True
    db.commit.assert_awaited_once()


async def test_non_generating_plan_returns_only_safe_response():
    await _test_non_generating_plan_returns_only_safe_response()


async def _test_agent_stream_is_buffered_until_post_generation_review() -> None:
    db, context = _session_context()
    completion_kwargs: dict = {}

    async def fake_acompletion(**kwargs):
        completion_kwargs.update(kwargs)

        async def chunks():
            yield _FakeDeltaChunk("unverified ")
            yield _FakeDeltaChunk("provider output")

        return chunks()

    policies = SimpleNamespace(model=SimpleNamespace(max_output_tokens=321, temperature=0.25))
    prompt = SimpleNamespace(
        messages=(
            {"role": "system", "content": "Approved immutable Agent prompt."},
            {"role": "user", "content": "Question"},
        )
    )
    plan = SimpleNamespace(
        status="ready",
        prompt=prompt,
        policies=policies,
        routing_outcome="explicit",
        total_planning_latency_ms=11,
    )
    turn = PreparedAgentTurn(
        plan=plan,
        options=SimpleNamespace(),
        run_id="run-buffered",
        chat_session_id=None,
    )
    resolved = SimpleNamespace(
        ai_model=SimpleNamespace(
            provider_type="openrouter",
            input_cost_per_1k=0.001,
            output_cost_per_1k=0.002,
            external_id="vendor/agent-model",
            display_name="Agent Model",
        ),
        api_key="secret",
        base_url="https://example.test/v1",
        provider_type="openrouter",
        model_id="vendor/agent-model",
        agent_turn=turn,
    )
    review = AgentCompletionReview(
        status="blocked",
        display_text=None,
        safe_response="The response was blocked by policy.",
        reason_code="citation_validation_failed",
        guardrail_decisions=(),
        citation_verification=None,
    )
    finalize_run = AsyncMock()

    async def fake_log_usage(*args, **kwargs):
        del args, kwargs
        return 42

    with ExitStack() as _stack:
        _stack.enter_context(patch.object(proxy_service, "AsyncSessionLocal", return_value=context))
        _stack.enter_context(patch.object(chat_turn_context, "AsyncSessionLocal", return_value=context))
        _stack.enter_context(patch.object(turn_settlement, "AsyncSessionLocal", return_value=context))
        mark_started = _stack.enter_context(patch.object(chat_turn_context, "mark_agent_run_started", AsyncMock()))
        _stack.enter_context(
            patch.object(
                chat_turn_context, "resolve_resource_access_subject", AsyncMock(return_value=SimpleNamespace(user_id=1))
            )
        )
        _stack.enter_context(
            patch.object(
                chat_turn_context,
                "augment_messages_with_tools",
                AsyncMock(side_effect=lambda _db, messages, _tools, **_kwargs: messages),
            )
        )
        _stack.enter_context(
            patch.object(
                chat_turn_context,
                "augment_messages_with_profile",
                AsyncMock(side_effect=lambda _db, messages, **_kwargs: messages),
            )
        )
        _stack.enter_context(
            patch.object(
                chat_turn_context,
                "augment_messages_with_memory",
                AsyncMock(side_effect=lambda _db, messages, **_kwargs: messages),
            )
        )
        _stack.enter_context(
            patch.object(
                proxy_service,
                "apply_prompt_cache_breakpoints",
                side_effect=lambda messages: messages,
            )
        )
        _stack.enter_context(
            patch.object(chat_turn_context, "apply_prompt_cache_breakpoints", side_effect=lambda messages: messages)
        )
        _stack.enter_context(patch.object(proxy_service, "acompletion", side_effect=fake_acompletion))
        _stack.enter_context(patch.object(proxy_service, "_usage_from_chunk", return_value=(10, 2, 0)))
        _stack.enter_context(
            patch.object(
                proxy_service,
                "_usage_from_stream_wrapper",
                return_value=(0, 0, 0),
            )
        )
        _stack.enter_context(patch.object(proxy_service, "_compute_token_cost_usd", return_value=0.0))
        finalize_completion = _stack.enter_context(
            patch.object(
                proxy_service,
                "finalize_agent_completion",
                AsyncMock(return_value=review),
            )
        )
        _stack.enter_context(patch.object(chat_turn_context, "finalize_agent_run", finalize_run))
        _stack.enter_context(patch.object(turn_settlement, "finalize_agent_run", finalize_run))
        _stack.enter_context(patch.object(proxy_service, "log_usage", side_effect=fake_log_usage))
        _stack.enter_context(patch.object(turn_settlement, "log_usage", side_effect=fake_log_usage))
        output = [
            chunk
            async for chunk in proxy_service.stream_chat(
                _request(),
                {
                    "messages": [{"role": "user", "content": "Untrusted input"}],
                    "_agent_run_id": turn.run_id,
                },
                user_id=1,
                username="user",
                source="gateway",
                skip_budget=True,
                resolved=resolved,
            )
        ]

    text = b"".join(output).decode()
    assert "unverified provider output" not in text
    assert "The response was blocked by policy." in text
    assert '"agent_status":"blocked"' in text
    assert '"completion_reason_code":"citation_validation_failed"' in text
    assert completion_kwargs["messages"] == list(prompt.messages)
    assert completion_kwargs["max_tokens"] == 321
    assert completion_kwargs["temperature"] == 0.25
    mark_started.assert_awaited_once_with(db, turn.run_id)
    finalize_completion.assert_awaited_once()
    assert finalize_completion.await_args.kwargs["output_text"] == "unverified provider output"
    finalize_run.assert_awaited_once()
    assert finalize_run.await_args.kwargs["status"] == "blocked"
    assert finalize_run.await_args.kwargs["request_log_id"] == 42
    assert finalize_run.await_args.kwargs["output_displayed"] is True


async def test_agent_stream_is_buffered_until_post_generation_review():
    await _test_agent_stream_is_buffered_until_post_generation_review()
