"""Exchange EWS: the rules in app.services.exchange_mail (settings, who may connect, logins, access, refs)."""

from __future__ import annotations

import asyncio
import datetime
import json
import threading
import time

import pytest
from sqlalchemy import func, select

from app.models.auth_provider import AuthProviderConfig
from app.models.mail_connection import (
    MailActionItem,
    MailConnection,
    MailConnectionMailbox,
    MailDraft,
    MailItemRef,
)
from app.models.system import SystemSetting
from app.models.user import User
from app.services import exchange_mail as em
from app.services.exchange_ews_types import EwsConfig, EwsError

CA_PEM = """-----BEGIN CERTIFICATE-----
MIIBkzCCATmgAwIBAgIUNaB7Hvd0lmzmmUZPzU6ocyvXqGEwCgYIKoZIzj0EAwIw
FjEUMBIGA1UEAwwLVGVzdCBSb290IENBMB4XDTI2MDEwMTAwMDAwMFoXDTM2MDEw
MTAwMDAwMFowFjEUMBIGA1UEAwwLVGVzdCBSb290IENBMFkwEwYHKoZIzj0CAQYI
KoZIzj0DAQcDQgAE
-----END CERTIFICATE-----"""


def _make_ca_pem() -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Corp Root CA")])
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii")


async def _ad_person(db, username="s.karimi", *, email="s.karimi@corp.example", provider="ldap", active=True):
    person = User(username=username, email=email, auth_provider=provider, is_active=active, display_name="Sara K")
    db.add(person)
    await db.commit()
    await db.refresh(person)
    return person


async def _turn_on(db, **overrides):
    settings = em.ExchangeSettings(enabled=True, ews_url="https://mail.corp.example/EWS/Exchange.asmx")
    for key, value in overrides.items():
        setattr(settings, key, value)
    await em.save_settings(db, settings)
    await db.commit()
    return settings


async def _ldap(db, **config):
    db.add(AuthProviderConfig(provider="ldap", enabled=True, config_json=json.dumps(config)))
    await db.commit()


async def _connect(db, person, *, status="connected", password="Secret-1", boxes=()):
    connection = MailConnection(
        user_id=person.id,
        login=f"CORP\\{person.username}",
        secret_encrypted=em.encrypt_password(password),
        primary_smtp=person.email,
        display_name="Sara K",
        status=status,
    )
    db.add(connection)
    await db.flush()
    db.add(MailConnectionMailbox(connection_id=connection.id, smtp=person.email, kind="own", source="own", notify=True))
    for smtp, enabled in boxes:
        db.add(
            MailConnectionMailbox(
                connection_id=connection.id, smtp=smtp, kind="full_access", source="autodiscover", enabled=enabled
            )
        )
    await db.commit()
    return connection


