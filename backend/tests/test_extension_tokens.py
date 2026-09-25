"""The browser extension's tokens: connect codes, sessions, rotation, authentication."""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import Update, select, update

from app.models.extension import ExtensionSession
from app.models.security import SecurityAuditEvent
from app.models.user import User
from app.services import extension_tokens as tokens
from app.services.extension_tokens import (
    ACCESS_TOKEN_PREFIX,
    REFRESH_TOKEN_PREFIX,
    ExtensionTokenError,
    authenticate,
    clean_device_name,
    consume_auth_code,
    create_auth_code,
    create_session,
    is_extension_access_token,
    is_valid_challenge,
    list_sessions,
    needs_touch,
    next_pair,
    pkce_challenge,
    redeem_auth_code,
    refresh_session,
    revoke_session,
    token_hash,
    touch_session,
    verify_pkce,
)

# RFC 7636, appendix B.
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
REDIRECT = "chrome-extension://abcdefghijklmnopabcdefghijklmnop/connected.html"
#: The extension's name for one refresh, and someone else's.
ATTEMPT = "attempt-of-the-extension-01"
OTHER_ATTEMPT = "attempt-of-someone-else-02"


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.ttl: dict[str, int | None] = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value
        self.ttl[key] = ex

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        return self.store.pop(key, None) is not None

    def pipeline(self):
        outer = self

        class _Pipe:
            def __init__(self):
                self._ops = []

            def get(self, key):
                self._ops.append(("get", key))

            def delete(self, key):
                self._ops.append(("delete", key))

            async def execute(self):
                return [await (outer.get(key) if op == "get" else outer.delete(key)) for op, key in self._ops]

        return _Pipe()


class BrokenRedis:
    async def set(self, *args, **kwargs):
        raise ConnectionError("redis down")

    def pipeline(self):
        raise ConnectionError("redis down")


class Clock:
    """A frozen ``_now`` for the service, moved by hand."""

    def __init__(self):
        self.value = datetime.datetime(2026, 9, 25, 12, 0, 0)

    def __call__(self) -> datetime.datetime:
        return self.value

    def advance(self, **delta) -> None:
        self.value += datetime.timedelta(**delta)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, session_factory):
    monkeypatch.setattr(tokens, "AsyncSessionLocal", session_factory)
    tokens._mem_codes.clear()
    yield
    tokens._mem_codes.clear()


@pytest.fixture
def redis_store(monkeypatch) -> FakeRedis:
    fake = FakeRedis()
    monkeypatch.setattr(tokens, "get_redis", lambda: fake)
    return fake


@pytest.fixture
def redis_down(monkeypatch) -> None:
    monkeypatch.setattr(tokens, "get_redis", BrokenRedis)


@pytest.fixture
def clock(monkeypatch) -> Clock:
    frozen = Clock()
    monkeypatch.setattr(tokens, "_now", frozen)
    return frozen


async def _connect(db, user, **kwargs) -> tokens.TokenPair:
    pair = await create_session(
        db,
        user=user,
        device_name=kwargs.get("device_name", "Chrome on Windows"),
        user_agent=kwargs.get("user_agent", "Mozilla/5.0"),
        ip=kwargs.get("ip", "10.0.0.5"),
    )
    await db.commit()
    return pair


async def _row(session_factory, session_id: str) -> ExtensionSession:
    async with session_factory() as fresh:
        return (await fresh.execute(select(ExtensionSession).where(ExtensionSession.id == session_id))).scalar_one()


def _columns(row: ExtensionSession) -> dict[str, object]:
    return {column.key: getattr(row, column.key) for column in ExtensionSession.__table__.columns}


class _NoCommit:
    """The request's session, which the service must leave for the request to commit."""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def commit(self):
        raise AssertionError("the request's session was committed")


class _RaceBeforeUpdate:
    """The request's session; just before its first UPDATE, ``interloper`` runs in another session."""

    def __init__(self, inner, interloper):
        self._inner = inner
        self._interloper = interloper
        self._raced = False

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def execute(self, statement, *args, **kwargs):
        if isinstance(statement, Update) and not self._raced:
            self._raced = True
            await self._interloper()
        return await self._inner.execute(statement, *args, **kwargs)


async def _grant_error(awaitable) -> ExtensionTokenError:
    with pytest.raises(ExtensionTokenError) as caught:
        await awaitable
    return caught.value


class TestPkce:
    def test_rfc_7636_vector(self):
        assert pkce_challenge(VERIFIER) == CHALLENGE
        assert verify_pkce(VERIFIER, CHALLENGE)

    @pytest.mark.parametrize(
        "verifier",
        [
            None,
            "",
            VERIFIER[:-1] + "A",  # another verifier
            "a" * 42,  # too short
            "a" * 129,  # too long
            VERIFIER[:-1] + "+",  # not an unreserved character
        ],
    )
    def test_wrong_verifiers_fail(self, verifier):
        assert not verify_pkce(verifier, CHALLENGE)

    def test_the_longest_verifier_is_accepted(self):
        verifier = "~" * 128
        assert verify_pkce(verifier, pkce_challenge(verifier))

    @pytest.mark.parametrize("challenge", [None, "", CHALLENGE[:-1], CHALLENGE + "=", CHALLENGE[:-1] + "+"])
    def test_malformed_challenges_are_refused(self, challenge):
        assert not is_valid_challenge(challenge)

    def test_a_proper_challenge_is_accepted(self):
        assert is_valid_challenge(CHALLENGE)


