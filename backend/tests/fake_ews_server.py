"""A small Exchange server for tests of the EWS client: HTTPS on 127.0.0.1, Basic auth, SOAP from canned XML.

``app.services.exchange_ews_client.EwsClient`` runs against it end to end -
real TLS (certificates from ``tests.smtp_test_server.make_tls_material``, the
CA handed to the client as ``ca_bundle_pem``), real HTTP, and the SOAP
exchangelib really sends. It answers the operations the client uses -
GetFolder, FindFolder, FindItem, GetItem, CreateItem, SendItem, DeleteItem,
ResolveNames, GetUserAvailability - and the Autodiscover POX request at
``/autodiscover/autodiscover.xml``, from a little in-memory Exchange: logins,
mailboxes (with Full Access and Send As), messages, people and calendars.

It behaves like Exchange where the client depends on it: a request that
names no mailbox opens the login's own; another mailbox needs Full Access
(``ErrorAccessDenied``) and must exist (``ErrorNonExistentMailbox``); GetItem
returns only the properties asked for; a draft sent by another mailbox
needs Send As (``ErrorSendAsDenied``) and an up-to-date change key
(``ErrorIrresolvableConflict``). Every request is recorded (``requests``)
with its operation, the properties it asked for and its ``X-AnchorMailbox``
header, so a test can check what the client sent.

Not a general EWS implementation: restrictions are the few the client
builds (received time, read state), a query string matches words in the
subject, body and sender (plus ``from:"..."``), and sorting is by received
time only.
"""

from __future__ import annotations

import base64
import datetime
import http.server
import itertools
import ssl
import threading
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any
from xml.sax.saxutils import escape, quoteattr

SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
M = "http://schemas.microsoft.com/exchange/services/2006/messages"
T = "http://schemas.microsoft.com/exchange/services/2006/types"
ERRORS = "http://schemas.microsoft.com/exchange/services/2006/errors"
UTC = datetime.UTC

#: FieldURI of each property GetItem may be asked for, and the element it answers with.
_FIELD_ELEMENTS = {
    "item:Subject": "Subject",
    "message:From": "From",
    "message:Sender": "Sender",
    "message:ToRecipients": "ToRecipients",
    "message:CcRecipients": "CcRecipients",
    "item:DateTimeReceived": "DateTimeReceived",
    "message:IsRead": "IsRead",
    "item:HasAttachments": "HasAttachments",
    "item:Importance": "Importance",
    "item:ConversationId": "ConversationId",
    "item:ItemClass": "ItemClass",
    "item:WebClientReadFormQueryString": "WebClientReadFormQueryString",
    "item:WebClientEditFormQueryString": "WebClientEditFormQueryString",
    "item:Preview": "Preview",
    "item:TextBody": "TextBody",
    "item:Attachments": "Attachments",
    "item:InternetMessageHeaders": "InternetMessageHeaders",
    "item:IsDraft": "IsDraft",
}


def _q(tag: str, ns: str = T) -> str:
    return f"{{{ns}}}{tag}"


def _children(parent: ET.Element, tag: str) -> list[ET.Element]:
    found = parent.find(tag)
    return list(found) if found is not None else []


def _text(elem: ET.Element | None) -> str:
    return (elem.text or "").strip() if elem is not None else ""