class TestSettings:
    async def test_off_until_turned_on(self, db_session):
        settings = await em.load_settings(db_session)
        assert settings.enabled is False
        assert settings.configured is False
        assert settings.login_format == "netbios"
        assert settings.allow_send is True

    async def test_garbled_or_out_of_bounds_values_are_put_back(self, db_session):
        db_session.add(
            SystemSetting(
                key=em.SETTINGS_KEY,
                value=json.dumps(
                    {
                        "enabled": "yes",
                        "poll_minutes": 1000,
                        "search_limit": "x",
                        "login_format": "kerberos",
                        "autodiscover_url": "http://plain.example/autodiscover",
                        "ews_url": 5,
                    }
                ),
            )
        )
        await db_session.commit()
        settings = await em.load_settings(db_session)
        assert settings.enabled is False
        assert settings.poll_minutes == 60
        assert settings.search_limit == 25
        assert settings.login_format == "netbios"
        assert settings.autodiscover_url == ""
        assert settings.ews_url == ""

    async def test_unreadable_json_gives_the_defaults(self, db_session):
        db_session.add(SystemSetting(key=em.SETTINGS_KEY, value="{not json"))
        await db_session.commit()
        assert (await em.load_settings(db_session)) == em.ExchangeSettings()

    async def test_save_and_load_round_trip(self, db_session):
        settings = await _turn_on(db_session, login_format="upn", upn_suffix="corp.example", poll_minutes=10)
        loaded = await em.load_settings(db_session)
        assert loaded == settings
        settings.allow_send = False
        await em.save_settings(db_session, settings)
        await db_session.commit()
        assert (await em.load_settings(db_session)).allow_send is False

    def test_a_bare_host_is_completed_to_the_ews_endpoint(self):
        assert em.normalize_ews_url("https://mail.corp.example") == "https://mail.corp.example/EWS/Exchange.asmx"
        assert em.normalize_ews_url("https://mail.corp.example/") == "https://mail.corp.example/EWS/Exchange.asmx"
        assert (
            em.normalize_ews_url("https://mail.corp.example:8443/ews/exchange.asmx?x=1#y")
            == "https://mail.corp.example:8443/ews/exchange.asmx"
        )

    @pytest.mark.parametrize(
        "value", ["http://mail.corp.example", "ftp://x", "mail.corp.example", "https://user:pw@mail.corp.example", ""]
    )
    def test_only_plain_https_addresses_are_endpoints(self, value):
        assert em.normalize_ews_url(value) == ""

    def test_autodiscover_defaults_to_the_ews_host(self):
        settings = em.ExchangeSettings(ews_url="https://mail.corp.example:444/EWS/Exchange.asmx")
        assert settings.autodiscover_endpoint() == "https://mail.corp.example:444/autodiscover/autodiscover.xml"
        settings.autodiscover_url = "https://autodiscover.corp.example/autodiscover/autodiscover.xml"
        assert settings.autodiscover_endpoint() == settings.autodiscover_url
        assert em.ExchangeSettings().autodiscover_endpoint() == ""


class TestValidateSettings:
    def _valid(self, **overrides):
        data = em.ExchangeSettings(enabled=True, ews_url="https://mail.corp.example").as_dict()
        data.update(overrides)
        return data

    def test_a_valid_object_is_normalised(self):
        settings = em.validate_settings(
            self._valid(netbios_domain="corp", upn_suffix="@Corp.Example", ews_url=" https://mail.corp.example ")
        )
        assert settings.ews_url == "https://mail.corp.example/EWS/Exchange.asmx"
        assert settings.netbios_domain == "CORP"
        assert settings.upn_suffix == "corp.example"

    @pytest.mark.parametrize(
        ("overrides", "fragment"),
        [
            ({"enabled": "true"}, "enabled must be true or false"),
            ({"poll_minutes": 1}, "poll_minutes"),
            ({"poll_minutes": True}, "poll_minutes"),
            ({"body_chars": 50000}, "body_chars"),
            ({"ews_url": "http://mail.corp.example"}, "https address"),
            ({"ews_url": ""}, "before turning Exchange EWS on"),
            ({"autodiscover_url": "http://x/autodiscover"}, "Autodiscover"),
            ({"login_format": "kerberos"}, "login_format"),
            ({"netbios_domain": "corp.example.local.toolong"}, "NetBIOS"),
            ({"netbios_domain": "co rp"}, "NetBIOS"),
            ({"upn_suffix": "not a domain"}, "UPN suffix"),
            ({"ca_bundle_pem": "hello"}, "PEM"),
            ({"ca_bundle_pem": CA_PEM}, "could not be read"),
            ({"ca_bundle_pem": "x" * (em.CA_BUNDLE_MAX + 1)}, "KB"),
            ({"detection": "magic"}, "detection"),
            ({"detection": "model", "detection_model": ""}, "Choose the model"),
        ],
    )
    def test_refuses_what_is_wrong_and_says_which(self, overrides, fragment):
        with pytest.raises(em.MailError) as caught:
            em.validate_settings(self._valid(**overrides))
        assert caught.value.code == "invalid_settings"
        assert caught.value.status_code == 422
        assert fragment in caught.value.message

    def test_off_may_be_saved_without_an_address(self):
        settings = em.validate_settings(self._valid(enabled=False, ews_url=""))
        assert settings.enabled is False and settings.ews_url == ""

    def test_a_real_ca_certificate_is_accepted(self):
        pem = _make_ca_pem()
        assert em.check_ca_bundle(pem + "\n" + pem) == 2
        assert em.validate_settings(self._valid(ca_bundle_pem=pem)).ca_bundle_pem == pem.strip()

    def test_not_an_object(self):
        with pytest.raises(em.MailError):
            em.validate_settings(["x"])  # type: ignore[arg-type]

    def test_changed_keys_names_only_what_changed(self):
        before = em.ExchangeSettings()
        after = em.ExchangeSettings(enabled=True, ews_url="https://m.example/EWS/Exchange.asmx")
        assert em.changed_keys(before, after) == ["enabled", "ews_url"]