class TestDeviceName:
    def test_control_characters_and_runs_of_space_go(self):
        assert clean_device_name("  Chrome\u0000 on\n\tWindows\u202e ") == "Chrome on Windows"

    def test_it_is_capped(self):
        assert len(clean_device_name("x" * 500)) == 64

    def test_nothing_gives_an_empty_name(self):
        assert clean_device_name(None) == ""


class TestCodes:
    async def test_a_code_is_used_once(self, user, redis_store):
        code = await create_auth_code(user=user, redirect_uri=REDIRECT, code_challenge=CHALLENGE)
        payload = await consume_auth_code(code)
        assert payload == {
            "user_id": user.id,
            "token_version": 0,
            "redirect_uri": REDIRECT,
            "code_challenge": CHALLENGE,
        }
        assert await consume_auth_code(code) is None

    async def test_the_store_never_holds_the_code(self, user, redis_store):
        code = await create_auth_code(user=user, redirect_uri=REDIRECT, code_challenge=CHALLENGE)
        (key,) = redis_store.store
        assert key == "ext:code:" + hashlib.sha256(code.encode()).hexdigest()
        assert code not in key and code not in redis_store.store[key]
        assert redis_store.ttl[key] == 120

    async def test_unknown_and_empty_codes_are_nothing(self, redis_store):
        assert await consume_auth_code("no-such-code") is None
        assert await consume_auth_code("") is None
        assert await consume_auth_code(None) is None

    async def test_a_payload_that_is_not_an_object_is_nothing(self, redis_store):
        redis_store.store["ext:code:" + token_hash("odd")] = "[1, 2]"
        redis_store.store["ext:code:" + token_hash("broken")] = "{not json"
        assert await consume_auth_code("odd") is None
        assert await consume_auth_code("broken") is None

    async def test_redis_down_falls_back_to_memory_once(self, user, redis_down):
        code = await create_auth_code(user=user, redirect_uri=REDIRECT, code_challenge=CHALLENGE)
        assert code not in json.dumps(list(tokens._mem_codes))
        assert (await consume_auth_code(code))["user_id"] == user.id
        assert await consume_auth_code(code) is None

    async def test_memory_codes_expire(self, user, redis_down, monkeypatch):
        code = await create_auth_code(user=user, redirect_uri=REDIRECT, code_challenge=CHALLENGE)
        real = tokens._monotonic
        monkeypatch.setattr(tokens, "_monotonic", lambda: real() + 121)
        assert await consume_auth_code(code) is None

    async def test_a_code_made_during_an_outage_still_works_when_redis_is_back(self, user, monkeypatch):
        monkeypatch.setattr(tokens, "get_redis", BrokenRedis)
        code = await create_auth_code(user=user, redirect_uri=REDIRECT, code_challenge=CHALLENGE)
        monkeypatch.setattr(tokens, "get_redis", FakeRedis)
        assert (await consume_auth_code(code))["redirect_uri"] == REDIRECT


class TestRedeem:
    async def _code(self, user, **overrides) -> str:
        return await create_auth_code(
            user=user,
            redirect_uri=overrides.get("redirect_uri", REDIRECT),
            code_challenge=overrides.get("code_challenge", CHALLENGE),
        )

    async def test_the_right_verifier_and_address_give_the_user(self, db_session, user, redis_store):
        code = await self._code(user)
        redeemed = await redeem_auth_code(db_session, code=code, code_verifier=VERIFIER, redirect_uri=REDIRECT)
        assert redeemed.id == user.id

    async def test_a_wrong_verifier_spends_the_code(self, db_session, user, redis_store):
        code = await self._code(user)
        wrong = "b" * 43
        error = await _grant_error(redeem_auth_code(db_session, code=code, code_verifier=wrong, redirect_uri=REDIRECT))
        assert error.code == "invalid_grant"
        again = await _grant_error(
            redeem_auth_code(db_session, code=code, code_verifier=VERIFIER, redirect_uri=REDIRECT)
        )
        assert again.code == "invalid_grant"

    @pytest.mark.parametrize(
        "redirect_uri",
        [None, "", "chrome-extension://ponmlkjihgfedcbaponmlkjihgfedcba/connected.html", REDIRECT + "?x=1"],
    )
    async def test_another_address_is_refused(self, db_session, user, redis_store, redirect_uri):
        code = await self._code(user)
        error = await _grant_error(
            redeem_auth_code(db_session, code=code, code_verifier=VERIFIER, redirect_uri=redirect_uri)
        )
        assert error.code == "invalid_grant"

    async def test_an_unknown_code_is_refused(self, db_session, redis_store):
        error = await _grant_error(
            redeem_auth_code(db_session, code="nope", code_verifier=VERIFIER, redirect_uri=REDIRECT)
        )
        assert error.code == "invalid_grant"

    async def test_an_expired_code_is_refused(self, db_session, user, redis_down, monkeypatch):
        code = await self._code(user)
        real = tokens._monotonic
        monkeypatch.setattr(tokens, "_monotonic", lambda: real() + 121)
        error = await _grant_error(
            redeem_auth_code(db_session, code=code, code_verifier=VERIFIER, redirect_uri=REDIRECT)
        )
        assert error.code == "invalid_grant"

    @pytest.mark.parametrize("change", ["inactive", "deleted", "signed_out"])
    async def test_an_account_that_changed_since_allowing_is_refused(self, db_session, user, redis_store, change):
        code = await self._code(user)
        if change == "inactive":
            user.is_active = False
        elif change == "deleted":
            user.deleted_at = datetime.datetime(2026, 9, 25)
        else:
            user.token_version = 1
        await db_session.commit()
        error = await _grant_error(
            redeem_auth_code(db_session, code=code, code_verifier=VERIFIER, redirect_uri=REDIRECT)
        )
        assert error.code == "invalid_grant"


