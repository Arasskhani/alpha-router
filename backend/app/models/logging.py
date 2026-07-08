"""Per-request API logs for admin and user dashboards."""

import datetime
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class RequestLog(Base):
    __tablename__ = "request_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=True)
    username = Column(String(255), index=True, nullable=True)
    model_id = Column(String(512), index=True, nullable=False)
    prompt_language = Column(String(32), nullable=True)  # e.g. fa, en
    source_ip = Column(String(64), nullable=True)
    source = Column(String(32), default="gateway")  # openwebui | alpha_router_key | user_key
    client_app = Column(String(128), nullable=True)  # Kilo Code, Open WebUI, etc.
    alpha_router_api_key_id = Column(Integer, ForeignKey("alpha_router_api_keys.id", ondelete="SET NULL"), index=True, nullable=True)

    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    cached_tokens = Column(Integer, default=0)
    total_cost_usd = Column(Float, default=0.0)  # from provider usage, not adjusted

    request_time = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    response_time_ms = Column(Float, default=0.0)
    success = Column(Boolean, default=True)
    error_message = Column(Text, nullable=True)

    user = relationship("User", back_populates="logs")