class TestLogins:
    async def test_the_domain_comes_from_the_ldap_settings(self, db_session):
        await _ldap(db_session, domain="corp.example", base_dn="DC=corp,DC=example", bind_username="svc@corp.example")
        defaults = await em.directory_defaults(db_session)
        assert defaults.netbios_domain == "CORP"
        assert defaults.dns_domain == "corp.example"
        assert defaults.available

    async def test_a_netbios_bind_name_wins(self, db_session):
        await _ldap(db_session, bind_username="CONTOSO\\svc-ldap", base_dn="DC=corp,DC=example")
        defaults = await em.directory_defaults(db_session)
        assert defaults.netbios_domain == "CONTOSO"
        assert defaults.dns_domain == "corp.example"

    async def test_no_ldap_settings_no_defaults(self, db_session):
        defaults = await em.directory_defaults(db_session)
        assert not defaults.available

    def test_login_formats(self):
        person = User(username="s.karimi", email="Sara.Karimi@Corp.Example")
        defaults = em.DirectoryDefaults(netbios_domain="CORP", dns_domain="corp.example")
        settings = em.ExchangeSettings()
        assert em.login_for(person, settings, defaults) == "CORP\\s.karimi"
        settings.netbios_domain = "HQ"
        assert em.login_for(person, settings, defaults) == "HQ\\s.karimi"
        settings.login_format = "upn"
        assert em.login_for(person, settings, defaults) == "s.karimi@corp.example"
        settings.upn_suffix = "hq.example"
        assert em.login_for(person, settings, defaults) == "s.karimi@hq.example"
        settings.login_format = "email"
        assert em.login_for(person, settings, defaults) == "sara.karimi@corp.example"

    def test_no_login_when_it_cannot_be_made(self):
        settings = em.ExchangeSettings()
        assert em.login_for(User(username="s.karimi"), settings, em.DirectoryDefaults()) == ""
        assert em.login_for(User(username="two words"), settings, em.DirectoryDefaults("CORP")) == ""
        settings.login_format = "email"
        assert em.login_for(User(username="x", email=None), settings, em.DirectoryDefaults()) == ""

    def test_a_username_with_a_domain_is_reduced_to_the_account(self):
        defaults = em.DirectoryDefaults(netbios_domain="CORP", dns_domain="corp.example")
        assert em.login_for(User(username="OLD\\s.karimi"), em.ExchangeSettings(), defaults) == "CORP\\s.karimi"
        assert em.login_for(User(username="s.karimi@x.example"), em.ExchangeSettings(), defaults) == "CORP\\s.karimi"


class TestEligibility:
    async def test_off_until_turned_on_and_configured(self, db_session):
        person = await _ad_person(db_session)
        assert (await em.eligibility(db_session, person)).reason == "feature_off"
        settings = em.ExchangeSettings(enabled=True)
        assert (await em.eligibility(db_session, person, settings)).reason == "not_configured"

    async def test_an_ad_account_with_an_email_may_connect(self, db_session):
        person = await _ad_person(db_session)
        await _turn_on(db_session)
        verdict = await em.eligibility(db_session, person)
        assert verdict.allowed and verdict.reason == "" and verdict.message == ""

    @pytest.mark.parametrize(
        ("kwargs", "reason"),
        [
            ({"provider": "local"}, "not_ad"),
            ({"provider": "saml"}, "not_ad"),
            ({"email": None}, "no_email"),
            ({"email": "not-an-address"}, "no_email"),
            ({"active": False}, "not_permitted"),
        ],
    )
    async def test_who_may_not(self, db_session, kwargs, reason):
        person = await _ad_person(db_session, **kwargs)
        await _turn_on(db_session)
        verdict = await em.eligibility(db_session, person)
        assert not verdict.allowed
        assert verdict.reason == reason
        assert verdict.message

    async def test_the_access_list_decides_among_ad_accounts(self, db_session):
        from app.services.chat_tool_access_service import set_chat_tool_access
        from app.services.resource_access_service import AccessGrant

        person = await _ad_person(db_session)
        other = await _ad_person(db_session, "a.rad", email="a.rad@corp.example")
        await _turn_on(db_session)
        await set_chat_tool_access(
            db_session, em.TOOL_KEY, access_type="private", grants=[AccessGrant(target_type="user", target=other.id)]
        )
        await db_session.commit()
        assert (await em.eligibility(db_session, person)).reason == "not_permitted"
        assert (await em.eligibility(db_session, other)).allowed

    async def test_no_chat_no_mail(self, db_session, monkeypatch):
        from app.services import feature_access_service

        person = await _ad_person(db_session)
        await _turn_on(db_session)

        async def no_chat(db, user, feature):
            return feature != "chat"

        monkeypatch.setattr(feature_access_service, "feature_enabled", no_chat)
        assert (await em.eligibility(db_session, person)).reason == "chat_off"