class TestCreateSession:
    async def test_only_hashes_are_stored(self, db_session, session_factory, user, clock):
        pair = await _connect(db_session, user)
        assert pair.access_token.startswith(ACCESS_TOKEN_PREFIX)
        assert pair.refresh_token.startswith(REFRESH_TOKEN_PREFIX)
        assert pair.expires_in == 3600
        row = await _row(session_factory, pair.session_id)
        assert row.access_token_hash == hashlib.sha256(pair.access_token.encode()).hexdigest()
        assert row.refresh_token_hash == hashlib.sha256(pair.refresh_token.encode()).hexdigest()
        stored = " ".join(str(value) for value in _columns(row).values())
        for secret, prefix in ((pair.access_token, ACCESS_TOKEN_PREFIX), (pair.refresh_token, REFRESH_TOKEN_PREFIX)):
            assert secret[len(prefix) :] not in stored

    async def test_lifetimes_and_details(self, db_session, session_factory, user, clock):
        pair = await _connect(db_session, user, device_name="Edge\n on  Mac", user_agent="U" * 400, ip="2001:db8::1")
        row = await _row(session_factory, pair.session_id)
        now = clock.value
        assert row.access_expires_at == now + datetime.timedelta(hours=1)
        assert row.refresh_expires_at == now + datetime.timedelta(days=30)
        assert row.absolute_expires_at == now + datetime.timedelta(days=180)
        assert row.created_at == row.last_used_at == now
        assert row.token_version == 0
        assert row.device_name == "Edge on Mac"
        assert len(row.user_agent) == 255
        assert row.last_ip == "2001:db8::1"
        assert row.revoked_at is None

    async def test_every_pair_is_new(self, db_session, user):
        first = await _connect(db_session, user)
        second = await _connect(db_session, user)
        assert len({first.access_token, first.refresh_token, second.access_token, second.refresh_token}) == 4
        assert first.session_id != second.session_id

    def test_access_tokens_are_told_apart(self):
        assert is_extension_access_token(ACCESS_TOKEN_PREFIX + "x")
        assert not is_extension_access_token(REFRESH_TOKEN_PREFIX + "x")
        assert not is_extension_access_token("eyJhbGciOiJIUzI1NiJ9.e30.sig")
        assert not is_extension_access_token("")
        assert not is_extension_access_token(None)


class TestAuthenticate:
    async def test_a_live_token_gives_the_session_and_user(self, db_session, user, clock):
        pair = await _connect(db_session, user)
        found = await authenticate(db_session, pair.access_token)
        assert found.session.id == pair.session_id
        assert found.user.id == user.id

    async def test_unknown_token(self, db_session, user):
        error = await _grant_error(authenticate(db_session, ACCESS_TOKEN_PREFIX + "unknown"))
        assert error.code == "invalid_token"

    async def test_an_hour_later_it_has_expired(self, db_session, user, clock):
        pair = await _connect(db_session, user)
        clock.advance(minutes=59, seconds=59)
        await authenticate(db_session, pair.access_token)
        clock.advance(seconds=1)
        assert (await _grant_error(authenticate(db_session, pair.access_token))).code == "expired"

    async def test_past_the_absolute_limit_it_is_over(self, db_session, user, clock):
        pair = await _connect(db_session, user)
        await db_session.execute(
            update(ExtensionSession)
            .where(ExtensionSession.id == pair.session_id)
            .values(absolute_expires_at=clock.value)
        )
        await db_session.commit()
        assert (await _grant_error(authenticate(db_session, pair.access_token))).code == "revoked"

    async def test_a_revoked_session(self, db_session, user, clock):
        pair = await _connect(db_session, user)
        assert await revoke_session(db_session, pair.session_id, reason=tokens.REVOKED_BY_USER)
        await db_session.commit()
        assert (await _grant_error(authenticate(db_session, pair.access_token))).code == "revoked"

    @pytest.mark.parametrize("change", ["signed_out", "deleted"])
    async def test_sign_out_everywhere_or_deletion_ends_it(self, db_session, session_factory, user, clock, change):
        pair = await _connect(db_session, user)
        if change == "signed_out":
            user.token_version = 1
        else:
            user.deleted_at = clock.value
        await db_session.commit()
        assert (await _grant_error(authenticate(db_session, pair.access_token))).code == "revoked"
        row = await _row(session_factory, pair.session_id)
        assert row.revoked_at == clock.value
        assert row.revoked_reason == "token_version"

    async def test_the_revocation_does_not_commit_the_request(self, db_session, session_factory, user, clock):
        pair = await _connect(db_session, user)
        user.token_version = 1
        await db_session.commit()
        await _grant_error(authenticate(_NoCommit(db_session), pair.access_token))
        assert (await _row(session_factory, pair.session_id)).revoked_reason == "token_version"


