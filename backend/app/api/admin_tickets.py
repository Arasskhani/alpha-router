"""Admin › Tickets: the queue, a ticket, assignment, settings and deleting."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/admin/tickets", tags=["tickets"])