class TestAccess:
    async def test_a_working_connection_gives_its_enabled_mailboxes(self, db_session):
        person = await _ad_person(db_session)
        await _turn_on(db_session)
        await _connect(db_session, person, boxes=(("finance@corp.example", True), ("ceo@corp.example", False)))
        access = await em.usable_access(db_session, person)
        assert access is not None
        assert access.own_smtp == "s.karimi@corp.example"
        assert [box.smtp for box in access.mailboxes] == ["s.karimi@corp.example", "finance@corp.example"]
        assert access.config.password == "Secret-1"
        assert access.config.login == "CORP\\s.karimi"
        assert access.config.ews_url == "https://mail.corp.example/EWS/Exchange.asmx"
        assert access.notify_mailboxes == ("s.karimi@corp.example",)
        assert access.mailbox(None) == "s.karimi@corp.example"
        assert access.mailbox("Finance@Corp.Example") == "finance@corp.example"
        with pytest.raises(em.MailError) as caught:
            access.mailbox("ceo@corp.example")
        assert caught.value.code == "mailbox_not_allowed"
        assert "Secret-1" not in repr(access.config)

    async def test_the_notify_switch_of_each_mailbox_decides_what_is_checked(self, db_session):
        person = await _ad_person(db_session)
        await _turn_on(db_session)
        connection = await _connect(db_session, person, boxes=(("finance@corp.example", True),))
        rows = await em.list_mailboxes(db_session, connection.id)
        rows[0].notify = False  # the own mailbox
        rows[1].notify = True
        await db_session.commit()
        access = await em.usable_access(db_session, person)
        assert access is not None
        assert access.notify_mailboxes == ("finance@corp.example",)

    async def test_full_access_mailboxes_go_when_the_admin_turns_them_off(self, db_session):
        person = await _ad_person(db_session)
        await _turn_on(db_session, allow_full_access=False)
        await _connect(db_session, person, boxes=(("finance@corp.example", True),))
        access = await em.usable_access(db_session, person)
        assert access is not None
        assert [box.smtp for box in access.mailboxes] == ["s.karimi@corp.example"]

    @pytest.mark.parametrize("status", ["needs_password", "error"])
    async def test_a_stopped_connection_gives_nothing(self, db_session, status):
        person = await _ad_person(db_session)
        await _turn_on(db_session)
        await _connect(db_session, person, status=status)
        assert await em.usable_access(db_session, person) is None

    async def test_an_ineligible_person_gives_nothing_even_when_connected(self, db_session):
        person = await _ad_person(db_session)
        await _connect(db_session, person)
        assert await em.usable_access(db_session, person) is None  # feature off

    async def test_an_unreadable_password_gives_nothing(self, db_session):
        person = await _ad_person(db_session)
        await _turn_on(db_session)
        connection = await _connect(db_session, person)
        connection.secret_encrypted = "gAAAAAgarbage"
        await db_session.commit()
        assert await em.usable_access(db_session, person) is None

    def test_a_copied_token_is_not_a_password(self):
        token = em.encrypt_password("Secret-1")
        with pytest.raises(em.MailError) as caught:
            em.encrypt_password(token)
        assert caught.value.code == "invalid_password"
        with pytest.raises(em.MailError):
            em.encrypt_password("")
        with pytest.raises(em.MailError):
            em.encrypt_password("x" * 257)

    async def test_session_features(self, db_session):
        person = await _ad_person(db_session)
        assert await em.session_features(db_session, person) == {"connections": False, "exchange_mail": False}
        await _turn_on(db_session)
        assert await em.session_features(db_session, person) == {"connections": True, "exchange_mail": False}
        connection = await _connect(db_session, person)
        assert await em.session_features(db_session, person) == {"connections": True, "exchange_mail": True}
        connection.status = "needs_password"
        await db_session.commit()
        assert await em.session_features(db_session, person) == {"connections": True, "exchange_mail": False}

    async def test_session_features_never_break_the_session(self, db_session, monkeypatch):
        person = await _ad_person(db_session)

        async def broken(db):
            raise RuntimeError("boom")

        monkeypatch.setattr(em, "load_settings", broken)
        assert await em.session_features(db_session, person) == {"connections": False, "exchange_mail": False}


