"""Atomic in-flight budget and API-key credit reservations."""

import datetime

from sqlalchemy import Column, DateTime, Integer, String

from app.database import Base, MoneyUSD


class BudgetReservation(Base):
    __tablename__ = "budget_reservations"

    id = Column(String(36), primary_key=True)
    subject_type = Column(String(16), nullable=False, index=True)  # user | alpha_router_key
    subject_id = Column(Integer, nullable=False, index=True)
    idempotency_key = Column(String(160), nullable=False, unique=True, index=True)
    operation = Column(String(32), nullable=False)
    model_id = Column(String(512), nullable=True)
    reserved_usd = Column(MoneyUSD, nullable=False)
    actual_usd = Column(MoneyUSD, nullable=True)
    status = Column(String(16), nullable=False, default="held", index=True)
    request_log_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    expires_at = Column(DateTime, nullable=False, index=True)
    settled_at = Column(DateTime, nullable=True)
