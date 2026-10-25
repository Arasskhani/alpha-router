"""The real EWS client against a fake Exchange (``tests/fake_ews_server.py``), end to end.

Every ``MailClient`` method is driven through exchangelib against the fake
server - HTTPS with a certificate made for the test run, Basic auth, the
SOAP exchangelib really sends - so the requests, the parsing and the error
mapping are all exercised; nothing in exchangelib is patched. A few helpers
with no network (time zone matching, the error table) also get direct unit
tests. NTLM itself cannot be driven against the Basic-only fake: the test
only checks that an NTLM configuration builds an NTLM session.
"""

from __future__ import annotations

import base64
import datetime
import logging
import os
import pathlib
import socket
import stat
import zoneinfo

import certifi
import pytest
from exchangelib import BaseProtocol
from exchangelib.errors import (
    ErrorAccessDenied,
    ErrorInvalidRecipients,
    ErrorIrresolvableConflict,
    ErrorItemNotFound,
    ErrorNonExistentMailbox,
    ErrorSendAsDenied,
    ErrorServerBusy,
    ErrorTimeoutExpired,
    TransportError,
    UnauthorizedError,
)
from exchangelib.protocol import CachingProtocol, Protocol
from requests_ntlm import HttpNtlmAuth

from app.services import exchange_ews_client as ews
from app.services.exchange_ews_client import EwsClient
from app.services.exchange_ews_types import Address, EwsConfig, EwsError, MailboxInfo
from tests.fake_ews_server import FakeCalendar, FakeEwsServer, FakeExchange, FakeItem, FakePerson
from tests.smtp_test_server import TlsMaterial, make_tls_material

UTC = datetime.UTC
LOGIN = "CORP\\s.karimi"
PASSWORD = "Winter-2026!pw"
OWN = "s.karimi@corp.example"
FINANCE = "finance@corp.example"
CEO = "ceo@corp.example"

TEHRAN_HOURS = (
    "<t:TimeZone><t:Bias>-210</t:Bias>"
    "<t:StandardTime><t:Bias>0</t:Bias><t:Time>00:00:00</t:Time><t:DayOrder>1</t:DayOrder><t:Month>1</t:Month>"
    "<t:DayOfWeek>Sunday</t:DayOfWeek></t:StandardTime>"
    "<t:DaylightTime><t:Bias>0</t:Bias><t:Time>00:00:00</t:Time><t:DayOrder>5</t:DayOrder><t:Month>12</t:Month>"
    "<t:DayOfWeek>Saturday</t:DayOfWeek></t:DaylightTime></t:TimeZone>"
    "<t:WorkingPeriodArray><t:WorkingPeriod><t:DayOfWeek>Saturday Sunday Monday Tuesday Wednesday</t:DayOfWeek>"
    "<t:StartTimeInMinutes>480</t:StartTimeInMinutes><t:EndTimeInMinutes>1020</t:EndTimeInMinutes>"
    "</t:WorkingPeriod></t:WorkingPeriodArray>"
)
# W. Europe: UTC+1, summer time from the last Sunday of March 02:00 to the last Sunday of October 03:00.
BERLIN_HOURS = (
    "<t:TimeZone><t:Bias>-60</t:Bias>"
    "<t:StandardTime><t:Bias>0</t:Bias><t:Time>03:00:00</t:Time><t:DayOrder>5</t:DayOrder><t:Month>10</t:Month>"
    "<t:DayOfWeek>Sunday</t:DayOfWeek></t:StandardTime>"
    "<t:DaylightTime><t:Bias>-60</t:Bias><t:Time>02:00:00</t:Time><t:DayOrder>5</t:DayOrder><t:Month>3</t:Month>"
    "<t:DayOfWeek>Sunday</t:DayOfWeek></t:DaylightTime></t:TimeZone>"
    "<t:WorkingPeriodArray><t:WorkingPeriod><t:DayOfWeek>Monday Tuesday Wednesday Thursday Friday</t:DayOfWeek>"
    "<t:StartTimeInMinutes>540</t:StartTimeInMinutes><t:EndTimeInMinutes>1020</t:EndTimeInMinutes>"
    "</t:WorkingPeriod></t:WorkingPeriodArray>"
)
# No real zone is 37 minutes east of UTC: the hours must come back shifted into UTC.
ODD_HOURS = BERLIN_HOURS.replace("<t:Bias>-60</t:Bias>", "<t:Bias>-37</t:Bias>", 1).replace(
    "<t:DaylightTime><t:Bias>-60</t:Bias>", "<t:DaylightTime><t:Bias>0</t:Bias>"
)


@pytest.fixture(scope="module")
def tls(tmp_path_factory: pytest.TempPathFactory) -> TlsMaterial:
    return make_tls_material(tmp_path_factory.mktemp("ews-tls"))


@pytest.fixture
def exchange() -> FakeExchange:
    ex = FakeExchange()
    ex.add_login(LOGIN, PASSWORD, OWN, "Sara Karimi")
    ex.add_mailbox(FINANCE, "Finance")
    ex.add_mailbox(CEO, "Chief Executive")
    ex.aliases["sara@corp.example"] = OWN
    ex.full_access["corp\\s.karimi"] = {FINANCE}
    ex.people = [
        # A near miss first: the client must rank exact matches first and check the root folder.
        FakePerson("s.karimian@corp.example", "Saeed Karimian", alias="s.karimian"),
        FakePerson(OWN, "Sara Karimi", alias="s.karimi", department="Finance", title="Analyst", office="Tehran"),
        FakePerson(FINANCE, "Finance", alias="finance"),
        FakePerson(CEO, "Chief Executive", alias="ceo", title="CEO"),
        FakePerson("sales-all@corp.example", "Sales (all)", alias="sales-all", mailbox_type="PublicDL"),
        FakePerson("sam@partner.example", "Sam Partner", alias="sam", mailbox_type="Contact"),
    ]
    return ex