class TestFailures:
    async def test_a_refused_password_stops_the_connection_at_once(self, db_session):
        person = await _ad_person(db_session)
        connection = await _connect(db_session, person)
        await em.record_failure(db_session, connection, EwsError("auth", "401"))
        assert connection.status == "needs_password"
        assert "password" in connection.last_error
        assert connection.consecutive_failures == 1

    async def test_other_failures_are_counted_but_never_stop_the_connection(self, db_session):
        person = await _ad_person(db_session)
        connection = await _connect(db_session, person)
        for _ in range(20):
            await em.record_failure(db_session, connection, EwsError("unreachable", "Exchange did not answer."))
        assert connection.status == "connected"
        assert connection.consecutive_failures == 20
        assert connection.last_error == "Exchange did not answer."
        await em.record_success(db_session, connection)
        assert connection.status == "connected"
        assert connection.consecutive_failures == 0 and connection.last_error is None
        assert connection.last_ok_at is not None

    async def test_a_needs_password_connection_is_not_revived_by_a_success_elsewhere(self, db_session):
        person = await _ad_person(db_session)
        connection = await _connect(db_session, person, status="needs_password")
        await em.record_success(db_session, connection)
        assert connection.status == "needs_password"

    async def test_a_wrong_mailbox_stops_the_connection(self, db_session):
        person = await _ad_person(db_session)
        connection = await _connect(db_session, person)
        await em.record_failure(db_session, connection, EwsError("mailbox_mismatch", "Another mailbox."))
        assert connection.status == "error"

    async def test_a_full_access_mailbox_drops_out_when_access_is_gone(self, db_session):
        person = await _ad_person(db_session)
        connection = await _connect(db_session, person, boxes=(("finance@corp.example", True),))
        assert not await em.record_mailbox_failure(
            db_session, connection.id, "finance@corp.example", EwsError("unreachable", "x")
        )
        assert await em.record_mailbox_failure(
            db_session, connection.id, "Finance@corp.example", EwsError("access_denied", "No access.")
        )
        row = (
            await db_session.execute(
                select(MailConnectionMailbox).where(MailConnectionMailbox.smtp == "finance@corp.example")
            )
        ).scalar_one()
        assert row.enabled is False and row.last_error == "No access."
        assert not await em.record_mailbox_failure(
            db_session, connection.id, person.email, EwsError("access_denied", "No access.")
        )


