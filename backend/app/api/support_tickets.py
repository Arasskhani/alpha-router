"""The person's own tickets (Support): list, open, answer, resolve, and their images."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/support", tags=["tickets"])
