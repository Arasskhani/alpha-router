"""Knowledge-index embeddings are metered - as the platform's own spend.

Every embedding call the index builder made cost money and none of it reached
the usage ledger: the metering helpers require a user or an API key, and a
build has neither - it spans every document in a release, on behalf of
everyone the base is shared with. The plan's options were the base's owner,
a synthetic platform subject, or a split by document owner; this is the
platform subject. It makes the spend visible without inventing an attribution
the data cannot support, and it holds nobody's budget.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.models.budget import BudgetPlan, PlanAssignment
from app.models.budget_reservation import BudgetReservation
from app.models.connection import Connection
from app.models.cost_accounting import UsageOperation
from app.models.logging import RequestLog
from app.models.model_catalog import AIModel
from app.services import knowledge_embedding_service as embeddings
from app.services import metered_usage_service
from app.services.knowledge_embedding_service import (
    PLATFORM_INDEXING_SUBJECT,
    CatalogKnowledgeEmbeddingBackend,
    EmbeddingMeteringSubject,
    metered_embeddings,
)
from app.services.secret_crypto import encrypt_secret
from app.services.usage_accounting_service import COST_SOURCE_CATALOG, SUBJECT_PLATFORM

DIMS = 4
PROMPT_RATE = 0.00000002  # USD per input token, as a catalog snapshot states it


@pytest.fixture
async def embedding_model(db_session) -> AIModel:
    connection = Connection(
        name="openai", provider_type="openai", api_key_encrypted=encrypt_secret("sk-test"), is_active=True
    )
    db_session.add(connection)
    await db_session.flush()
    model = AIModel(
        connection_id=connection.id,
        external_id="text-embedding-3-small",
        provider_type="openai",
        is_enabled=True,
        admin_disabled=False,
        pricing_raw=json.dumps({"pricing": {"prompt": str(PROMPT_RATE)}}),
    )
    db_session.add(model)
    await db_session.commit()
    return model


@pytest.fixture
def ledger(monkeypatch, session_factory):
    """Metering opens its own sessions; point them at the test database."""
    monkeypatch.setattr(metered_usage_service, "AsyncSessionLocal", session_factory)


def _provider_response(count: int, *, prompt_tokens: int) -> SimpleNamespace:
    """The shape LiteLLM hands back for an embedding call: an object with a
    ``usage`` attribute and ``data`` list, and ``model_dump()`` for the same."""
    payload = {
        "data": [{"index": i, "embedding": [0.1] * DIMS} for i in range(count)],
        "usage": {"prompt_tokens": prompt_tokens, "total_tokens": prompt_tokens},
    }
    return SimpleNamespace(
        data=payload["data"],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, total_tokens=prompt_tokens),
        model_dump=lambda: payload,
    )


@pytest.fixture
def provider(monkeypatch):
    calls: list[dict] = []

    async def fake_aembedding(**kwargs):
        calls.append(kwargs)
        return _provider_response(len(kwargs["input"]), prompt_tokens=37)

    monkeypatch.setattr(embeddings, "aembedding", fake_aembedding)
    return calls


async def _embed(db, texts: list[str]) -> list[list[float]]:
    return await CatalogKnowledgeEmbeddingBackend().embed(
        db, provider="openai", model="text-embedding-3-small", dimensions=DIMS, texts=texts
    )


async def test_an_index_build_writes_one_priced_row_against_the_platform(db_session, embedding_model, ledger, provider):
    with metered_embeddings(PLATFORM_INDEXING_SUBJECT):
        vectors = await _embed(db_session, ["alpha", "beta", "gamma"])
    assert len(vectors) == 3

    log = (await db_session.execute(select(RequestLog))).scalars().one()
    assert log.username == metered_usage_service.PLATFORM_USERNAME
    assert log.user_id is None and log.alpha_router_api_key_id is None
    assert log.source == "knowledge" and log.client_app == "knowledge_index"
    assert log.model_id == "text-embedding-3-small"
    assert log.prompt_tokens == 37
    # Priced from the catalog snapshot, not left as an unpriced row.
    assert log.total_cost_usd == pytest.approx(37 * PROMPT_RATE)
    assert log.cost_source == COST_SOURCE_CATALOG

    operation = (await db_session.execute(select(UsageOperation))).scalars().one()
    assert operation.subject_type == SUBJECT_PLATFORM
    assert operation.subject_id is None
    assert operation.operation_type == "knowledge_index_embed"


async def test_the_platform_holds_nobodys_budget(db_session, embedding_model, ledger, provider):
    with metered_embeddings(PLATFORM_INDEXING_SUBJECT):
        await _embed(db_session, ["alpha"])
    assert (await db_session.execute(select(func.count()).select_from(BudgetReservation))).scalar_one() == 0


async def test_without_a_subject_in_scope_nothing_is_recorded(db_session, embedding_model, ledger, provider):
    """Retrieval and memory share this backend and set no subject yet; they
    must keep behaving exactly as before - embedding, recording nothing."""
    await _embed(db_session, ["alpha"])
    assert provider, "the provider was still called"
    assert (await db_session.execute(select(func.count()).select_from(RequestLog))).scalar_one() == 0


async def test_the_subject_does_not_leak_out_of_the_block(db_session, embedding_model, ledger, provider):
    with metered_embeddings(PLATFORM_INDEXING_SUBJECT):
        pass
    assert embeddings.current_metering_subject() is None
    await _embed(db_session, ["alpha"])
    assert (await db_session.execute(select(func.count()).select_from(RequestLog))).scalar_one() == 0


async def test_a_failed_provider_call_is_recorded_as_failed_and_still_raised(
    db_session, embedding_model, ledger, monkeypatch
):
    async def boom(**kwargs):
        raise RuntimeError("upstream 503")

    monkeypatch.setattr(embeddings, "aembedding", boom)
    with metered_embeddings(PLATFORM_INDEXING_SUBJECT), pytest.raises(RuntimeError):
        await _embed(db_session, ["alpha"])

    log = (await db_session.execute(select(RequestLog))).scalars().one()
    assert log.success is False
    assert "upstream 503" in (log.error_message or "")
    assert log.username == metered_usage_service.PLATFORM_USERNAME


async def test_a_user_subject_is_metered_against_that_user(db_session, user, embedding_model, ledger, provider):
    """The same block can name a person - retrieval will, once it is wired."""
    plan = BudgetPlan(name="ten", monthly_budget_usd=10.0)
    db_session.add(plan)
    await db_session.flush()
    db_session.add(PlanAssignment(user_id=user.id, plan_id=plan.id))
    user.monthly_budget_usd = 10.0
    await db_session.commit()
    subject = EmbeddingMeteringSubject(
        operation_name="knowledge_query_embed", source="knowledge", client_app="chat", user_id=user.id
    )
    with metered_embeddings(subject):
        await _embed(db_session, ["what is the policy"])
    log = (await db_session.execute(select(RequestLog))).scalars().one()
    assert log.user_id == user.id
    assert log.username == user.username


async def test_a_platform_call_cannot_also_name_a_person():
    with pytest.raises(ValueError):
        await metered_usage_service.start_metered_usage(
            user_id=1,
            provider_type="openai",
            service_type="embeddings",
            operation_name="x",
            model_id="m",
            platform=True,
        )


async def test_an_index_build_embeds_under_the_platform_subject():
    """The builder is what makes the call; the metering has to be there, not
    only available. A fake backend records which subject was in scope each
    time it was asked to embed."""
    from qdrant_client import AsyncQdrantClient

    from app.services.knowledge_index_service import build_and_activate_knowledge_index
    from app.services.qdrant_service import QdrantVectorService
    from tests.test_knowledge_retrieval import FakeEmbeddingBackend, _seed_index, _session_factory

    class RecordingBackend(FakeEmbeddingBackend):
        subjects: list[EmbeddingMeteringSubject | None] = []

        async def embed(self, db, **kwargs):
            self.subjects.append(embeddings.current_metering_subject())
            return await super().embed(db, **kwargs)

    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            seeded = await _seed_index(db)
            await build_and_activate_knowledge_index(
                db,
                index_version_id=seeded["index_version"].id,
                published_by_user_id=seeded["finance"].id,
                qdrant=QdrantVectorService(AsyncQdrantClient(location=":memory:")),
                embedding_backend=RecordingBackend(),
            )
    finally:
        await engine.dispose()
    assert RecordingBackend.subjects, "the build embedded nothing"
    assert all(subject is PLATFORM_INDEXING_SUBJECT for subject in RecordingBackend.subjects)
    # And the block closed behind it.
    assert embeddings.current_metering_subject() is None