class TestOwnTransactions:
    """SQLite runs these tests on one shared connection, so reading "from another
    session" cannot show that a write was committed; PostgreSQL can, and this
    checks the commit itself on both."""

    async def test_a_revocation_found_while_authenticating_is_committed(
        self, db_session, session_factory, user, clock, monkeypatch
    ):
        commits: list[str] = []

        class _CountingFactory:
            def __init__(self):
                self._inner = session_factory()

            async def __aenter__(self):
                session = await self._inner.__aenter__()
                real_commit = session.commit

                async def commit():
                    commits.append("commit")
                    await real_commit()

                session.commit = commit
                return session

            async def __aexit__(self, *exc):
                return await self._inner.__aexit__(*exc)

        pair = await _connect(db_session, user)
        user.token_version = 1
        await db_session.commit()
        monkeypatch.setattr(tokens, "AsyncSessionLocal", _CountingFactory)
        await _grant_error(authenticate(_NoCommit(db_session), pair.access_token))
        assert commits == ["commit"]


class TestRefresh:
    async def test_rotation_gives_a_new_pair_and_retires_the_old_one(self, db_session, session_factory, user, clock):
        pair = await _connect(db_session, user)
        clock.advance(minutes=50)
        new = await refresh_session(db_session, pair.refresh_token)
        await db_session.commit()
        assert new.session_id == pair.session_id
        assert new.expires_in == 3600
        assert {new.access_token, new.refresh_token}.isdisjoint({pair.access_token, pair.refresh_token})
        assert (await _grant_error(authenticate(db_session, pair.access_token))).code == "invalid_token"
        assert (await authenticate(db_session, new.access_token)).session.id == pair.session_id
        row = await _row(session_factory, pair.session_id)
        assert row.prior_refresh_token_hash == token_hash(pair.refresh_token)
        assert row.prior_refresh_valid_until == clock.value + tokens.REFRESH_GRACE
        assert row.access_expires_at == clock.value + datetime.timedelta(hours=1)
        assert row.refresh_expires_at == clock.value + datetime.timedelta(days=30)

    def test_a_token_always_turns_into_the_same_pair(self, monkeypatch):
        first = next_pair(REFRESH_TOKEN_PREFIX + "one")
        assert next_pair(REFRESH_TOKEN_PREFIX + "one") == first
        assert next_pair(REFRESH_TOKEN_PREFIX + "two") != first
        assert first[0].startswith(ACCESS_TOKEN_PREFIX) and first[1].startswith(REFRESH_TOKEN_PREFIX)
        assert len(first[0]) - len(ACCESS_TOKEN_PREFIX) == 43
        monkeypatch.setattr(tokens, "get_settings", lambda: SimpleNamespace(secret_key="another-secret"))
        assert next_pair(REFRESH_TOKEN_PREFIX + "one") != first

    def test_the_access_token_depends_on_the_attempt_and_the_refresh_token_does_not(self):
        token = REFRESH_TOKEN_PREFIX + "one"
        mine = next_pair(token, ATTEMPT)
        assert next_pair(token, ATTEMPT) == mine
        theirs = next_pair(token, OTHER_ATTEMPT)
        without = next_pair(token)
        assert len({mine[0], theirs[0], without[0]}) == 3
        assert mine[0].startswith(ACCESS_TOKEN_PREFIX) and len(mine[0]) - len(ACCESS_TOKEN_PREFIX) == 43
        # One chain of refresh tokens, whichever attempt spent each of them.
        assert mine[1] == theirs[1] == without[1]

    @pytest.mark.parametrize("attempt", [ATTEMPT, None])
    async def test_a_retry_within_the_grace_gets_the_same_pair_and_writes_nothing(
        self, db_session, session_factory, user, clock, attempt
    ):
        pair = await _connect(db_session, user)
        new = await refresh_session(db_session, pair.refresh_token, attempt=attempt)
        await db_session.commit()
        before = _columns(await _row(session_factory, pair.session_id))
        clock.value += tokens.REFRESH_GRACE
        again = await refresh_session(db_session, pair.refresh_token, attempt=attempt)
        await db_session.commit()
        assert again.access_token == new.access_token
        assert again.refresh_token == new.refresh_token
        assert again.expires_in == 3600 - int(tokens.REFRESH_GRACE.total_seconds())
        assert _columns(await _row(session_factory, pair.session_id)) == before

    @pytest.mark.parametrize(("extension", "copy"), [(ATTEMPT, None), (ATTEMPT, OTHER_ATTEMPT), (None, OTHER_ATTEMPT)])
    async def test_a_copy_presented_within_the_grace_ends_the_session_and_is_audited(
        self, db_session, session_factory, user, clock, extension, copy
    ):
        # Whoever else holds the tokens sees their access token stop working
        # when the extension refreshes, and presents the replaced refresh
        # token at once, as a different attempt or none.
        pair = await _connect(db_session, user)
        new = await refresh_session(db_session, pair.refresh_token, attempt=extension)
        await db_session.commit()
        clock.advance(seconds=5)
        error = await _grant_error(refresh_session(db_session, pair.refresh_token, attempt=copy, ip="203.0.113.7"))
        assert error.code == "invalid_grant"
        assert (await _row(session_factory, pair.session_id)).revoked_reason == "refresh_reuse"
        async with session_factory() as fresh:
            (event,) = (await fresh.execute(select(SecurityAuditEvent))).scalars().all()
        assert (event.action, event.actor_ip, event.resource_id) == (
            "extension_session_revoked",
            "203.0.113.7",
            pair.session_id,
        )
        # Whoever holds the new pair is out too: the copy could as well have come first.
        assert (await _grant_error(authenticate(db_session, new.access_token))).code == "revoked"
        assert (await _grant_error(refresh_session(db_session, new.refresh_token))).code == "invalid_grant"

    async def test_after_the_grace_the_old_token_ends_the_session(self, db_session, session_factory, user, clock):
        pair = await _connect(db_session, user)
        new = await refresh_session(db_session, pair.refresh_token)
        await db_session.commit()
        clock.value += tokens.REFRESH_GRACE + datetime.timedelta(seconds=1)
        error = await _grant_error(refresh_session(db_session, pair.refresh_token))
        assert error.code == "invalid_grant"
        row = await _row(session_factory, pair.session_id)
        assert row.revoked_reason == "refresh_reuse"
        # Whoever holds the new pair is out too: it may be the thief.
        assert (await _grant_error(authenticate(db_session, new.access_token))).code == "revoked"
        assert (await _grant_error(refresh_session(db_session, new.refresh_token))).code == "invalid_grant"

    async def test_the_grace_starts_when_the_token_is_replaced_not_when_the_request_began(
        self, db_session, session_factory, user, clock
    ):
        pair = await _connect(db_session, user)

        class _SlowPool:
            """The request's session, whose first statement waits longer than the grace for a connection."""

            def __init__(self, inner):
                self._inner = inner
                self._waited = False

            def __getattr__(self, name):
                return getattr(self._inner, name)

            async def execute(self, statement, *args, **kwargs):
                if not self._waited:
                    self._waited = True
                    clock.value += tokens.REFRESH_GRACE + datetime.timedelta(seconds=10)
                return await self._inner.execute(statement, *args, **kwargs)

        new = await refresh_session(_SlowPool(db_session), pair.refresh_token)
        await db_session.commit()
        clock.advance(seconds=1)
        retried = await refresh_session(db_session, pair.refresh_token)
        await db_session.commit()
        assert retried.refresh_token == new.refresh_token
        assert (await _row(session_factory, pair.session_id)).revoked_at is None

    @pytest.mark.parametrize("rotations", [2, 5])
    async def test_any_older_token_ends_the_session_too(self, db_session, session_factory, user, clock, rotations):
        pair = await _connect(db_session, user)
        token = pair.refresh_token
        for n in range(rotations):
            # A new attempt for each refresh, as the extension makes them: the
            # chain of refresh tokens does not depend on them.
            token = (await refresh_session(db_session, token, attempt=f"attempt-of-refresh-{n:04d}")).refresh_token
            await db_session.commit()
        error = await _grant_error(refresh_session(db_session, pair.refresh_token, ip="203.0.113.7"))
        assert error.code == "invalid_grant"
        row = await _row(session_factory, pair.session_id)
        assert row.revoked_reason == "refresh_reuse"
        async with session_factory() as fresh:
            (event,) = (await fresh.execute(select(SecurityAuditEvent))).scalars().all()
        assert (event.action, event.actor_ip, event.resource_id) == (
            "extension_session_revoked",
            "203.0.113.7",
            pair.session_id,
        )

    async def test_a_token_of_another_session_ends_only_that_one(self, db_session, session_factory, user, clock):
        mine = await _connect(db_session, user)
        other = await _connect(db_session, user)
        token = mine.refresh_token
        for _ in range(2):
            token = (await refresh_session(db_session, token)).refresh_token
            await db_session.commit()
        await _grant_error(refresh_session(db_session, mine.refresh_token))
        assert (await _row(session_factory, mine.session_id)).revoked_at is not None
        assert (await _row(session_factory, other.session_id)).revoked_at is None

    async def test_a_random_token_ends_nothing(self, db_session, session_factory, user, clock):
        pair = await _connect(db_session, user)
        await refresh_session(db_session, pair.refresh_token)
        await db_session.commit()
        assert (
            await _grant_error(refresh_session(db_session, REFRESH_TOKEN_PREFIX + "random"))
        ).code == "invalid_grant"
        assert (await _row(session_factory, pair.session_id)).revoked_at is None

    @pytest.mark.parametrize("token", [None, "", "alpha-router-ext-at-looks-like-access", REFRESH_TOKEN_PREFIX + "x"])
    async def test_unknown_tokens(self, db_session, user, token):
        assert (await _grant_error(refresh_session(db_session, token))).code == "invalid_grant"

    async def test_use_slides_the_idle_limit(self, db_session, session_factory, user, clock):
        pair = await _connect(db_session, user)
        clock.advance(days=29)
        new = await refresh_session(db_session, pair.refresh_token)
        await db_session.commit()
        assert (await _row(session_factory, pair.session_id)).refresh_expires_at == clock.value + datetime.timedelta(
            days=30
        )
        clock.advance(days=30)
        assert (await _grant_error(refresh_session(db_session, new.refresh_token))).code == "invalid_grant"

    async def test_no_use_can_pass_the_absolute_limit(self, db_session, session_factory, user, clock):
        pair = await _connect(db_session, user)
        absolute = clock.value + datetime.timedelta(days=180)
        token = pair.refresh_token
        for _ in range(6):  # 174 days of steady use
            clock.advance(days=29)
            token = (await refresh_session(db_session, token)).refresh_token
            await db_session.commit()
            assert (await _row(session_factory, pair.session_id)).refresh_expires_at <= absolute
        clock.advance(days=6)
        assert (await _grant_error(refresh_session(db_session, token))).code == "invalid_grant"

    @pytest.mark.parametrize("change", ["signed_out", "deleted"])
    async def test_sign_out_everywhere_or_deletion_ends_it(self, db_session, session_factory, user, clock, change):
        pair = await _connect(db_session, user)
        if change == "signed_out":
            user.token_version = 3
        else:
            user.deleted_at = clock.value
        await db_session.commit()
        assert (await _grant_error(refresh_session(_NoCommit(db_session), pair.refresh_token))).code == "invalid_grant"
        assert (await _row(session_factory, pair.session_id)).revoked_reason == "token_version"

    async def test_a_disabled_account_keeps_its_browsers(self, db_session, session_factory, user, clock):
        # Only the feature list and the disconnect call answer it (app.api.deps);
        # re-enabling the account brings the browser back without reconnecting.
        pair = await _connect(db_session, user)
        user.is_active = False
        await db_session.commit()
        new = await refresh_session(db_session, pair.refresh_token)
        await db_session.commit()
        assert (await authenticate(db_session, new.access_token)).user.id == user.id
        assert (await _row(session_factory, pair.session_id)).revoked_at is None

    async def test_a_revoked_session_cannot_refresh(self, db_session, user, clock):
        pair = await _connect(db_session, user)
        await revoke_session(db_session, pair.session_id, reason=tokens.REVOKED_BY_USER)
        await db_session.commit()
        assert (await _grant_error(refresh_session(db_session, pair.refresh_token))).code == "invalid_grant"

    async def test_the_grace_path_checks_the_session_too(self, db_session, session_factory, user, clock):
        pair = await _connect(db_session, user)
        await refresh_session(db_session, pair.refresh_token)
        user.token_version = 1
        await db_session.commit()
        assert (await _grant_error(refresh_session(db_session, pair.refresh_token))).code == "invalid_grant"
        assert (await _row(session_factory, pair.session_id)).revoked_reason == "token_version"

    @pytest.mark.parametrize("attempt", [ATTEMPT, None])
    async def test_a_request_that_loses_the_race_to_its_own_retry_gets_the_same_pair(
        self, db_session, session_factory, user, clock, attempt
    ):
        pair = await _connect(db_session, user)
        winner: list[tokens.TokenPair] = []

        async def retry_elsewhere():
            async with session_factory() as other:
                winner.append(await refresh_session(other, pair.refresh_token, attempt=attempt))
                await other.commit()

        racing = _RaceBeforeUpdate(db_session, retry_elsewhere)
        loser = await refresh_session(racing, pair.refresh_token, attempt=attempt)
        await db_session.commit()
        assert winner and loser == winner[0]
        # One session, still going.
        again = await refresh_session(db_session, loser.refresh_token)
        await db_session.commit()
        assert again.session_id == pair.session_id

    async def test_a_request_that_loses_the_race_to_another_attempt_ends_the_session(
        self, db_session, session_factory, user, clock
    ):
        pair = await _connect(db_session, user)
        winner: list[tokens.TokenPair] = []

        async def copy_elsewhere():
            async with session_factory() as other:
                winner.append(await refresh_session(other, pair.refresh_token, attempt=OTHER_ATTEMPT))
                await other.commit()

        racing = _RaceBeforeUpdate(db_session, copy_elsewhere)
        assert (
            await _grant_error(refresh_session(racing, pair.refresh_token, attempt=ATTEMPT))
        ).code == "invalid_grant"
        await db_session.commit()
        assert (await _row(session_factory, pair.session_id)).revoked_reason == "refresh_reuse"
        assert (await _grant_error(authenticate(db_session, winner[0].access_token))).code == "revoked"

    async def test_a_stale_request_cannot_roll_the_session_back(self, db_session, session_factory, user, clock):
        pair = await _connect(db_session, user)
        latest: list[tokens.TokenPair] = []

        async def two_rotations_elsewhere():
            async with session_factory() as other:
                second = await refresh_session(other, pair.refresh_token)
                await other.commit()
                latest.append(await refresh_session(other, second.refresh_token))
                await other.commit()

        racing = _RaceBeforeUpdate(db_session, two_rotations_elsewhere)
        assert (await _grant_error(refresh_session(racing, pair.refresh_token))).code == "invalid_grant"
        await db_session.commit()
        row = await _row(session_factory, pair.session_id)
        assert row.refresh_token_hash == token_hash(latest[0].refresh_token)
        # Its token is now two rotations old: someone else holds the chain, so it ends.
        assert row.revoked_reason == "refresh_reuse"

    async def test_a_disconnect_during_a_refresh_wins(self, db_session, session_factory, user, clock):
        pair = await _connect(db_session, user)

        async def disconnect_elsewhere():
            async with session_factory() as other:
                await revoke_session(other, pair.session_id, reason=tokens.REVOKED_BY_USER)
                await other.commit()

        racing = _RaceBeforeUpdate(db_session, disconnect_elsewhere)
        assert (await _grant_error(refresh_session(racing, pair.refresh_token))).code == "invalid_grant"
        await db_session.commit()
        row = await _row(session_factory, pair.session_id)
        assert row.revoked_reason == "user"
        assert row.refresh_token_hash == token_hash(pair.refresh_token)

    @pytest.mark.parametrize("attempt", [ATTEMPT, None])
    async def test_a_refresh_and_its_retry_at_once_cannot_fork_the_session(
        self, db_session, session_factory, user, clock, attempt
    ):
        pair = await _connect(db_session, user)

        async def one() -> tokens.TokenPair:
            async with session_factory() as own:
                result = await refresh_session(own, pair.refresh_token, attempt=attempt)
                await own.commit()
                return result

        first, second = await asyncio.gather(one(), one())
        assert first == second
        async with session_factory() as fresh:
            rows = (await fresh.execute(select(ExtensionSession))).scalars().all()
        assert len(rows) == 1
        assert rows[0].refresh_token_hash == token_hash(first.refresh_token)
        assert rows[0].revoked_at is None

    async def test_two_attempts_at_once_end_the_session(self, db_session, session_factory, user, clock):
        pair = await _connect(db_session, user)

        async def one(attempt: str) -> tokens.TokenPair:
            async with session_factory() as own:
                result = await refresh_session(own, pair.refresh_token, attempt=attempt)
                await own.commit()
                return result

        outcomes = await asyncio.gather(one(ATTEMPT), one(OTHER_ATTEMPT), return_exceptions=True)
        granted = [o for o in outcomes if isinstance(o, tokens.TokenPair)]
        refused = [o for o in outcomes if isinstance(o, ExtensionTokenError)]
        assert len(granted) == len(refused) == 1 and refused[0].code == "invalid_grant"
        assert (await _row(session_factory, pair.session_id)).revoked_reason == "refresh_reuse"
        assert (await _grant_error(authenticate(db_session, granted[0].access_token))).code == "revoked"