class TestRefs:
    def test_a_ref_is_short_stable_and_alphanumeric(self):
        ref = em.ref_value("s.karimi@corp.example", "AAMkAGI2")
        assert ref == em.ref_value("S.Karimi@corp.example", "AAMkAGI2")
        assert ref != em.ref_value("s.karimi@corp.example", "AAMkAGI3")
        assert len(ref) == em.REF_LENGTH and ref.startswith("m") and ref.isalnum()
        assert em.looks_like_ref(ref)
        assert not em.looks_like_ref("m123")
        assert not em.looks_like_ref("x" * 10)
        assert not em.looks_like_ref(None)

    async def test_a_ref_belongs_to_one_person_and_expires(self, db_session):
        person = await _ad_person(db_session)
        other = await _ad_person(db_session, "a.rad", email="a.rad@corp.example")
        ref = await em.ref_for(db_session, person.id, person.email, "AAMk1", "ck1")
        assert ref == await em.ref_for(db_session, person.id, person.email, "AAMk1", "ck2")
        await db_session.commit()
        assert (await db_session.execute(select(func.count()).select_from(MailItemRef))).scalar_one() == 1
        found = await em.resolve_ref(db_session, person.id, ref)
        assert found is not None and found.item_id == "AAMk1" and found.change_key == "ck2"
        assert await em.resolve_ref(db_session, other.id, ref) is None
        assert await em.resolve_ref(db_session, person.id, "not a ref") is None
        found.created_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - datetime.timedelta(days=8)
        await db_session.commit()
        assert await em.resolve_ref(db_session, person.id, ref) is None
        assert await em.prune_refs(db_session) == 1


class TestDeleting:
    async def test_disconnecting_forgets_everything_mail_kept(self, db_session):
        person = await _ad_person(db_session)
        other = await _ad_person(db_session, "a.rad", email="a.rad@corp.example")
        await _connect(db_session, person, boxes=(("finance@corp.example", True),))
        await _connect(db_session, other)
        for who in (person, other):
            await em.ref_for(db_session, who.id, who.email, "AAMk1")
            db_session.add(MailDraft(user_id=who.id, mailbox_smtp=who.email, item_id="d1", kind="new", subject="s"))
            db_session.add(MailActionItem(user_id=who.id, mailbox_smtp=who.email, item_key=f"k{who.id}", item_id="i1"))
        await db_session.commit()
        assert await em.delete_connection(db_session, person.id)
        await db_session.commit()
        for model in (MailConnection, MailItemRef, MailDraft, MailActionItem):
            rows = (await db_session.execute(select(model))).scalars().all()
            assert [row.user_id for row in rows] == [other.id], model.__name__
        assert (await db_session.execute(select(func.count()).select_from(MailConnectionMailbox))).scalar_one() == 1
        assert not await em.delete_connection(db_session, person.id)

    async def test_the_purge_hook(self, db_session):
        person = await _ad_person(db_session)
        await _connect(db_session, person)
        await em.delete_user_mail(db_session, person.id)
        await db_session.commit()
        assert await em.get_connection(db_session, person.id) is None

    async def test_counts(self, db_session):
        person = await _ad_person(db_session)
        other = await _ad_person(db_session, "a.rad", email="a.rad@corp.example")
        await _connect(db_session, person)
        await _connect(db_session, other, status="needs_password")
        assert await em.connection_counts(db_session) == {"connected": 1, "needs_password": 1, "error": 0}


class _ThreadClient:
    """A client that notes the thread it was made, used and closed in."""

    def __init__(self, log: list[tuple[str, int]]) -> None:
        self.log = log
        self.log.append(("made", threading.get_ident()))

    def work(self, seconds: float = 0.0) -> int:
        self.log.append(("work", threading.get_ident()))
        time.sleep(seconds)
        return threading.get_ident()

    def close(self) -> None:
        self.log.append(("closed", threading.get_ident()))


CONFIG = EwsConfig(ews_url="https://mail.corp.example/EWS/Exchange.asmx", login="CORP\\s.karimi", password="x")