@pytest.fixture
def server(exchange: FakeExchange, tls: TlsMaterial):
    with FakeEwsServer(exchange, tls.server_context) as srv:
        yield srv


def config_for(server: FakeEwsServer, tls: TlsMaterial, **overrides: object) -> EwsConfig:
    values: dict[str, object] = {
        "ews_url": server.ews_url,
        "login": LOGIN,
        "password": PASSWORD,
        "autodiscover_url": server.autodiscover_url,
        "ca_bundle_pem": tls.ca_path.read_text(),
        "timeout_s": 5,
        "auth": "basic",
    }
    values.update(overrides)
    return EwsConfig(**values)  # type: ignore[arg-type]


@pytest.fixture
def client(server: FakeEwsServer, tls: TlsMaterial):
    c = EwsClient(config_for(server, tls))
    yield c
    c.close()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _assert_clean(error: EwsError) -> None:
    """A message a person can read: no XML, no exchangelib internals, never the password."""
    assert error.message
    assert "<" not in error.message and PASSWORD not in error.message
    assert "Traceback" not in error.message and "Envelope" not in error.message


# --- who the login is ---------------------------------------------------------------------------------------------


def test_whoami_is_the_mailbox_the_login_opens(client: EwsClient, server: FakeEwsServer) -> None:
    assert client.whoami() == MailboxInfo(smtp=OWN, display_name="Sara Karimi")
    own_root = server.requests[0]
    assert own_root.operation == "GetFolder"
    assert own_root.anchor is None, "the request that names no mailbox must not name one in X-AnchorMailbox either"
    assert "Mailbox" not in own_root.body.split("FolderIds", 1)[1]
    resolve = [r for r in server.requests if r.operation == "ResolveNames"]
    assert len(resolve) == 1 and ">s.karimi<" in resolve[0].body
    # The exact match was checked first, so the near miss never was.
    checked = [r.anchor for r in server.requests if r.operation == "GetFolder" and r.anchor]
    assert checked == [OWN]
    # Asked again: nothing new goes to Exchange.
    count = len(server.requests)
    assert client.whoami().smtp == OWN
    assert len(server.requests) == count


def test_every_request_names_alpharouter_for_an_ews_allow_list(client: EwsClient, server: FakeEwsServer) -> None:
    from app.services.exchange_ews_client import USER_AGENT

    client.whoami()
    client.discover_full_access()
    assert USER_AGENT.startswith("Alpharouter-EWS/1.0 (exchangelib/")
    assert server.user_agents and set(server.user_agents) == {USER_AGENT}


def test_whoami_checks_candidates_until_the_root_folder_matches(
    exchange: FakeExchange, server: FakeEwsServer, tls: TlsMaterial
) -> None:
    # Another person's address looks exactly like the login; only the root folder tells them apart.
    exchange.add_mailbox("s.karimi.old@corp.example", "Old Sara")
    exchange.full_access["corp\\s.karimi"].add("s.karimi.old@corp.example")
    exchange.people.insert(0, FakePerson("s.karimi.old@corp.example", "Old Sara", alias="s.karimi"))
    c = EwsClient(config_for(server, tls))
    try:
        assert c.whoami() == MailboxInfo(smtp=OWN, display_name="Sara Karimi")
    finally:
        c.close()
    checked = [r.anchor for r in server.requests if r.operation == "GetFolder" and r.anchor]
    assert checked == ["s.karimi.old@corp.example", OWN]


def test_whoami_with_a_upn_login_asks_for_the_whole_upn_first(
    exchange: FakeExchange, server: FakeEwsServer, tls: TlsMaterial
) -> None:
    exchange.add_login(OWN, PASSWORD, OWN, "Sara Karimi")
    c = EwsClient(config_for(server, tls, login=OWN))
    try:
        assert c.whoami() == MailboxInfo(smtp=OWN, display_name="Sara Karimi")
    finally:
        c.close()
    resolve = [r.body for r in server.requests if r.operation == "ResolveNames"]
    asked = [body.split("<m:UnresolvedEntry>", 1)[1].split("<", 1)[0] for body in resolve]
    assert asked == [OWN], "found with the UPN: its user part is never asked about"


def test_identity_names() -> None:
    assert ews._identity_names("CORP\\s.karimi") == ["s.karimi"]
    assert ews._identity_names("s.karimi@corp.local") == ["s.karimi@corp.local", "s.karimi"]
    assert ews._identity_names("CORP\\") == []


def test_whoami_without_an_address_book_entry_is_a_server_error(exchange: FakeExchange, client: EwsClient) -> None:
    exchange.people = []
    with pytest.raises(EwsError) as caught:
        client.whoami()
    assert caught.value.kind == "server"
    _assert_clean(caught.value)


def test_whoami_with_the_account_s_email_needs_no_address_book_search_for_the_login(
    client: EwsClient, server: FakeEwsServer
) -> None:
    assert client.whoami(OWN) == MailboxInfo(smtp=OWN, display_name="Sara Karimi")
    asked = [
        r.body.split("<m:UnresolvedEntry>", 1)[1].split("<", 1)[0]
        for r in server.requests
        if r.operation == "ResolveNames"
    ]
    assert asked == [OWN], "only the hint's name is looked up, never the login"
    checked = [r.anchor for r in server.requests if r.operation == "GetFolder" and r.anchor]
    assert checked == [OWN]


