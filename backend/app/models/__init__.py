"""ORM models — import all for Alembic metadata."""

from app.models.user import User, UserGroup, user_group_members
from app.models.connection import Connection, ConnectionAuditLog
from app.models.model_catalog import AIModel
from app.models.api_key import NitroApiKey, NitroApiKeyAuditLog, UserApiKey
from app.models.budget import BudgetPlan, PlanAssignment
from app.models.logging import RequestLog
from app.models.system import SmtpSettings, ReportSchedule, SystemMetricSnapshot, SystemSetting
from app.models.auth_provider import AuthProviderConfig
from app.models.media import MediaAsset
from app.models.chat import ChatFolder, ChatMessage, ChatSession, UserChatPrefs

__all__ = [
    "User",
    "UserGroup",
    "user_group_members",
    "Connection",
    "ConnectionAuditLog",
    "AIModel",
    "NitroApiKey",
    "NitroApiKeyAuditLog",
    "UserApiKey",
    "BudgetPlan",
    "PlanAssignment",
    "RequestLog",
    "SmtpSettings",
    "ReportSchedule",
    "SystemSetting",
    "SystemMetricSnapshot",
    "AuthProviderConfig",
    "MediaAsset",
    "ChatFolder",
    "ChatMessage",
    "ChatSession",
    "UserChatPrefs",
]
