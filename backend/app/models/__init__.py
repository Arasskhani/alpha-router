"""ORM models — import all for Alembic metadata."""

from app.models.user import User, UserGroup, user_group_members
from app.models.connection import Connection, ConnectionAuditLog
from app.models.model_catalog import AIModel, ModelAccessAssignment
from app.models.api_key import AlphaRouterApiKey, AlphaRouterApiKeyAuditLog, UserApiKey
from app.models.budget import BudgetPlan, PlanAssignment
from app.models.logging import ImageGenerationAttempt, RequestLog
from app.models.budget_reservation import BudgetReservation
from app.models.cost_accounting import (
    CostLineItem,
    LedgerEntry,
    PricingSnapshot,
    ReconciliationRun,
    UsageEvent,
    UsageOperation,
)
from app.models.system import SmtpSettings, ReportSchedule, SystemMetricSnapshot, SystemSetting
from app.models.auth_provider import AuthProviderConfig
from app.models.media import MediaAsset
from app.models.chat import ChatFolder, ChatMessage, ChatMessageFeedback, ChatSession, UserChatPrefs

__all__ = [
    "User",
    "UserGroup",
    "user_group_members",
    "Connection",
    "ConnectionAuditLog",
    "AIModel",
    "ModelAccessAssignment",
    "AlphaRouterApiKey",
    "AlphaRouterApiKeyAuditLog",
    "UserApiKey",
    "BudgetPlan",
    "PlanAssignment",
    "RequestLog",
    "ImageGenerationAttempt",
    "BudgetReservation",
    "PricingSnapshot",
    "UsageOperation",
    "UsageEvent",
    "CostLineItem",
    "LedgerEntry",
    "ReconciliationRun",
    "SmtpSettings",
    "ReportSchedule",
    "SystemSetting",
    "SystemMetricSnapshot",
    "AuthProviderConfig",
    "MediaAsset",
    "ChatFolder",
    "ChatMessage",
    "ChatMessageFeedback",
    "ChatSession",
    "UserChatPrefs",
]