def test_whoami_finds_someone_hidden_from_the_address_book_from_the_hint(
    exchange: FakeExchange, server: FakeEwsServer, tls: TlsMaterial
) -> None:
    exchange.people = []
    c = EwsClient(config_for(server, tls))
    try:
        assert c.whoami(OWN) == MailboxInfo(smtp=OWN, display_name="")
        # Later calls in the same session (Autodiscover) use it too.
        assert c.whoami() == MailboxInfo(smtp=OWN, display_name="")
    finally:
        c.close()


@pytest.mark.parametrize("hint", [FINANCE, CEO, "nobody@corp.example", "not an address"])
def test_whoami_with_a_hint_of_another_mailbox_asks_the_address_book(
    exchange: FakeExchange, server: FakeEwsServer, tls: TlsMaterial, hint: str
) -> None:
    c = EwsClient(config_for(server, tls))
    try:
        assert c.whoami(hint) == MailboxInfo(smtp=OWN, display_name="Sara Karimi")
    finally:
        c.close()
    assert any(r.operation == "ResolveNames" and ">s.karimi<" in r.body for r in server.requests)


def test_a_refused_password_is_auth_and_is_never_retried(server: FakeEwsServer, tls: TlsMaterial) -> None:
    c = EwsClient(config_for(server, tls, password="wrong-password"))
    try:
        with pytest.raises(EwsError) as caught:
            c.whoami()
    finally:
        c.close()
    assert caught.value.kind == "auth"
    assert "wrong-password" not in caught.value.message
    _assert_clean(caught.value)
    assert server.operations() == ["401"], "one attempt only: a retry could lock the AD account"


def test_same_mailbox_compares_root_folders(client: EwsClient) -> None:
    assert client.same_mailbox(OWN) is True
    assert client.same_mailbox("SARA@corp.example") is True  # another address of the same mailbox
    assert client.same_mailbox(FINANCE) is False  # Full Access, but someone else's mailbox
    assert client.same_mailbox(CEO) is False  # no access at all
    assert client.same_mailbox("nobody@corp.example") is False
    assert client.same_mailbox("not an address") is False


# --- getting there ------------------------------------------------------------------------------------------------


def test_an_untrusted_certificate_is_tls(
    server: FakeEwsServer, tls: TlsMaterial, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The environment's CA bundle must not count: only the admin page's certificates do.
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(tls.ca_path))
    monkeypatch.setenv("CURL_CA_BUNDLE", str(tls.ca_path))
    c = EwsClient(config_for(server, tls, ca_bundle_pem=""))
    try:
        with pytest.raises(EwsError) as caught:
            c.whoami()
    finally:
        c.close()
    assert caught.value.kind == "tls"
    assert "127.0.0.1" in caught.value.message
    _assert_clean(caught.value)


@pytest.mark.filterwarnings("ignore::urllib3.exceptions.InsecureRequestWarning")
def test_a_self_signed_server_is_tls_unless_verification_is_off(exchange: FakeExchange, tls: TlsMaterial) -> None:
    with FakeEwsServer(exchange, tls.self_signed_context) as srv:
        trusting_ca = EwsClient(config_for(srv, tls))
        try:
            with pytest.raises(EwsError) as caught:
                trusting_ca.whoami()
            assert caught.value.kind == "tls"
        finally:
            trusting_ca.close()
        unverified = EwsClient(config_for(srv, tls, verify_tls=False, ca_bundle_pem=""))
        try:
            assert unverified.whoami().smtp == OWN
        finally:
            unverified.close()


def test_the_extra_ca_is_added_to_the_system_store_in_a_private_file(tls: TlsMaterial) -> None:
    pem = tls.ca_path.read_text()
    path = ews._combined_bundle(pem)
    assert ews._combined_bundle(pem) == path, "written once per distinct PEM"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    content = pathlib.Path(path).read_text(encoding="utf-8")
    assert pem.strip() in content
    assert pathlib.Path(certifi.where()).read_text(encoding="utf-8").strip().splitlines()[-1] in content


def test_a_closed_port_is_unreachable(tls: TlsMaterial) -> None:
    port = _free_port()
    c = EwsClient(
        EwsConfig(
            ews_url=f"https://127.0.0.1:{port}/EWS/Exchange.asmx",
            login=LOGIN,
            password=PASSWORD,
            timeout_s=3,
            auth="basic",
        )
    )
    try:
        with pytest.raises(EwsError) as caught:
            c.whoami()
    finally:
        c.close()
    assert caught.value.kind == "unreachable"
    _assert_clean(caught.value)


def test_an_unset_address_is_invalid_without_a_request() -> None:
    c = EwsClient(EwsConfig(ews_url="", login=LOGIN, password=PASSWORD))
    with pytest.raises(EwsError) as caught:
        c.whoami()
    assert caught.value.kind == "invalid"


@pytest.mark.parametrize(
    ("setting", "value", "kind"),
    [
        ("fault_code", "ErrorServerBusy", "throttled"),
        ("http_status", 404, "server"),
        ("http_status", 403, "blocked"),
    ],
)
def test_exchange_answers_that_are_not_mail(
    exchange: FakeExchange, client: EwsClient, setting: str, value: object, kind: str
) -> None:
    setattr(exchange, setting, value)
    with pytest.raises(EwsError) as caught:
        client.search(OWN)
    assert caught.value.kind == kind
    _assert_clean(caught.value)