def _iso(moment: datetime.datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(text: str) -> datetime.datetime:
    value = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@dataclass
class FakeItem:
    item_id: str
    mailbox: str
    folder: str
    subject: str
    sender: tuple[str, str] | None = None
    to: list[tuple[str, str]] = field(default_factory=list)
    cc: list[tuple[str, str]] = field(default_factory=list)
    received: datetime.datetime = datetime.datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    is_read: bool = False
    importance: str = "Normal"
    body: str = ""
    preview: str = ""
    attachments: list[tuple[str, int, str, bool]] = field(default_factory=list)
    headers: list[tuple[str, str]] = field(default_factory=list)
    item_class: str = "IPM.Note"
    flag_status: int | None = None
    is_draft: bool = False
    kind: str = ""
    change_key: str = "CQAAABYAAAA1"
    #: Recipients and subject exactly as the client sent them (drafts only).
    request: dict[str, Any] = field(default_factory=dict)


@dataclass
class FakePerson:
    email: str
    name: str
    alias: str = ""
    department: str = ""
    title: str = ""
    office: str = ""
    mailbox_type: str = "Mailbox"


@dataclass
class FakeCalendar:
    #: (start, end, BusyType) in UTC.
    events: list[tuple[datetime.datetime, datetime.datetime, str]] = field(default_factory=list)
    #: The ``<t:WorkingHours>`` inner XML (TimeZone + WorkingPeriodArray), or "" for none.
    working_hours_xml: str = ""
    #: An EWS error code to answer with instead (``ErrorNoFreeBusyAccess``, say).
    error: str = ""


@dataclass
class Recorded:
    path: str
    operation: str
    login: str
    anchor: str | None
    #: FieldURI / ExtendedFieldURI tags the request asked for (GetItem, FindItem).
    fields: set[str]
    body: str


class FakeExchange:
    """The mailbox data the server answers from; tests set it up directly."""

    def __init__(self) -> None:
        self.logins: dict[str, tuple[str, str]] = {}  # login (lower) -> (password, own smtp)
        self.mailboxes: dict[str, str] = {}  # smtp -> display name
        self.aliases: dict[str, str] = {}  # other smtp -> primary smtp
        self.full_access: dict[str, set[str]] = {}  # login -> mailboxes
        self.send_as: dict[str, set[str]] = {}  # login -> mailboxes
        self.items: dict[str, FakeItem] = {}
        self.subfolders: dict[str, list[tuple[str, str, str]]] = {}  # smtp -> [(folder id, name, class)]
        self.people: list[FakePerson] = []
        self.calendars: dict[str, FakeCalendar] = {}
        self.autodiscover_status = 200
        #: The WWW-Authenticate header of an Autodiscover 401 ("" for none).
        self.autodiscover_www_authenticate = 'Basic realm="fake"'
        self.autodiscover_body: bytes | None = None
        self.autodiscover_delegates: dict[str, list[tuple[str, str]]] = {}  # login -> [(smtp, name)]
        #: Answer every EWS request with this HTTP status (and no SOAP), e.g. 403 or 404.
        self.http_status: int | None = None
        #: Answer every EWS request with a SOAP fault of this code, e.g. ErrorServerBusy.
        self.fault_code: str | None = None
        self._ids = itertools.count(1)

    def add_login(self, login: str, password: str, smtp: str, display_name: str = "") -> None:
        self.logins[login.lower()] = (password, smtp.lower())
        self.mailboxes[smtp.lower()] = display_name

    def add_mailbox(self, smtp: str, display_name: str = "") -> None:
        self.mailboxes[smtp.lower()] = display_name

    def new_id(self) -> str:
        return f"AAMkAD{next(self._ids):06d}" + "Q" * 30

    def add_item(self, mailbox: str, subject: str, **kw: Any) -> FakeItem:
        item = FakeItem(
            item_id=self.new_id(), mailbox=mailbox.lower(), folder=kw.pop("folder", "inbox"), subject=subject, **kw
        )
        self.items[item.item_id] = item
        return item

    def add_subfolder(self, mailbox: str, name: str, folder_class: str = "IPF.Note") -> str:
        folder_id = f"F:{mailbox.lower()}:sub{len(self.subfolders.get(mailbox.lower(), [])) + 1}"
        self.subfolders.setdefault(mailbox.lower(), []).append((folder_id, name, folder_class))
        return folder_id

    def primary(self, smtp: str) -> str:
        smtp = smtp.lower()
        return self.aliases.get(smtp, smtp)


class _Error(Exception):
    """An EWS ResponseCode to answer one response message with."""

    def __init__(self, code: str, text: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.text = text or code


class FakeEwsServer:
    """``with FakeEwsServer(exchange, tls_context) as server:`` serves ``server.ews_url`` and ``server.autodiscover_url``."""

    def __init__(self, exchange: FakeExchange, tls_context: ssl.SSLContext) -> None:
        self.exchange = exchange
        self.tls_context = tls_context
        self.requests: list[Recorded] = []
        self.tls_failures = 0
        self._httpd: http.server.ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port = 0

    @property
    def ews_url(self) -> str:
        return f"https://127.0.0.1:{self.port}/EWS/Exchange.asmx"

    @property
    def autodiscover_url(self) -> str:
        return f"https://127.0.0.1:{self.port}/autodiscover/autodiscover.xml"

    def operations(self) -> list[str]:
        return [r.operation for r in self.requests]

    def __enter__(self) -> FakeEwsServer:
        server = self

        class Httpd(http.server.ThreadingHTTPServer):
            daemon_threads = True

            def finish_request(self, request: Any, client_address: Any) -> None:
                try:
                    request = server.tls_context.wrap_socket(request, server_side=True)
                except (ssl.SSLError, OSError):
                    server.tls_failures += 1
                    return
                super().finish_request(request, client_address)

            def handle_error(self, request: Any, client_address: Any) -> None:
                pass  # a client that gave up mid-request is not a test failure

        self._httpd = Httpd(("127.0.0.1", 0), _handler(self))
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        assert self._httpd is not None
        self._httpd.shutdown()
        self._httpd.server_close()

    # --- one request ---

    def login_of(self, authorization: str) -> str | None:
        """The login of a valid Basic Authorization header, or None."""
        if not authorization.lower().startswith("basic "):
            return None
        try:
            user, _, password = base64.b64decode(authorization[6:]).decode("utf-8").partition(":")
        except (ValueError, UnicodeDecodeError):
            return None
        known = self.exchange.logins.get(user.lower())
        return user.lower() if known and known[0] == password else None

    def answer_soap(self, login: str, body: bytes, anchor: str | None) -> tuple[int, bytes]:
        root = ET.fromstring(body)
        soap_body = root.find(_q("Body", SOAP))
        assert soap_body is not None and len(soap_body), "no SOAP body"
        request = soap_body[0]
        operation = request.tag.rsplit("}", 1)[-1]
        fields = {f.get("FieldURI", "") for f in request.iter(_q("FieldURI"))}
        fields |= {"ext:" + (f.get("PropertyTag") or "") for f in request.iter(_q("ExtendedFieldURI"))}
        self.requests.append(Recorded("/EWS/Exchange.asmx", operation, login, anchor, fields, body.decode("utf-8")))
        if self.exchange.fault_code:
            return 500, _envelope(_fault(self.exchange.fault_code))
        handler = getattr(self, f"_op_{operation}", None)
        assert handler is not None, f"the fake server does not know {operation}"
        return 200, _envelope(handler(login, request, fields))

    # --- helpers ---

    def _own(self, login: str) -> str:
        return self.exchange.logins[login][1]

    def _open(self, login: str, smtp: str | None) -> str:
        """The mailbox a request means, checked: the login's own when none is named."""
        if not smtp:
            return self._own(login)
        box = self.exchange.primary(smtp)
        if box not in self.exchange.mailboxes:
            raise _Error("ErrorNonExistentMailbox", "The SMTP address has no mailbox associated with it.")
        if box != self._own(login) and box not in self.exchange.full_access.get(login, set()):
            raise _Error("ErrorAccessDenied", "Access is denied. Check credentials and try again.")
        return box

    def _folder_ref(self, login: str, elem: ET.Element) -> tuple[str, str]:
        """(mailbox, folder name or id) for a FolderId / DistinguishedFolderId element."""
        if elem.tag == _q("DistinguishedFolderId"):
            mailbox = _text(elem.find(f"{_q('Mailbox')}/{_q('EmailAddress')}"))
            return self._open(login, mailbox or None), elem.get("Id", "")
        folder_id = elem.get("Id", "")
        for smtp, subs in self.exchange.subfolders.items():
            if any(sub_id == folder_id for sub_id, _n, _c in subs):
                return self._open(login, smtp), folder_id
        raise _Error("ErrorFolderNotFound")

    @staticmethod
    def _folder_id(mailbox: str, name: str) -> str:
        return name if name.startswith("F:") else f"F:{mailbox}:{name}"

    def _item(self, login: str, item_id: str) -> FakeItem:
        item = self.exchange.items.get(item_id)
        if item is None:
            raise _Error("ErrorItemNotFound", "The specified object was not found in the store.")
        self._open(login, item.mailbox)
        return item

    # --- operations ---

    def _op_GetFolder(self, login: str, request: ET.Element, fields: set[str]) -> str:
        messages = []
        for ref in _children(request, _q("FolderIds", M)):
            try:
                mailbox, name = self._folder_ref(login, ref)
                display = {"msgfolderroot": "Top of Information Store", "root": ""}.get(name, name)
                folder = (
                    f'<t:Folder><t:FolderId Id="{self._folder_id(mailbox, name)}" ChangeKey="AQAAAA=="/>'
                    f"<t:DisplayName>{escape(display)}</t:DisplayName></t:Folder>"
                )
                messages.append(_success("GetFolder", f"<m:Folders>{folder}</m:Folders>"))
            except _Error as error:
                messages.append(_failure("GetFolder", error))
        return _response("GetFolder", messages)

    def _op_FindFolder(self, login: str, request: ET.Element, fields: set[str]) -> str:
        messages = []
        for ref in _children(request, _q("ParentFolderIds", M)):
            try:
                mailbox, name = self._folder_ref(login, ref)
                subs = self.exchange.subfolders.get(mailbox, []) if name == "inbox" else []
                folders = "".join(
                    f'<t:Folder><t:FolderId Id="{sub_id}" ChangeKey="AQAAAA=="/>'
                    f'<t:ParentFolderId Id="{self._folder_id(mailbox, "inbox")}" ChangeKey="AQAAAA=="/>'
                    f"<t:FolderClass>{escape(cls)}</t:FolderClass><t:DisplayName>{escape(sub_name)}</t:DisplayName>"
                    "<t:TotalCount>0</t:TotalCount><t:ChildFolderCount>0</t:ChildFolderCount>"
                    "<t:UnreadCount>0</t:UnreadCount></t:Folder>"
                    for sub_id, sub_name, cls in subs
                )
                root = (
                    f'<m:RootFolder TotalItemsInView="{len(subs)}" IncludesLastItemInRange="true">'
                    f"<t:Folders>{folders}</t:Folders></m:RootFolder>"
                )
                messages.append(_success("FindFolder", root))
            except _Error as error:
                messages.append(_failure("FindFolder", error))
        return _response("FindFolder", messages)

    def _matches(self, item: FakeItem, request: ET.Element) -> bool:
        restriction = request.find(_q("Restriction", M))
        if restriction is not None and not self._restriction(item, restriction):
            return False
        query = _text(request.find(_q("QueryString", M)))
        if query:
            words, sender = [], ""
            for word in query.split('from:"', 1)[0].split():
                words.append(word.lower())
            if 'from:"' in query:
                sender = query.split('from:"', 1)[1].split('"', 1)[0].lower()
            haystack = f"{item.subject} {item.body} {item.sender[0] if item.sender else ''}".lower()
            if any(word not in haystack for word in words):
                return False
            if sender and (not item.sender or sender not in f"{item.sender[0]} {item.sender[1]}".lower()):
                return False
        return True

    def _restriction(self, item: FakeItem, node: ET.Element) -> bool:
        children = list(node)
        if node.tag in (_q("Restriction", M), _q("And")):
            return all(self._restriction(item, child) for child in children)
        field_uri = node.find(_q("FieldURI"))
        uri = field_uri.get("FieldURI", "") if field_uri is not None else ""
        constant = node.find(f"{_q('FieldURIOrConstant')}/{_q('Constant')}")
        value = constant.get("Value", "") if constant is not None else ""
        tag = node.tag.rsplit("}", 1)[-1]
        if uri == "item:DateTimeReceived":
            when = _parse_time(value)
            return {
                "IsGreaterThan": item.received > when,
                "IsGreaterThanOrEqualTo": item.received >= when,
                "IsLessThan": item.received < when,
                "IsLessThanOrEqualTo": item.received <= when,
            }[tag]
        if uri == "message:IsRead" and tag == "IsEqualTo":
            return item.is_read == (value in ("1", "true"))
        raise AssertionError(f"the fake server cannot apply {tag} on {uri}")

    def _op_FindItem(self, login: str, request: ET.Element, fields: set[str]) -> str:
        view = request.find(_q("IndexedPageItemView", M))
        size = int(view.get("MaxEntriesReturned", "1000")) if view is not None else 1000
        offset = int(view.get("Offset", "0")) if view is not None else 0
        order = request.find(f"{_q('SortOrder', M)}/{_q('FieldOrder')}")
        descending = order is not None and order.get("Order") == "Descending"
        messages = []
        for ref in _children(request, _q("ParentFolderIds", M)):
            try:
                mailbox, name = self._folder_ref(login, ref)
            except _Error as error:
                messages.append(_failure("FindItem", error))
                continue
            found = [
                item
                for item in self.exchange.items.values()
                if item.mailbox == mailbox and item.folder == name and self._matches(item, request)
            ]
            found.sort(key=lambda item: item.received, reverse=descending)
            page = found[offset : offset + size]
            last = offset + len(page) >= len(found)
            items = "".join(
                f"<t:{_tag(item)}>{_id(item)}<t:DateTimeReceived>{_iso(item.received)}</t:DateTimeReceived>"
                f"<t:IsRead>{str(item.is_read).lower()}</t:IsRead></t:{_tag(item)}>"
                for item in page
            )
            next_offset = "" if last else f' IndexedPagingOffset="{offset + len(page)}"'
            root = (
                f'<m:RootFolder{next_offset} TotalItemsInView="{len(found)}" '
                f'IncludesLastItemInRange="{str(last).lower()}"><t:Items>{items}</t:Items></m:RootFolder>'
            )
            messages.append(_success("FindItem", root))
        return _response("FindItem", messages)

    def _op_GetItem(self, login: str, request: ET.Element, fields: set[str]) -> str:
        messages = []
        for ref in _children(request, _q("ItemIds", M)):
            try:
                item = self._item(login, ref.get("Id", ""))
                messages.append(_success("GetItem", f"<m:Items>{_item_xml(item, fields)}</m:Items>"))
            except _Error as error:
                messages.append(_failure("GetItem", error))
        return _response("GetItem", messages)

    def _op_CreateItem(self, login: str, request: ET.Element, fields: set[str]) -> str:
        assert request.get("MessageDisposition") == "SaveOnly", "the client must never send from CreateItem"
        target = request.find(f"{_q('SavedItemFolderId', M)}/{_q('DistinguishedFolderId')}")
        assert target is not None and target.get("Id") == "drafts"
        messages = []
        try:
            mailbox, _name = self._folder_ref(login, target)
            for node in _children(request, _q("Items", M)):
                draft = self._draft_from(login, mailbox, node)
                self.exchange.items[draft.item_id] = draft
                messages.append(_success("CreateItem", f"<m:Items><t:Message>{_id(draft)}</t:Message></m:Items>"))
        except _Error as error:
            messages.append(_failure("CreateItem", error))
        return _response("CreateItem", messages)

    def _draft_from(self, login: str, mailbox: str, node: ET.Element) -> FakeItem:
        kind = {"Message": "new", "ReplyToItem": "reply", "ReplyAllToItem": "reply_all", "ForwardItem": "forward"}[
            node.tag.rsplit("}", 1)[-1]
        ]

        def boxes(tag: str) -> list[tuple[str, str]]:
            out = []
            for box in node.findall(f"{_q(tag)}/{_q('Mailbox')}"):
                out.append((_text(box.find(_q("EmailAddress"))).lower(), _text(box.find(_q("Name")))))
            return out

        to, cc = boxes("ToRecipients"), boxes("CcRecipients")
        subject_elem = node.find(_q("Subject"))
        subject = _text(subject_elem)
        body = _text(node.find(_q("Body")) if kind == "new" else node.find(_q("NewBodyContent")))
        request = {"to": list(to), "cc": list(cc), "subject": subject if subject_elem is not None else None}
        if kind != "new":
            ref = node.find(_q("ReferenceItemId"))
            source = self._item(login, ref.get("Id", "") if ref is not None else "")
            prefix = "FW: " if kind == "forward" else "RE: "
            subject = subject or prefix + source.subject
            body = f"{body}\n\n-----Original Message-----\n{source.body}"
        return FakeItem(
            item_id=self.exchange.new_id(),
            mailbox=mailbox,
            folder="drafts",
            subject=subject,
            sender=(mailbox, self.exchange.mailboxes.get(mailbox, "")),
            to=to,
            cc=cc,
            received=datetime.datetime.now(UTC).replace(microsecond=0),
            is_read=True,
            body=body,
            is_draft=True,
            kind=kind,
            change_key="CQAAABYAAAB1",
            request=request,
        )

    def _op_SendItem(self, login: str, request: ET.Element, fields: set[str]) -> str:
        messages = []
        for ref in _children(request, _q("ItemIds", M)):
            try:
                item = self._item(login, ref.get("Id", ""))
                if not item.is_draft:
                    raise _Error("ErrorItemNotFound")
                if ref.get("ChangeKey") and ref.get("ChangeKey") != item.change_key:
                    raise _Error("ErrorIrresolvableConflict", "The send or update operation could not be performed.")
                if item.mailbox != self._own(login) and item.mailbox not in self.exchange.send_as.get(login, set()):
                    raise _Error("ErrorSendAsDenied", "The account may not send on behalf of this mailbox.")
                item.folder, item.is_draft = "sentitems", False
                messages.append(_success("SendItem", ""))
            except _Error as error:
                messages.append(_failure("SendItem", error))
        return _response("SendItem", messages)

    def _op_DeleteItem(self, login: str, request: ET.Element, fields: set[str]) -> str:
        assert request.get("DeleteType") == "MoveToDeletedItems", "drafts are only ever moved to Deleted Items"
        messages = []
        for ref in _children(request, _q("ItemIds", M)):
            try:
                item = self._item(login, ref.get("Id", ""))
                item.folder, item.is_draft = "deleteditems", False
                messages.append(_success("DeleteItem", ""))
            except _Error as error:
                messages.append(_failure("DeleteItem", error))
        return _response("DeleteItem", messages)

    def _op_ResolveNames(self, login: str, request: ET.Element, fields: set[str]) -> str:
        needle = _text(request.find(_q("UnresolvedEntry", M))).lower()
        full = request.get("ReturnFullContactData") == "true"
        found = [
            person
            for person in self.exchange.people
            if needle
            and (
                needle in person.name.lower()
                or person.email.startswith(needle)
                or person.alias.lower().startswith(needle)
            )
        ]
        if not found:
            error = _Error("ErrorNameResolutionNoResults", "No results were found.")
            return _response("ResolveNames", [_failure("ResolveNames", error)])
        resolutions = "".join(_resolution(person, full) for person in found)
        code = "ErrorNameResolutionMultipleResults" if len(found) > 1 else "NoError"
        klass = "Warning" if len(found) > 1 else "Success"
        message = (
            f'<m:ResolveNamesResponseMessage ResponseClass="{klass}">'
            + ("<m:MessageText>Multiple results were found.</m:MessageText>" if len(found) > 1 else "")
            + f"<m:ResponseCode>{code}</m:ResponseCode>"
            f'<m:ResolutionSet TotalItemsInView="{len(found)}" IncludesLastItemInRange="true">{resolutions}'
            "</m:ResolutionSet></m:ResolveNamesResponseMessage>"
        )
        return _response("ResolveNames", [message])

    def _op_GetUserAvailabilityRequest(self, login: str, request: ET.Element, fields: set[str]) -> str:
        window = request.find(f"{_q('FreeBusyViewOptions')}/{_q('TimeWindow')}")
        assert window is not None
        start, end = _parse_time(_text(window.find(_q("StartTime")))), _parse_time(_text(window.find(_q("EndTime"))))
        answers = []
        for data in request.iter(_q("MailboxData")):
            address = _text(data.find(f"{_q('Email')}/{_q('Address')}")).lower()
            calendar = self.exchange.calendars.get(address)
            if calendar is None or calendar.error:
                code = calendar.error if calendar is not None else "ErrorMailRecipientNotFound"
                answers.append(
                    '<m:FreeBusyResponse><m:ResponseMessage ResponseClass="Error">'
                    f"<m:MessageText>{code}</m:MessageText><m:ResponseCode>{code}</m:ResponseCode>"
                    "</m:ResponseMessage></m:FreeBusyResponse>"
                )
                continue
            events = "".join(
                "<t:CalendarEvent>"
                f"<t:StartTime>{s.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%S')}</t:StartTime>"
                f"<t:EndTime>{e.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%S')}</t:EndTime>"
                f"<t:BusyType>{busy}</t:BusyType></t:CalendarEvent>"
                for s, e, busy in calendar.events
                if e > start and s < end
            )
            hours = (
                f"<t:WorkingHours>{calendar.working_hours_xml}</t:WorkingHours>" if calendar.working_hours_xml else ""
            )
            answers.append(
                '<m:FreeBusyResponse><m:ResponseMessage ResponseClass="Success"><m:ResponseCode>NoError</m:ResponseCode>'
                "</m:ResponseMessage><m:FreeBusyView><t:FreeBusyViewType>Detailed</t:FreeBusyViewType>"
                f"<t:CalendarEventArray>{events}</t:CalendarEventArray>{hours}</m:FreeBusyView></m:FreeBusyResponse>"
            )
        return (
            f'<m:GetUserAvailabilityResponse xmlns:m="{M}" xmlns:t="{T}">'
            f"<m:FreeBusyResponseArray>{''.join(answers)}</m:FreeBusyResponseArray></m:GetUserAvailabilityResponse>"
        )

    def answer_autodiscover(self, login: str, body: bytes) -> tuple[int, bytes, dict[str, str]]:
        root = ET.fromstring(body)
        email = _text(root.find(".//{*}EMailAddress"))
        self.requests.append(
            Recorded("/autodiscover/autodiscover.xml", "Autodiscover", login, None, set(), body.decode())
        )
        status = self.exchange.autodiscover_status
        if status == 401:
            offer = self.exchange.autodiscover_www_authenticate
            return 401, b"", ({"WWW-Authenticate": offer} if offer else {})
        if status != 200:
            return status, b"<html>error</html>", {}
        if self.exchange.autodiscover_body is not None:
            return 200, self.exchange.autodiscover_body, {}
        delegates = "".join(
            f"<AlternativeMailbox><Type>Delegate</Type><DisplayName>{escape(name)}</DisplayName>"
            f"<SmtpAddress>{escape(smtp)}</SmtpAddress><OwnerSmtpAddress>{escape(email)}</OwnerSmtpAddress>"
            "</AlternativeMailbox>"
            for smtp, name in self.exchange.autodiscover_delegates.get(login, [])
        )
        archive = (
            "<AlternativeMailbox><Type>Archive</Type><DisplayName>Online Archive</DisplayName>"
            "<SmtpAddress>archive@corp.example</SmtpAddress></AlternativeMailbox>"
        )
        xml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<Autodiscover xmlns="http://schemas.microsoft.com/exchange/autodiscover/responseschema/2006">'
            '<Response xmlns="http://schemas.microsoft.com/exchange/autodiscover/outlook/responseschema/2006a">'
            f"<User><DisplayName>Me</DisplayName><AutoDiscoverSMTPAddress>{escape(email)}</AutoDiscoverSMTPAddress></User>"
            f"<Account><AccountType>email</AccountType><Action>settings</Action>{archive}{delegates}</Account>"
            "</Response></Autodiscover>"
        )
        return 200, xml.encode("utf-8"), {}


# --- XML pieces -----------------------------------------------------------------------------------------------


def _envelope(content: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<s:Envelope xmlns:s="{SOAP}"><s:Header>'
        f'<h:ServerVersionInfo xmlns:h="{T}" MajorVersion="15" MinorVersion="2" MajorBuildNumber="1544" '
        'MinorBuildNumber="4" Version="V2017_07_11"/></s:Header>'
        f'<s:Body xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">{content}</s:Body></s:Envelope>'
    ).encode()


def _response(operation: str, messages: list[str]) -> str:
    return (
        f'<m:{operation}Response xmlns:m="{M}" xmlns:t="{T}"><m:ResponseMessages>'
        f"{''.join(messages)}</m:ResponseMessages></m:{operation}Response>"
    )


def _success(operation: str, inner: str) -> str:
    return (
        f'<m:{operation}ResponseMessage ResponseClass="Success"><m:ResponseCode>NoError</m:ResponseCode>'
        f"{inner}</m:{operation}ResponseMessage>"
    )


def _failure(operation: str, error: _Error) -> str:
    return (
        f'<m:{operation}ResponseMessage ResponseClass="Error"><m:MessageText>{escape(error.text)}</m:MessageText>'
        f"<m:ResponseCode>{error.code}</m:ResponseCode><m:DescriptiveLinkKey>0</m:DescriptiveLinkKey>"
        f"</m:{operation}ResponseMessage>"
    )


def _fault(code: str) -> str:
    return (
        f'<s:Fault><faultcode xmlns:a="{T}">a:{code}</faultcode><faultstring>{code}</faultstring>'
        f'<detail><e:ResponseCode xmlns:e="{ERRORS}">{code}</e:ResponseCode>'
        f'<e:Message xmlns:e="{ERRORS}">The server cannot service this request right now.</e:Message>'
        "</detail></s:Fault>"
    )


def _tag(item: FakeItem) -> str:
    return "MeetingRequest" if item.item_class.startswith("IPM.Schedule.Meeting.Request") else "Message"


def _id(item: FakeItem) -> str:
    return f'<t:ItemId Id="{item.item_id}" ChangeKey="{item.change_key}"/>'


def _mailbox(email: str, name: str) -> str:
    return f"<t:Mailbox><t:Name>{escape(name)}</t:Name><t:EmailAddress>{escape(email)}</t:EmailAddress></t:Mailbox>"


def _item_xml(item: FakeItem, fields: set[str]) -> str:
    """The item with only the properties asked for, as GetItem answers."""
    link = escape(f"https://mail.corp.example/owa/?ItemID={item.item_id}&exvsurl=1&viewmodel=ReadMessageItem")
    values = {
        "Subject": escape(item.subject),
        "From": _mailbox(*item.sender) if item.sender else None,
        "Sender": _mailbox(*item.sender) if item.sender else None,
        "ToRecipients": "".join(_mailbox(*a) for a in item.to) or None,
        "CcRecipients": "".join(_mailbox(*a) for a in item.cc) or None,
        "DateTimeReceived": _iso(item.received),
        "IsRead": str(item.is_read).lower(),
        "HasAttachments": str(bool(item.attachments)).lower(),
        "Importance": item.importance,
        "ItemClass": item.item_class,
        "WebClientReadFormQueryString": link,
        "WebClientEditFormQueryString": link.replace("ReadMessageItem", "EditMessageItem") if item.is_draft else None,
        "Preview": escape(" ".join(item.preview.split() or item.body.split())[:255]),
        "IsDraft": str(item.is_draft).lower(),
        "InternetMessageHeaders": "".join(
            f"<t:InternetMessageHeader HeaderName={quoteattr(name)}>{escape(value)}</t:InternetMessageHeader>"
            for name, value in item.headers
        )
        or None,
        "Attachments": "".join(
            f'<t:FileAttachment><t:AttachmentId Id="{item.item_id}-a{n}"/><t:Name>{escape(name)}</t:Name>'
            f"<t:ContentType>{escape(ctype)}</t:ContentType><t:Size>{size}</t:Size>"
            f"<t:IsInline>{str(inline).lower()}</t:IsInline></t:FileAttachment>"
            for n, (name, size, ctype, inline) in enumerate(item.attachments)
        )
        or None,
    }
    parts = [_id(item)]
    for uri, element in _FIELD_ELEMENTS.items():
        if uri not in fields:
            continue
        if element == "TextBody":
            parts.append(f'<t:TextBody BodyType="Text">{escape(item.body)}</t:TextBody>')
        elif element == "ConversationId":
            parts.append(f'<t:ConversationId Id="conv-{item.item_id[-8:]}"/>')
        elif values.get(element) is not None:
            parts.append(f"<t:{element}>{values[element]}</t:{element}>")
    if "ext:0x1090" in fields and item.flag_status is not None:
        parts.append(
            '<t:ExtendedProperty><t:ExtendedFieldURI PropertyTag="0x1090" PropertyType="Integer"/>'
            f"<t:Value>{item.flag_status}</t:Value></t:ExtendedProperty>"
        )
    return f"<t:{_tag(item)}>{''.join(parts)}</t:{_tag(item)}>"


def _resolution(person: FakePerson, full: bool) -> str:
    mailbox = (
        f"<t:Mailbox><t:Name>{escape(person.name)}</t:Name><t:EmailAddress>{escape(person.email)}</t:EmailAddress>"
        f"<t:RoutingType>SMTP</t:RoutingType><t:MailboxType>{person.mailbox_type}</t:MailboxType></t:Mailbox>"
    )
    contact = ""
    if full:
        contact = (
            f"<t:Contact><t:DisplayName>{escape(person.name)}</t:DisplayName>"
            f'<t:EmailAddresses><t:Entry Key="EmailAddress1">SMTP:{escape(person.email)}</t:Entry></t:EmailAddresses>'
            f"<t:JobTitle>{escape(person.title)}</t:JobTitle><t:Department>{escape(person.department)}</t:Department>"
            f"<t:OfficeLocation>{escape(person.office)}</t:OfficeLocation><t:Alias>{escape(person.alias)}</t:Alias>"
            "</t:Contact>"
        )
    return f"<t:Resolution>{mailbox}{contact}</t:Resolution>"


def _handler(server: FakeEwsServer) -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def _reply(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/xml; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            login = server.login_of(self.headers.get("Authorization", ""))
            path = self.path.split("?", 1)[0].lower()
            if login is None:
                server.requests.append(Recorded(path, "401", "", None, set(), ""))
                self._reply(401, b"", {"WWW-Authenticate": 'Basic realm="fake"'})
                return
            if path == "/autodiscover/autodiscover.xml":
                self._reply(*server.answer_autodiscover(login, body))
                return
            if path != "/ews/exchange.asmx":
                self._reply(404, b"")
                return
            if server.exchange.http_status:
                server.requests.append(Recorded(path, str(server.exchange.http_status), login, None, set(), ""))
                self._reply(server.exchange.http_status, b"<html>no</html>")
                return
            status, answer = server.answer_soap(login, body, self.headers.get("X-AnchorMailbox"))
            self._reply(status, answer)

    return Handler
