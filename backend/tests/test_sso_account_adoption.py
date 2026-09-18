"""A directory login must not take over an account bound to someone else.

``_upsert_directory_user`` matches on ``external_id`` first and falls back to the
username. The cross-provider case was refused; the same-provider case was not,
and there was no check that the row it adopted was unbound.

So SSO principal B presenting ``username = A`` was mapped onto A's row - A's
roles, budget, chats and group memberships - and the ``external_id`` write two
lines later replaced A's stable identity with B's, locking A out for good.

The username claim is not always the IdP's to guarantee. The OIDC fallback chain
ended at ``email``, which several IdP configurations let the account holder edit.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.auth import _upsert_directory_user
from app.models.user import User


async def _directory_user(db_session, *, username: str, external_id: str | None) -> User:
    row = User(
        username=username,
        auth_provider="saml",
        external_id=external_id,
        is_active=True,
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


async def test_a_second_principal_cannot_adopt_a_bound_account(db_session):
    victim = await _directory_user(db_session, username="alice", external_id="ID-ALICE")

    with pytest.raises(HTTPException) as exc:
        await _upsert_directory_user(
            db_session,
            {"username": "alice", "external_id": "ID-MALLORY"},
            "saml",
        )
    assert exc.value.status_code == 409
    assert "takeover" in str(exc.value.detail).lower()

    await db_session.refresh(victim)
    assert victim.external_id == "ID-ALICE", "the victim's directory identity was overwritten"


async def test_an_unbound_row_is_still_backfilled(db_session):
    """Adoption by username exists for rows that predate external_id."""

    legacy = await _directory_user(db_session, username="bob", external_id=None)

    user = await _upsert_directory_user(
        db_session,
        {"username": "bob", "external_id": "ID-BOB"},
        "saml",
    )
    assert user.id == legacy.id
    assert user.external_id == "ID-BOB"


async def test_the_same_principal_signing_in_again_is_fine(db_session):
    existing = await _directory_user(db_session, username="carol", external_id="ID-CAROL")

    user = await _upsert_directory_user(
        db_session,
        {"username": "carol", "external_id": "ID-CAROL"},
        "saml",
    )
    assert user.id == existing.id


async def test_cross_provider_takeover_is_still_refused(db_session):
    local = User(username="dave", auth_provider="local", is_active=True)
    db_session.add(local)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await _upsert_directory_user(db_session, {"username": "dave", "external_id": "ID-DAVE"}, "saml")
    assert exc.value.status_code == 409


def test_the_oidc_username_chain_does_not_fall_back_to_email():
    """An address the account holder can edit must not choose the username."""

    import inspect

    from app.services import oidc_client

    source = inspect.getsource(oidc_client)
    assert 'pick(username_claim, "preferred_username", "sub")' in source
    assert 'pick(username_claim, "preferred_username", "email", "sub")' not in source