@pytest.mark.filterwarnings("ignore::urllib3.exceptions.InsecureRequestWarning")
def test_each_client_has_its_own_protocol_and_leaves_exchangelib_as_it_was(
    server: FakeEwsServer, tls: TlsMaterial
) -> None:
    adapter_class, timeout = BaseProtocol.HTTP_ADAPTER_CLS, Protocol.TIMEOUT
    first = EwsClient(config_for(server, tls))
    second = EwsClient(config_for(server, tls, verify_tls=False, timeout_s=9))
    try:
        assert first.whoami() == second.whoami()
        assert first._protocol is not second._protocol
        assert first._protocol.TIMEOUT == 5 and second._protocol.TIMEOUT == 9
        session = second._protocol.get_session()
        try:
            assert session.get_adapter(server.ews_url)._verify is False
        finally:
            second._protocol.release_session(session)
        assert not CachingProtocol._protocol_cache, "nothing left in exchangelib's process-wide cache"
        assert BaseProtocol.HTTP_ADAPTER_CLS is adapter_class and timeout == Protocol.TIMEOUT
    finally:
        first.close()
        second.close()


def test_ntlm_is_the_default_auth(tls: TlsMaterial) -> None:
    c = EwsClient(EwsConfig(ews_url="https://mail.corp.example/EWS/Exchange.asmx", login=LOGIN, password=PASSWORD))
    try:
        session = c._protocol.create_session()
        assert isinstance(session.auth, HttpNtlmAuth)
        session.close()
    finally:
        c.close()


