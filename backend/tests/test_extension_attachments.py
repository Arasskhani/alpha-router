"""A PDF tab read through the browser extension (D5).

The side panel cannot read Chrome's PDF viewer like a page, so it fetches the
PDF with the site's permission and has the server extract its text, as a
chat attachment - the same endpoint and limits as the web app, with the
extension's token.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.media import MediaAsset
from app.services import extension_tokens
from app.services.extension_tokens import create_session

PROCESS_URL = "/api/chat/attachments/process"


def pdf_with(text: str) -> bytes:
    """A one-page PDF whose only content is `text`, in a standard font pypdf can read."""
    stream = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


@pytest.fixture(autouse=True)
def _no_external_services(session_factory, monkeypatch):
    monkeypatch.setattr(extension_tokens, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)
    monkeypatch.setattr("app.api.chat.screen_upload", AsyncMock(return_value=None))
    monkeypatch.setattr("app.services.storage_service._put_object_once", AsyncMock(return_value=True))


async def test_a_connected_browser_has_a_pdf_read_and_kept_as_an_attachment(client, db_session, user):
    pair = await create_session(db_session, user=user, device_name="Chrome", user_agent="UA", ip="10.0.0.5")
    await db_session.commit()
    resp = await client.post(
        PROCESS_URL,
        headers={"Authorization": f"Bearer {pair.access_token}"},
        files=[("files", ("report.pdf", pdf_with("Quarterly revenue grew twelve percent"), "application/pdf"))],
    )
    assert resp.status_code == 200, resp.text
    [attachment] = resp.json()["attachments"]
    assert attachment["kind"] == "document"
    assert attachment["mime_type"] == "application/pdf"
    assert "Quarterly revenue grew twelve percent" in attachment["text"]
    # Kept in the user's Media, as a chat attachment from the web app is.
    [asset] = (await db_session.execute(select(MediaAsset).where(MediaAsset.user_id == user.id))).scalars().all()
    assert asset.file_name == "report.pdf"
