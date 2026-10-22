"""``GET /api/admin/storage`` feeds the Retention Policy page, which shows the Tickets window read-only."""

from __future__ import annotations

from app.api.admin import get_storage_overview
from app.services import support_tickets as st


async def test_the_page_receives_the_tickets_window(db_session, admin):
    stats = await get_storage_overview(db=db_session, _=admin)
    assert stats["tickets"] == {"retention_days": 365}

    await st.save_settings(db_session, st.TicketSettings(retention_days=0))
    await db_session.commit()
    stats = await get_storage_overview(db=db_session, _=admin)
    assert stats["tickets"] == {"retention_days": 0}