def test_no_password_or_mail_text_reaches_the_log(
    exchange: FakeExchange, client: EwsClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    exchange.add_item(OWN, "Budget", sender=("boss@corp.example", "Boss"), body="SECRET-BODY-TEXT")
    client.create_draft(OWN, kind="new", body_text="ANOTHER-SECRET", to=(Address("ali@corp.example"),))
    client.search(OWN, query="Budget")
    basic = base64.b64encode(f"{LOGIN}:{PASSWORD}".encode()).decode()
    for record in caplog.records:
        text = record.getMessage()
        for secret in (PASSWORD, basic, "SECRET-BODY-TEXT", "ANOTHER-SECRET"):
            assert secret not in text, record.name


# --- reading ------------------------------------------------------------------------------------------------------


def _inbox(exchange: FakeExchange) -> dict[str, FakeItem]:
    day = datetime.datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    return {
        "old": exchange.add_item(OWN, "Old news", sender=("news@corp.example", "News"), received=day, is_read=True),
        "budget": exchange.add_item(
            OWN,
            "Approve the Q4 budget",
            sender=("Boss@Corp.Example", "The Boss"),
            to=[(OWN, "Sara Karimi"), ("Ali@corp.example", "Ali")],
            cc=[("cfo@corp.example", "CFO")],
            received=day + datetime.timedelta(days=2),
            importance="High",
            body="Please   approve\n\n\n\nthe budget by Friday.",
            attachments=[("budget.xlsx", 2048, "application/vnd.ms-excel", False), ("logo.png", 99, "image/png", True)],
            flag_status=2,
        ),
        "meeting": exchange.add_item(
            OWN,
            "Planning",
            sender=("pm@corp.example", "PM"),
            received=day + datetime.timedelta(days=3),
            item_class="IPM.Schedule.Meeting.Request",
        ),
    }


def test_search_maps_messages_newest_first_without_bodies(
    exchange: FakeExchange, client: EwsClient, server: FakeEwsServer
) -> None:
    items = _inbox(exchange)
    found = client.search(OWN)
    assert [m.subject for m in found] == ["Planning", "Approve the Q4 budget", "Old news"]
    budget = found[1]
    assert budget.item_id == items["budget"].item_id
    assert budget.change_key and budget.mailbox == OWN and budget.folder == "inbox"
    assert budget.sender == Address("boss@corp.example", "The Boss")
    assert budget.to == (Address(OWN, "Sara Karimi"), Address("ali@corp.example", "Ali"))
    assert budget.cc == (Address("cfo@corp.example", "CFO"),)
    assert budget.received == datetime.datetime(2026, 10, 22, 9, 0, tzinfo=UTC)
    assert budget.received.tzinfo is not None and budget.received.utcoffset() == datetime.timedelta(0)
    assert budget.importance == "High" and budget.has_attachments and not budget.is_read and budget.flagged
    assert budget.preview == "Please approve the budget by Friday."
    assert budget.owa_url.startswith("https://mail.corp.example/owa/?ItemID=")
    assert budget.hints == {}
    assert found[0].is_meeting_request and not budget.is_meeting_request and not found[2].flagged
    get_item = [r for r in server.requests if r.operation == "GetItem"][-1]
    assert not {"item:TextBody", "item:Body", "item:InternetMessageHeaders", "item:Attachments"} & get_item.fields
    assert "item:Preview" in get_item.fields and "ext:0x1090" in get_item.fields


def test_search_pages_and_filters_on_the_server(
    exchange: FakeExchange, client: EwsClient, server: FakeEwsServer
) -> None:
    _inbox(exchange)
    assert [m.subject for m in client.search(OWN, limit=1, offset=1)] == ["Approve the Q4 budget"]
    since = datetime.datetime(2026, 10, 21, tzinfo=UTC)
    until = datetime.datetime(2026, 10, 22, 12, tzinfo=UTC)
    assert [m.subject for m in client.search(OWN, since=since, until=until)] == ["Approve the Q4 budget"]
    assert [m.subject for m in client.search(OWN, unread_only=True)] == ["Planning", "Approve the Q4 budget"]
    find = [r for r in server.requests if r.operation == "FindItem"][-1]
    assert "Restriction" in find.body and "QueryString" not in find.body


def test_search_with_a_query_filters_dates_itself(
    exchange: FakeExchange, client: EwsClient, server: FakeEwsServer
) -> None:
    _inbox(exchange)
    exchange.add_item(OWN, "Budget draft v1", sender=("boss@corp.example", "Boss"), body="old budget", is_read=True)
    found = client.search(OWN, query="budget", since=datetime.datetime(2026, 10, 21, tzinfo=UTC))
    assert [m.subject for m in found] == ["Approve the Q4 budget"]
    find = [r for r in server.requests if r.operation == "FindItem"][-1]
    assert "QueryString" in find.body and "Restriction" not in find.body
    by_sender = client.search(OWN, sender="pm@corp.example")
    assert [m.subject for m in by_sender] == ["Planning"]
    assert 'from:"pm@corp.example"' in [r for r in server.requests if r.operation == "FindItem"][-1].body


def test_search_all_merges_inbox_subfolders_and_sent(exchange: FakeExchange, client: EwsClient) -> None:
    _inbox(exchange)
    projects = exchange.add_subfolder(OWN, "Projects")
    exchange.add_subfolder(OWN, "Contacts copy", folder_class="IPF.Contact")
    exchange.add_item(OWN, "Project kickoff", folder=projects, received=datetime.datetime(2026, 10, 23, 8, tzinfo=UTC))
    exchange.add_item(OWN, "My reply", folder="sentitems", received=datetime.datetime(2026, 10, 24, 8, tzinfo=UTC))
    exchange.add_item(OWN, "Not searched", folder="deleteditems", received=datetime.datetime(2026, 10, 25, tzinfo=UTC))
    found = client.search(OWN, folder="all")
    assert [(m.subject, m.folder) for m in found] == [
        ("My reply", "sent"),
        ("Planning", "inbox"),
        ("Project kickoff", "inbox/Projects"),
        ("Approve the Q4 budget", "inbox"),
        ("Old news", "inbox"),
    ]
    assert [m.subject for m in client.search(OWN, folder="all", limit=2, offset=1)] == ["Planning", "Project kickoff"]
    assert [m.subject for m in client.search(OWN, folder="deleted")] == ["Not searched"]


def test_a_mailbox_without_full_access_is_access_denied(client: EwsClient) -> None:
    for call in (lambda: client.search(CEO), lambda: client.check_mailbox(CEO)):
        with pytest.raises(EwsError) as caught:
            call()
        assert caught.value.kind == "access_denied"
        _assert_clean(caught.value)


def test_check_mailbox(client: EwsClient) -> None:
    assert client.check_mailbox("FINANCE@corp.example") == MailboxInfo(smtp=FINANCE, display_name="Finance")
    with pytest.raises(EwsError) as caught:
        client.check_mailbox("nobody@corp.example")
    assert caught.value.kind == "not_found"


def test_list_received_gives_new_inbox_mail_oldest_first_with_hints(
    exchange: FakeExchange, client: EwsClient, server: FakeEwsServer
) -> None:
    items = _inbox(exchange)
    items["old"].headers = [("List-Id", "<news.corp.example>"), ("Received", "from x")]
    items["budget"].headers = [("Auto-Submitted", "auto-generated"), ("Precedence", "bulk")]
    found = client.list_received(OWN, since=datetime.datetime(2026, 10, 21, tzinfo=UTC), limit=10)
    assert [m.subject for m in found] == ["Approve the Q4 budget", "Planning"]
    assert found[0].hints == {"auto-submitted": "auto-generated", "precedence": "bulk"}
    assert found[1].hints == {}
    assert "item:InternetMessageHeaders" in [r for r in server.requests if r.operation == "GetItem"][-1].fields
    everything = client.list_received(OWN, since=datetime.datetime(2026, 10, 1, tzinfo=UTC), limit=1)
    assert [m.subject for m in everything] == ["Old news"]
    assert everything[0].hints == {"list-id": "<news.corp.example>"}


def test_read_folds_and_cuts_the_body_and_lists_attachments(exchange: FakeExchange, client: EwsClient) -> None:
    items = _inbox(exchange)
    detail = client.read(OWN, items["budget"].item_id, body_chars=20)
    assert detail.body_text == "Please   approve\n\nth"
    assert detail.truncated is True
    assert [(a.name, a.size, a.content_type) for a in detail.attachments] == [
        ("budget.xlsx", 2048, "application/vnd.ms-excel")
    ]
    assert detail.summary.subject == "Approve the Q4 budget"
    whole = client.read(OWN, items["budget"].item_id)
    assert whole.body_text == "Please   approve\n\nthe budget by Friday." and whole.truncated is False
    with pytest.raises(EwsError) as caught:
        client.read(OWN, "AAMkADmissing")
    assert caught.value.kind == "not_found"


# --- drafts -------------------------------------------------------------------------------------------------------


def test_a_new_draft_is_saved_in_drafts(exchange: FakeExchange, client: EwsClient) -> None:
    draft = client.create_draft(
        OWN,
        kind="new",
        body_text="Hello Ali",
        to=(Address("Ali@corp.example", "Ali"),),
        cc=(Address("cfo@corp.example"),),
        subject="Lunch?",
    )
    stored = exchange.items[draft.item_id]
    assert stored.folder == "drafts" and stored.is_draft and stored.kind == "new"
    assert draft.subject == "Lunch?" and draft.mailbox == OWN and draft.body_text == "Hello Ali"
    assert draft.to == (Address("ali@corp.example", "Ali"),) and draft.cc == (Address("cfo@corp.example", ""),)
    assert draft.change_key == stored.change_key
    assert "EditMessageItem" in draft.owa_url
    for bad in ((), (Address("not-an-address"),)):
        with pytest.raises(EwsError) as caught:
            client.create_draft(OWN, kind="new", body_text="x", to=bad)
        assert caught.value.kind == "invalid"


def test_a_reply_is_built_by_exchange_from_the_message(exchange: FakeExchange, client: EwsClient) -> None:
    items = _inbox(exchange)
    source = items["budget"].item_id
    reply = client.create_draft(
        OWN, kind="reply", body_text="Approved.", source_item_id=source, cc=(Address("ali@corp.example"),)
    )
    stored = exchange.items[reply.item_id]
    assert stored.kind == "reply" and stored.request["subject"] is None, "Exchange makes the subject"
    assert reply.subject == "RE: Approve the Q4 budget"
    assert reply.body_text.startswith("Approved.") and "-----Original Message-----" in reply.body_text
    assert stored.request["to"] == [("boss@corp.example", "The Boss")]
    assert stored.request["cc"] == [("ali@corp.example", "")]


def test_reply_all_leaves_out_the_mailbox_itself(exchange: FakeExchange, client: EwsClient) -> None:
    items = _inbox(exchange)
    draft = client.create_draft(
        OWN,
        kind="reply_all",
        body_text="Thanks all",
        source_item_id=items["budget"].item_id,
        subject="Re: budget",
    )
    stored = exchange.items[draft.item_id]
    assert [a for a, _n in stored.request["to"]] == ["boss@corp.example", "ali@corp.example"]
    assert [a for a, _n in stored.request["cc"]] == ["cfo@corp.example"]
    assert draft.subject == "Re: budget"


def test_a_forward_needs_recipients(exchange: FakeExchange, client: EwsClient) -> None:
    items = _inbox(exchange)
    source = items["budget"].item_id
    with pytest.raises(EwsError) as caught:
        client.create_draft(OWN, kind="forward", body_text="FYI", source_item_id=source)
    assert caught.value.kind == "invalid"
    forward = client.create_draft(
        OWN, kind="forward", body_text="FYI", source_item_id=source, to=(Address("cfo@corp.example"),)
    )
    assert forward.subject == "FW: Approve the Q4 budget"
    assert exchange.items[forward.item_id].request["to"] == [("cfo@corp.example", "")]
    with pytest.raises(EwsError) as caught:
        client.create_draft(OWN, kind="reply", body_text="x")
    assert caught.value.kind == "invalid"


def test_a_draft_in_a_full_access_mailbox(exchange: FakeExchange, client: EwsClient) -> None:
    draft = client.create_draft(FINANCE, kind="new", body_text="Invoice", to=(Address("vendor@partner.example"),))
    assert exchange.items[draft.item_id].mailbox == FINANCE and draft.mailbox == FINANCE


def test_get_draft_reads_it_as_it_is_now(exchange: FakeExchange, client: EwsClient) -> None:
    draft = client.create_draft(OWN, kind="new", body_text="v1", to=(Address("ali@corp.example"),))
    exchange.items[draft.item_id].body = "v2 edited in Outlook"
    exchange.items[draft.item_id].change_key = "CQAAABYAAAB2"
    now = client.get_draft(OWN, draft.item_id)
    assert now.body_text == "v2 edited in Outlook" and now.change_key == "CQAAABYAAAB2"
    received = _inbox(exchange)["old"].item_id
    for item_id in (received, "AAMkADgone"):
        with pytest.raises(EwsError) as caught:
            client.get_draft(OWN, item_id)
        assert caught.value.kind == "not_found"


def test_send_draft_sends_exactly_what_was_read(
    exchange: FakeExchange, client: EwsClient, server: FakeEwsServer
) -> None:
    draft = client.create_draft(OWN, kind="new", body_text="Go", to=(Address("ali@corp.example"),))
    exchange.items[draft.item_id].change_key = "CQAAABYAAAB9"  # edited in Outlook since
    with pytest.raises(EwsError) as caught:
        client.send_draft(OWN, draft.item_id, draft.change_key)
    assert caught.value.kind == "conflict"
    assert "SendItem" not in server.operations()
    client.send_draft(OWN, draft.item_id, "CQAAABYAAAB9")
    assert exchange.items[draft.item_id].folder == "sentitems"
    assert 'SaveItemToFolder="true"' in [r for r in server.requests if r.operation == "SendItem"][0].body


def test_sending_as_a_mailbox_without_send_as_is_access_denied(exchange: FakeExchange, client: EwsClient) -> None:
    draft = client.create_draft(FINANCE, kind="new", body_text="Pay", to=(Address("vendor@partner.example"),))
    with pytest.raises(EwsError) as caught:
        client.send_draft(FINANCE, draft.item_id, draft.change_key)
    assert caught.value.kind == "access_denied"
    assert "Send As" in caught.value.message
    assert exchange.items[draft.item_id].is_draft
    exchange.send_as["corp\\s.karimi"] = {FINANCE}
    client.send_draft(FINANCE, draft.item_id, draft.change_key)
    assert exchange.items[draft.item_id].folder == "sentitems"


def test_delete_draft_moves_it_to_deleted_items_and_ignores_what_is_gone(
    exchange: FakeExchange, client: EwsClient
) -> None:
    draft = client.create_draft(OWN, kind="new", body_text="Never mind", to=(Address("ali@corp.example"),))
    client.delete_draft(OWN, draft.item_id)
    assert exchange.items[draft.item_id].folder == "deleteditems"
    client.delete_draft(OWN, draft.item_id)  # already gone: nothing happens
    client.delete_draft(OWN, "AAMkADnever")
    received = _inbox(exchange)["old"]
    client.delete_draft(OWN, received.item_id)
    assert received.folder == "inbox", "only drafts are ever discarded"


# --- people and calendars -----------------------------------------------------------------------------------------


def test_find_people_gives_mailboxes_from_the_address_book(client: EwsClient) -> None:
    people = client.find_people("s")
    assert [p.email for p in people] == ["s.karimian@corp.example", OWN]
    sara = people[1]
    assert (sara.name, sara.department, sara.title, sara.office) == ("Sara Karimi", "Finance", "Analyst", "Tehran")
    assert client.find_people("s", limit=1)[0].email == "s.karimian@corp.example"
    assert client.find_people("zzz") == []
    assert client.find_people("sales") == [], "a group is not a mailbox"
    assert client.find_people("sam") == [], "nor is a personal contact"
    with pytest.raises(EwsError) as caught:
        client.find_people("  ")
    assert caught.value.kind == "invalid"


def test_availability_maps_busy_times_and_working_hours(exchange: FakeExchange, client: EwsClient) -> None:
    day = datetime.datetime(2026, 10, 26, tzinfo=UTC)
    exchange.calendars[OWN] = FakeCalendar(
        events=[
            (day + datetime.timedelta(hours=10), day + datetime.timedelta(hours=11), "Tentative"),
            (day + datetime.timedelta(hours=6), day + datetime.timedelta(hours=7), "Busy"),
            (day + datetime.timedelta(hours=8), day + datetime.timedelta(hours=9), "Free"),
            (day + datetime.timedelta(hours=12), day + datetime.timedelta(hours=13), "OOF"),
            (day + datetime.timedelta(hours=14), day + datetime.timedelta(hours=15), "WorkingElsewhere"),
        ],
        working_hours_xml=TEHRAN_HOURS,
    )
    exchange.calendars[FINANCE] = FakeCalendar(working_hours_xml=BERLIN_HOURS)
    exchange.calendars[CEO] = FakeCalendar(error="ErrorNoFreeBusyAccess")
    exchange.calendars["odd@corp.example"] = FakeCalendar(working_hours_xml=ODD_HOURS)
    found = client.availability(
        [OWN, "nobody@corp.example", FINANCE, CEO, "odd@corp.example", "not an address"],
        start=day,
        end=day + datetime.timedelta(days=1),
    )
    assert [a.email for a in found] == [OWN, "nobody@corp.example", FINANCE, CEO, "odd@corp.example", "not an address"]
    mine = found[0]
    assert [(b.start.hour, b.status) for b in mine.busy] == [
        (6, "Busy"),
        (10, "Tentative"),
        (12, "OOF"),
        (14, "WorkingElsewhere"),
    ]
    assert mine.busy[0].start == day + datetime.timedelta(hours=6) and mine.busy[0].start.tzinfo is not None
    assert mine.working_hours is not None
    assert mine.working_hours.timezone == "Asia/Tehran"
    assert (mine.working_hours.days, mine.working_hours.start_minute, mine.working_hours.end_minute) == (
        (1, 2, 3, 6, 7),
        480,
        1020,
    )
    assert found[1].error == "No mailbox has this address." and found[1].busy == ()
    berlin = found[2].working_hours
    assert berlin is not None and berlin.days == (1, 2, 3, 4, 5) and berlin.start_minute == 540
    zone = zoneinfo.ZoneInfo(berlin.timezone)
    assert datetime.datetime(2026, 1, 15, tzinfo=UTC).astimezone(zone).utcoffset() == datetime.timedelta(hours=1)
    assert datetime.datetime(2026, 3, 29, 2, tzinfo=UTC).astimezone(zone).utcoffset() == datetime.timedelta(hours=2)
    assert datetime.datetime(2026, 3, 28, 12, tzinfo=UTC).astimezone(zone).utcoffset() == datetime.timedelta(hours=1)
    assert found[3].error == "Free/busy is not visible for this person."
    odd = found[4].working_hours
    assert odd is not None and odd.timezone == "UTC"
    assert (odd.start_minute, odd.end_minute) == (540 - 37, 1020 - 37)
    assert found[5].error
    with pytest.raises(EwsError) as caught:
        client.availability([OWN], start=day, end=day)
    assert caught.value.kind == "invalid"


# --- Autodiscover -------------------------------------------------------------------------------------------------


def test_autodiscover_lists_delegate_mailboxes(
    exchange: FakeExchange, client: EwsClient, server: FakeEwsServer
) -> None:
    exchange.autodiscover_delegates["corp\\s.karimi"] = [
        (FINANCE, "Finance"),
        ("HR@corp.example", "HR"),
        (OWN, "Me again"),
        (FINANCE, "Finance twice"),
    ]
    assert client.discover_full_access() == [
        MailboxInfo(smtp=FINANCE, display_name="Finance"),
        MailboxInfo(smtp="hr@corp.example", display_name="HR"),
    ]
    request = [r for r in server.requests if r.operation == "Autodiscover"][0]
    assert f"<EMailAddress>{OWN}</EMailAddress>" in request.body
    assert "responseschema/2006a" in request.body


@pytest.mark.parametrize(
    "breakage",
    ["status", "doctype", "garbage", "no_url", "other_auth"],
)
def test_autodiscover_that_fails_gives_nothing(
    exchange: FakeExchange, server: FakeEwsServer, tls: TlsMaterial, breakage: str
) -> None:
    exchange.autodiscover_delegates["corp\\s.karimi"] = [(FINANCE, "Finance")]
    overrides: dict[str, object] = {}
    if breakage == "status":
        exchange.autodiscover_status = 500
    elif breakage == "doctype":
        exchange.autodiscover_body = (
            b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e "finance@corp.example">]>'
            b"<Autodiscover><AlternativeMailbox><Type>Delegate</Type><SmtpAddress>&e;</SmtpAddress>"
            b"</AlternativeMailbox></Autodiscover>"
        )
    elif breakage == "garbage":
        exchange.autodiscover_body = b"<html><body>Sign in</body>"
    elif breakage == "no_url":
        overrides["autodiscover_url"] = ""
    elif breakage == "other_auth":
        exchange.autodiscover_status = 401
        exchange.autodiscover_www_authenticate = "Negotiate"
    c = EwsClient(config_for(server, tls, **overrides))
    try:
        assert c.discover_full_access() == []
        assert c.autodiscover_problem, "the admin's Test connection is told why"
        assert "<" not in c.autodiscover_problem and PASSWORD not in c.autodiscover_problem
    finally:
        c.close()