class TestRevoke:
    async def test_revoking_is_once_and_only_your_own(self, db_session, user):
        other = User(username="someone_else", email="else@test", auth_provider="local", is_active=True)
        db_session.add(other)
        await db_session.commit()
        pair = await _connect(db_session, user)
        assert not await revoke_session(db_session, pair.session_id, reason="user", user_id=other.id)
        assert await revoke_session(db_session, pair.session_id, reason="user", user_id=user.id)
        assert not await revoke_session(db_session, pair.session_id, reason="user", user_id=user.id)
        await db_session.commit()
        row = await db_session.get(ExtensionSession, pair.session_id)
        await db_session.refresh(row)
        assert row.revoked_reason == "user"


class TestTouch:
    async def test_use_is_written_at_most_once_a_minute(self, db_session, session_factory, user, clock):
        pair = await _connect(db_session, user, ip="10.0.0.5")
        connected = clock.value
        clock.advance(seconds=59)
        await touch_session(pair.session_id, ip="10.0.0.6")
        row = await _row(session_factory, pair.session_id)
        assert (row.last_used_at, row.last_ip) == (connected, "10.0.0.5")
        assert not needs_touch(row, clock.value)
        clock.advance(seconds=2)
        assert needs_touch(row, clock.value)
        await touch_session(pair.session_id, ip="10.0.0.6")
        row = await _row(session_factory, pair.session_id)
        assert (row.last_used_at, row.last_ip) == (clock.value, "10.0.0.6")

    async def test_a_database_failure_never_fails_the_request(self, monkeypatch):
        def broken():
            raise RuntimeError("database unavailable")

        monkeypatch.setattr(tokens, "AsyncSessionLocal", broken)
        await touch_session("any", ip=None)

    def test_a_session_never_used_needs_a_touch(self):
        assert needs_touch(ExtensionSession(last_used_at=None))