class TestCallEws:
    @pytest.fixture
    def log(self, monkeypatch) -> list[tuple[str, int]]:
        log: list[tuple[str, int]] = []
        monkeypatch.setattr(em, "make_client", lambda config: _ThreadClient(log))
        monkeypatch.setattr(em, "_ews_slots", None)
        return log

    async def test_the_client_is_made_used_and_closed_in_one_worker_thread(self, log):
        caller = threading.get_ident()
        worker = await em.call_ews(CONFIG, lambda client: client.work(), timeout_s=5)
        assert worker != caller
        assert log == [("made", worker), ("work", worker), ("closed", worker)]

    async def test_a_slow_call_times_out_as_unreachable_and_holds_its_slot_until_the_thread_ends(
        self, log, monkeypatch
    ):
        monkeypatch.setattr(em, "EWS_CONCURRENCY", 1)
        with pytest.raises(EwsError) as caught:
            await em.call_ews(CONFIG, lambda client: client.work(0.4), timeout_s=0.05)
        assert caught.value.kind == "unreachable"
        # The thread still runs: its client is not closed under it, and its slot is not free yet.
        assert [what for what, _ in log] == ["made", "work"]
        slots = em._slots()
        assert slots.locked()
        started = time.monotonic()
        await em.call_ews(CONFIG, lambda client: client.work(), timeout_s=5)
        assert time.monotonic() - started >= 0.2, "the next call waited for the slow thread to end"
        assert [what for what, _ in log] == ["made", "work", "closed", "made", "work", "closed"]
        assert not slots.locked()

    async def test_a_cancelled_wait_also_keeps_the_slot_until_the_thread_ends(self, log, monkeypatch):
        monkeypatch.setattr(em, "EWS_CONCURRENCY", 1)
        task = asyncio.ensure_future(em.call_ews(CONFIG, lambda client: client.work(0.3), timeout_s=5))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert em._slots().locked()
        await asyncio.sleep(0.5)
        assert not em._slots().locked()
        assert log[-1][0] == "closed"

    async def test_errors_come_through_and_the_client_is_closed(self, log):
        def fail(client):
            raise EwsError("auth", "no")

        with pytest.raises(EwsError) as caught:
            await em.call_ews(CONFIG, fail, timeout_s=5)
        assert caught.value.kind == "auth"
        assert [what for what, _ in log] == ["made", "closed"]
        assert not em._slots().locked()

    async def test_at_most_so_many_at_once(self, log, monkeypatch):
        monkeypatch.setattr(em, "EWS_CONCURRENCY", 2)
        running = 0
        peak = 0
        lock = threading.Lock()

        def work(client):
            nonlocal running, peak
            with lock:
                running += 1
                peak = max(peak, running)
            time.sleep(0.05)
            with lock:
                running -= 1

        await asyncio.gather(*(em.call_ews(CONFIG, work, timeout_s=5) for _ in range(6)))
        assert peak == 2

    def test_the_wait_follows_the_administrator_s_timeout(self):
        settings = em.ExchangeSettings(timeout_s=30)
        assert em.call_timeout(settings) == 35
        assert em.call_timeout(settings, steps=3) == 105


async def test_the_fake_client_follows_the_protocol(monkeypatch):
    """The shared test double gives what the client promises (so tests built on it test something real)."""
    from tests.fake_mail_client import FakeExchange, install

    exchange = install(monkeypatch, FakeExchange())
    exchange.add_account("CORP\\s.karimi", "pw", "s.karimi@corp.example", "Sara", full_access=("finance@corp.example",))
    exchange.add_mailbox("finance@corp.example", "Finance")
    message = exchange.add_message("s.karimi@corp.example", "Budget 2027", body="Please approve the budget.")
    config = em.ews_config(em.ExchangeSettings(ews_url="https://m.example"), "CORP\\s.karimi", "pw")
    client = em.make_client(config)
    assert client.whoami().smtp == "s.karimi@corp.example"
    assert [box.smtp for box in client.discover_full_access()] == ["finance@corp.example"]
    assert [m.subject for m in client.search("s.karimi@corp.example", query="budget")] == ["Budget 2027"]
    draft = client.create_draft(
        "s.karimi@corp.example", kind="reply", body_text="Approved.", source_item_id=message.item_id
    )
    assert draft.subject == "RE: Budget 2027" and draft.to[0].email == "boss@corp.example"
    with pytest.raises(EwsError) as caught:
        client.send_draft("s.karimi@corp.example", draft.item_id, "stale")
    assert caught.value.kind == "conflict"
    client.send_draft("s.karimi@corp.example", draft.item_id, draft.change_key)
    assert len(exchange.sent) == 1
    with pytest.raises(EwsError) as caught:
        client.check_mailbox("ceo@corp.example")
    assert caught.value.kind == "not_found"
    bad = em.make_client(em.ews_config(em.ExchangeSettings(), "CORP\\s.karimi", "wrong"))
    with pytest.raises(EwsError) as caught:
        bad.whoami()
    assert caught.value.kind == "auth"