@pytest.mark.parametrize("offer", ['Basic realm="fake"', "Negotiate", ""])
def test_a_401_from_autodiscover_is_its_own_trouble_never_a_wrong_password(
    exchange: FakeExchange, client: EwsClient, caplog: pytest.LogCaptureFixture, offer: str
) -> None:
    """Autodiscover is asked after EWS accepted the login: another host, a load balancer ending TLS, EPA."""
    exchange.autodiscover_delegates["corp\\s.karimi"] = [(FINANCE, "Finance")]
    exchange.autodiscover_status = 401
    exchange.autodiscover_www_authenticate = offer
    with caplog.at_level(logging.INFO, logger="app.services.exchange_ews_client"):
        assert client.discover_full_access() == []
    assert "HTTP 401" in client.autodiscover_problem
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "401" in logged and PASSWORD not in logged and LOGIN not in logged


def test_an_answer_says_nothing_went_wrong(exchange: FakeExchange, client: EwsClient) -> None:
    exchange.autodiscover_delegates["corp\\s.karimi"] = [(FINANCE, "Finance")]
    exchange.autodiscover_status = 500
    assert client.discover_full_access() == []
    exchange.autodiscover_status = 200
    assert client.discover_full_access() == [MailboxInfo(smtp=FINANCE, display_name="Finance")]
    assert client.autodiscover_problem == ""


