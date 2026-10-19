"""Guardrails: what may leave the organisation, to where, and for whom.

Every row here is written by an administrator; nothing is created on upgrade,
so until one is, Guardrails does nothing.

- A *pattern* is what to look for: a regular expression, a word list or a list
  of domains (the built-in library lives in code, ``guardrail_patterns``).
- A *rule* says which patterns, in which channels, sent to which destinations,
  for whom, are blocked, masked or routed to a model of the administrator's
  choosing - or only recorded while the rule is tried out.
- An *event* records that a rule matched. It never holds what was found: only
  its kind, how many, and a masked hint.
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.database import Base
from app.models.knowledge import one_acl_target_constraint


class GuardrailPattern(Base):
    __tablename__ = "guardrail_patterns"
    __table_args__ = (CheckConstraint("kind IN ('regex', 'words', 'domains')", name="chk_guardrail_patterns_kind"),)

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    description = Column(String(500), nullable=True)
    kind = Column(String(16), nullable=False, default="regex")
    #: The RE2 expression (kind ``regex``).
    expression = Column(Text, nullable=True)
    #: JSON list: the words or domains (kinds ``words`` and ``domains``).
    entries_json = Column(Text, nullable=True)
    case_sensitive = Column(Boolean, nullable=False, default=False)
    normalize = Column(Boolean, nullable=False, default=True)
    context_words_json = Column(Text, nullable=True)
    context_window = Column(Integer, nullable=False, default=50)
    validator = Column(String(32), nullable=True)
    never_match_json = Column(Text, nullable=True)
    redact_label = Column(String(32), nullable=False, default="REDACTED")
    must_match_json = Column(Text, nullable=True)
    must_not_match_json = Column(Text, nullable=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    updated_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class GuardrailRule(Base):
    __tablename__ = "guardrail_rules"
    __table_args__ = (
        CheckConstraint("mode IN ('off', 'monitor', 'enforce')", name="chk_guardrail_rules_mode"),
        CheckConstraint("action IN ('block', 'redact', 'route')", name="chk_guardrail_rules_action"),
        CheckConstraint("match_mode IN ('any', 'all')", name="chk_guardrail_rules_match_mode"),
        CheckConstraint("access_type IN ('public', 'private')", name="chk_guardrail_rules_access_type"),
    )

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    description = Column(String(500), nullable=True)
    #: ``off``, ``monitor`` (record what it would do) or ``enforce``.
    mode = Column(String(16), nullable=False, default="off")
    #: Rules are listed, and evaluated, in this order.
    position = Column(Integer, nullable=False, default=0, index=True)
    #: JSON list of pattern refs: ``lib:<key>`` or ``custom:<id>``.
    patterns_json = Column(Text, nullable=False, default="[]")
    match_mode = Column(String(8), nullable=False, default="any")
    min_matches = Column(Integer, nullable=False, default=1)
    #: JSON list of channels (guardrail_policy.CHANNELS).
    channels_json = Column(Text, nullable=False, default="[]")
    #: JSON list of trust levels the rule watches; empty: every destination.
    destinations_json = Column(Text, nullable=False, default="[]")
    action = Column(String(16), nullable=False, default="block")
    route_model_id = Column(Integer, ForeignKey("ai_models.id", ondelete="SET NULL"), nullable=True)
    #: What the person is told when the rule acts on their message.
    user_message = Column(Text, nullable=True)
    #: Who the rule applies to: ``public`` (everyone, but the denied) or ``private`` (only the allowed).
    access_type = Column(String(16), nullable=False, default="public")
    acl_version = Column(Integer, nullable=False, default=0)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    updated_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class GuardrailRuleAssignment(Base):
    """Allow or deny one principal a rule's application, as for any other access-controlled thing."""

    __tablename__ = "guardrail_rule_assignments"
    __table_args__ = (
        one_acl_target_constraint("chk_guardrail_rule_access_one_target"),
        CheckConstraint("effect IN ('allow', 'deny')", name="chk_guardrail_rule_access_effect"),
        UniqueConstraint("rule_id", "user_id", "effect", name="uq_guardrail_rule_access_user_effect"),
        UniqueConstraint("rule_id", "group_id", "effect", name="uq_guardrail_rule_access_group_effect"),
        UniqueConstraint("rule_id", "department", "effect", name="uq_guardrail_rule_access_department_effect"),
        UniqueConstraint("rule_id", "role_slug", "effect", name="uq_guardrail_rule_access_role_effect"),
    )

    id = Column(Integer, primary_key=True)
    rule_id = Column(Integer, ForeignKey("guardrail_rules.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    group_id = Column(Integer, ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=True, index=True)
    department = Column(String(255), nullable=True)
    role_slug = Column(String(64), nullable=True)
    effect = Column(String(8), nullable=False, default="allow")
    assigned_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assigned_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class GuardrailEvent(Base):
    __tablename__ = "guardrail_events"
    __table_args__ = (
        Index("ix_guardrail_events_action_created", "action", "created_at"),
        Index("ix_guardrail_events_rule_created", "rule_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)
    rule_id = Column(Integer, ForeignKey("guardrail_rules.id", ondelete="SET NULL"), nullable=True)
    rule_name = Column(String(120), nullable=True)
    rule_version = Column(Integer, nullable=True)
    #: ``block``, ``redact``, ``route``, ``monitor`` (what a monitored rule would have done is in
    #: ``intended_action``) or ``engine_error``.
    action = Column(String(16), nullable=False)
    intended_action = Column(String(16), nullable=True)
    channel = Column(String(32), nullable=False)
    destination = Column(String(160), nullable=True)
    destination_trust = Column(String(16), nullable=True)
    connection_id = Column(Integer, ForeignKey("connections.id", ondelete="SET NULL"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    username = Column(String(255), nullable=True)
    alpha_router_api_key_id = Column(
        Integer, ForeignKey("alpha_router_api_keys.id", ondelete="SET NULL"), nullable=True
    )
    source = Column(String(32), nullable=True)
    model_ref = Column(String(255), nullable=True)
    match_count = Column(Integer, nullable=False, default=0)
    #: JSON: ``[{"ref", "name", "count", "hints": [...]}]`` - never the values found.
    findings_json = Column(Text, nullable=True)
    #: What the person was shown, as the rule said it.
    message = Column(Text, nullable=True)
