"""Admin › Tickets › Overview: how tickets came in, ended and wait, for a period."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/admin/tickets", tags=["tickets"])