class TestList:
    async def test_only_live_sessions_newest_first(self, db_session, user, clock):
        other = User(username="someone_else", email="else@test", auth_provider="local", is_active=True)
        db_session.add(other)
        await db_session.commit()
        oldest = await _connect(db_session, user, device_name="oldest")
        clock.advance(minutes=1)
        revoked = await _connect(db_session, user, device_name="revoked")
        await revoke_session(db_session, revoked.session_id, reason="user")
        clock.advance(minutes=1)
        idle = await _connect(db_session, user, device_name="idle")
        await db_session.execute(
            update(ExtensionSession)
            .where(ExtensionSession.id == idle.session_id)
            .values(refresh_expires_at=clock.value)
        )
        clock.advance(minutes=1)
        await _connect(db_session, other, device_name="someone else's")
        newest = await _connect(db_session, user, device_name="newest")
        await db_session.commit()
        listed = await list_sessions(db_session, user)
        assert [row.id for row in listed] == [newest.session_id, oldest.session_id]

    async def test_a_sign_out_everywhere_empties_the_list_at_once(self, db_session, user, clock):
        await _connect(db_session, user)
        user.token_version = 1
        await db_session.commit()
        assert await list_sessions(db_session, user) == []
        fresh = await _connect(db_session, user)
        assert [row.id for row in await list_sessions(db_session, user)] == [fresh.session_id]