# --- the pieces without a network ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (UnauthorizedError("refused"), "auth"),
        (ErrorAccessDenied("x"), "access_denied"),
        (ErrorSendAsDenied("x"), "access_denied"),
        (ErrorNonExistentMailbox("x"), "not_found"),
        (ErrorItemNotFound("x"), "not_found"),
        (ErrorServerBusy("x"), "throttled"),
        (ErrorIrresolvableConflict("x"), "conflict"),
        (ErrorInvalidRecipients("x"), "invalid"),
        (ErrorTimeoutExpired("x"), "unreachable"),
        (TransportError("Unknown failure in response. Code: 500 headers: {} content: <soap/>"), "server"),
        (ValueError("Expected result length 1"), "server"),
    ],
)
def test_error_mapping(error: Exception, kind: str) -> None:
    mapped = ews._map_error(error, "mail.corp.example")
    assert mapped.kind == kind
    _assert_clean(mapped)


def test_a_lockout_says_so() -> None:
    mapped = ews._map_error(UnauthorizedError("locked out"), "")
    assert mapped.kind == "auth" and "locked out" in mapped.message


def test_registering_the_extra_fields_twice_is_harmless() -> None:
    ews._register_fields()
    ews._register_fields()


def test_time_zone_rules_match_iana_zones_in_both_hemispheres() -> None:
    # AUS Eastern: UTC+10, summer time from the first Sunday of October to the first Sunday of April.
    sydney = (-600, (0, datetime.time(3), 1, 4, 7), (-60, datetime.time(2), 1, 10, 7))
    name = ews._iana_zone(sydney, 2026)
    assert name is not None
    zone = zoneinfo.ZoneInfo(name)
    assert datetime.datetime(2026, 1, 15, tzinfo=UTC).astimezone(zone).utcoffset() == datetime.timedelta(hours=11)
    assert datetime.datetime(2026, 7, 15, tzinfo=UTC).astimezone(zone).utcoffset() == datetime.timedelta(hours=10)
    assert datetime.datetime(2026, 10, 3, 12, tzinfo=UTC).astimezone(zone).utcoffset() == datetime.timedelta(hours=10)
    assert ews._iana_zone((-37, None, None), 2026) is None


def test_working_hours_that_would_cross_midnight_in_utc_are_left_out() -> None:
    from types import SimpleNamespace

    odd = SimpleNamespace(bias=-37, standard_time=None, daylight_time=None)
    night = SimpleNamespace(weekdays=[1, 2], start=datetime.time(0, 10), end=datetime.time(8, 0))
    assert ews._working_hours(SimpleNamespace(working_hours=[night], working_hours_timezone=odd), 2026) is None
    early = SimpleNamespace(weekdays=[1, 7], start=datetime.time(0, 0), end=datetime.time(0, 30))
    shifted = ews._working_hours(SimpleNamespace(working_hours=[early], working_hours_timezone=odd), 2026)
    # 00:00-00:30 at UTC+0:37 is 23:23-23:53 UTC the day before: Monday -> Sunday, Sunday -> Saturday.
    assert shifted is not None and shifted.timezone == "UTC"
    assert (shifted.days, shifted.start_minute, shifted.end_minute) == ((6, 7), 1440 - 37, 1440 - 7)