class TestCleanup:
    async def test_connections_that_ended_long_ago_are_deleted(self, db_session, session_factory, user, clock):
        live = await _connect(db_session, user)
        revoked_long_ago = await _connect(db_session, user)
        revoked_lately = await _connect(db_session, user)
        idle_long_ago = await _connect(db_session, user)
        long = clock.value - tokens.ENDED_SESSION_RETENTION - datetime.timedelta(days=1)
        lately = clock.value - datetime.timedelta(days=10)
        for session_id, values in (
            (revoked_long_ago.session_id, {"revoked_at": long}),
            (revoked_lately.session_id, {"revoked_at": lately}),
            (idle_long_ago.session_id, {"refresh_expires_at": long}),
        ):
            await db_session.execute(update(ExtensionSession).where(ExtensionSession.id == session_id).values(**values))
        await db_session.commit()
        assert await tokens.purge_ended_sessions(db_session) == 2
        async with session_factory() as fresh:
            left = set((await fresh.execute(select(ExtensionSession.id))).scalars().all())
        assert left == {live.session_id, revoked_lately.session_id}

    async def test_it_works_in_batches(self, db_session, session_factory, user, clock, monkeypatch):
        monkeypatch.setattr(tokens, "_PURGE_BATCH", 2)
        for _ in range(5):
            pair = await _connect(db_session, user)
            await db_session.execute(
                update(ExtensionSession)
                .where(ExtensionSession.id == pair.session_id)
                .values(revoked_at=clock.value - tokens.ENDED_SESSION_RETENTION - datetime.timedelta(days=1))
            )
        await db_session.commit()
        assert await tokens.purge_ended_sessions(db_session) == 5

    def test_the_nightly_job_is_registered(self, monkeypatch):
        from app.services import scheduler

        added: list[tuple[tuple, dict]] = []
        monkeypatch.setattr(scheduler.scheduler, "add_job", lambda *a, **k: added.append((a, k)))
        monkeypatch.setattr(scheduler.scheduler, "start", lambda: None)
        scheduler.start_scheduler()
        (args, kwargs) = next((a, k) for a, k in added if k.get("id") == "extension_session_cleanup")
        assert args == (scheduler.job_extension_session_cleanup, "cron")
        assert (kwargs["hour"], kwargs["minute"]) == (4, 40)

    async def test_the_nightly_job_deletes_on_the_app_database(
        self, db_session, session_factory, user, clock, monkeypatch
    ):
        from app.services import scheduler

        pair = await _connect(db_session, user)
        await db_session.execute(
            update(ExtensionSession)
            .where(ExtensionSession.id == pair.session_id)
            .values(revoked_at=clock.value - tokens.ENDED_SESSION_RETENTION - datetime.timedelta(days=1))
        )
        await db_session.commit()
        monkeypatch.setattr(scheduler, "AsyncSessionLocal", session_factory)
        await scheduler.job_extension_session_cleanup()
        async with session_factory() as fresh:
            assert (await fresh.execute(select(ExtensionSession.id))).first() is None
