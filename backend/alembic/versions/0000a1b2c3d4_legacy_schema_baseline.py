"""Legacy schema baseline.

Revision ID: 0000a1b2c3d4
Revises: (root)
Create Date: 2026-09-14

Phase 4.3: the forty tables that were bootstrapped by ``Base.metadata.create_all``
plus ``db_migrate.apply_schema_column_patches`` now have a versioned
definition. This revision is the new *root* of the chain:

* A fresh database runs it first and gets every legacy table, then the
  existing revisions run on top (all of them check for what already exists,
  so a table created here with its full current column set is fine).
* An existing installation is already at a descendant revision, so Alembic
  treats this one as applied and never executes it. Tables that exist are
  skipped anyway (``if name not in existing``).

The definitions are frozen as of this revision; do not edit them to follow
the ORM — write a new revision instead. ``tests/test_schema_baseline.py``
fails when the ORM and the migration chain disagree.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0000a1b2c3d4"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    created: set[str] = set()

    if "auth_providers" not in existing:
        created.add("auth_providers")
        op.create_table('auth_providers',
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=True),
        sa.Column('config_json', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('provider')
        )
    if "budget_plans" not in existing:
        created.add("budget_plans")
        op.create_table('budget_plans',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('monthly_budget_usd', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
        )
    if "budget_reservations" not in existing:
        created.add("budget_reservations")
        op.create_table('budget_reservations',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('subject_type', sa.String(length=16), nullable=False),
        sa.Column('subject_id', sa.Integer(), nullable=False),
        sa.Column('idempotency_key', sa.String(length=160), nullable=False),
        sa.Column('operation', sa.String(length=32), nullable=False),
        sa.Column('model_id', sa.String(length=512), nullable=True),
        sa.Column('reserved_usd', sa.Float(), nullable=False),
        sa.Column('actual_usd', sa.Float(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('request_log_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('settled_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
        )
    if "budget_reservations" in created:
        op.create_index(op.f('ix_budget_reservations_expires_at'), 'budget_reservations', ['expires_at'], unique=False)
    if "budget_reservations" in created:
        op.create_index(op.f('ix_budget_reservations_idempotency_key'), 'budget_reservations', ['idempotency_key'], unique=True)
    if "budget_reservations" in created:
        op.create_index(op.f('ix_budget_reservations_status'), 'budget_reservations', ['status'], unique=False)
    if "budget_reservations" in created:
        op.create_index(op.f('ix_budget_reservations_subject_id'), 'budget_reservations', ['subject_id'], unique=False)
    if "budget_reservations" in created:
        op.create_index(op.f('ix_budget_reservations_subject_type'), 'budget_reservations', ['subject_type'], unique=False)
    if "connections" not in existing:
        created.add("connections")
        op.create_table('connections',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('provider_type', sa.String(length=64), nullable=False),
        sa.Column('adapter_key', sa.String(length=64), nullable=True),
        sa.Column('api_key_encrypted', sa.Text(), nullable=False),
        sa.Column('base_url', sa.String(length=512), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('sync_enabled', sa.Boolean(), nullable=True),
        sa.Column('sync_interval_hours', sa.Integer(), nullable=True),
        sa.Column('last_sync_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
        )
    if "connections" in created:
        op.create_index(op.f('ix_connections_adapter_key'), 'connections', ['adapter_key'], unique=False)
    if "connections" in created:
        op.create_index(op.f('ix_connections_provider_type'), 'connections', ['provider_type'], unique=False)
    if "report_schedules" not in existing:
        created.add("report_schedules")
        op.create_table('report_schedules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('owner_user_id', sa.Integer(), nullable=True),
        sa.Column('report_type', sa.String(length=64), nullable=False),
        sa.Column('cron_expression', sa.String(length=128), nullable=False),
        sa.Column('recipients', sa.Text(), nullable=False),
        sa.Column('parameters_json', sa.Text(), nullable=True),
        sa.Column('format', sa.String(length=16), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('last_run_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
        )
    if "smtp_settings" not in existing:
        created.add("smtp_settings")
        op.create_table('smtp_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('host', sa.String(length=255), nullable=False),
        sa.Column('port', sa.Integer(), nullable=True),
        sa.Column('username', sa.String(length=255), nullable=True),
        sa.Column('password_encrypted', sa.Text(), nullable=True),
        sa.Column('from_address', sa.String(length=255), nullable=False),
        sa.Column('use_tls', sa.Boolean(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
        )
    if "system_metric_snapshots" not in existing:
        created.add("system_metric_snapshots")
        op.create_table('system_metric_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('recorded_at', sa.DateTime(), nullable=True),
        sa.Column('db_engine', sa.String(length=32), nullable=True),
        sa.Column('host_cpu_percent', sa.Float(), nullable=True),
        sa.Column('host_memory_percent', sa.Float(), nullable=True),
        sa.Column('process_cpu_percent', sa.Float(), nullable=True),
        sa.Column('process_rss_bytes', sa.Integer(), nullable=True),
        sa.Column('db_ping_ms', sa.Float(), nullable=True),
        sa.Column('db_size_bytes', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id')
        )
    if "system_metric_snapshots" in created:
        op.create_index(op.f('ix_system_metric_snapshots_recorded_at'), 'system_metric_snapshots', ['recorded_at'], unique=False)
    if "system_settings" not in existing:
        created.add("system_settings")
        op.create_table('system_settings',
        sa.Column('key', sa.String(length=128), nullable=False),
        sa.Column('value', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('key')
        )
    if "user_groups" not in existing:
        created.add("user_groups")
        op.create_table('user_groups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('source', sa.String(length=32), nullable=True),
        sa.Column('external_id', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', 'source', name='uq_group_name_source')
        )
    if "user_groups" in created:
        op.create_index(op.f('ix_user_groups_external_id'), 'user_groups', ['external_id'], unique=False)
    if "user_groups" in created:
        op.create_index(op.f('ix_user_groups_name'), 'user_groups', ['name'], unique=False)
    if "user_groups" in created:
        op.create_index(op.f('ix_user_groups_source'), 'user_groups', ['source'], unique=False)
    if "users" not in existing:
        created.add("users")
        op.create_table('users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=255), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('display_name', sa.String(length=255), nullable=True),
        sa.Column('hashed_password', sa.String(length=255), nullable=True),
        sa.Column('auth_provider', sa.String(length=32), nullable=True),
        sa.Column('external_id', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('token_version', sa.Integer(), server_default='0', nullable=False),
        sa.Column('company', sa.String(length=255), nullable=True),
        sa.Column('job_title', sa.String(length=255), nullable=True),
        sa.Column('department', sa.String(length=255), nullable=True),
        sa.Column('office', sa.String(length=255), nullable=True),
        sa.Column('reporting_to', sa.String(length=255), nullable=True),
        sa.Column('monthly_budget_usd', sa.Float(), nullable=True),
        sa.Column('budget_used_usd', sa.Float(), nullable=True),
        sa.Column('budget_reserved_usd', sa.Float(), server_default='0', nullable=False),
        sa.Column('budget_period_start', sa.DateTime(), nullable=True),
        sa.Column('totp_secret_encrypted', sa.Text(), nullable=True),
        sa.Column('totp_enabled', sa.Boolean(), nullable=False),
        sa.Column('totp_backup_codes_hashed', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('last_login_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
        )
    if "users" in created:
        op.create_index(op.f('ix_users_deleted_at'), 'users', ['deleted_at'], unique=False)
    if "users" in created:
        op.create_index(op.f('ix_users_department'), 'users', ['department'], unique=False)
    if "users" in created:
        op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    if "users" in created:
        op.create_index(op.f('ix_users_external_id'), 'users', ['external_id'], unique=False)
    if "users" in created:
        op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
    if "ai_models" not in existing:
        created.add("ai_models")
        op.create_table('ai_models',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('connection_id', sa.Integer(), nullable=True),
        sa.Column('external_id', sa.String(length=512), nullable=False),
        sa.Column('display_name', sa.String(length=512), nullable=True),
        sa.Column('provider_type', sa.String(length=64), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), nullable=True),
        sa.Column('admin_disabled', sa.Boolean(), nullable=False),
        sa.Column('access_type', sa.String(length=16), nullable=False),
        sa.Column('is_image_model', sa.Boolean(), nullable=True),
        sa.Column('is_video_model', sa.Boolean(), nullable=True),
        sa.Column('input_cost_per_1k', sa.Float(), nullable=True),
        sa.Column('output_cost_per_1k', sa.Float(), nullable=True),
        sa.Column('pricing_unit', sa.String(length=16), nullable=True),
        sa.Column('pricing_raw', sa.Text(), nullable=True),
        sa.Column('context_length', sa.Integer(), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('first_seen_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['connection_id'], ['connections.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
    if "ai_models" in created:
        op.create_index(op.f('ix_ai_models_connection_id'), 'ai_models', ['connection_id'], unique=False)
    if "ai_models" in created:
        op.create_index(op.f('ix_ai_models_external_id'), 'ai_models', ['external_id'], unique=False)
    if "ai_models" in created:
        op.create_index(op.f('ix_ai_models_first_seen_at'), 'ai_models', ['first_seen_at'], unique=False)
    if "alpha_router_api_keys" not in existing:
        created.add("alpha_router_api_keys")
        op.create_table('alpha_router_api_keys',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('key_prefix', sa.String(length=16), nullable=False),
        sa.Column('key_hash', sa.String(length=128), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('owner_user_id', sa.Integer(), nullable=True),
        sa.Column('credit_limit_usd', sa.Float(), nullable=True),
        sa.Column('unlimited_budget', sa.Boolean(), nullable=True),
        sa.Column('reset_period', sa.String(length=16), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('period_used_usd', sa.Float(), nullable=True),
        sa.Column('period_reserved_usd', sa.Float(), server_default='0', nullable=False),
        sa.Column('total_used_usd', sa.Float(), nullable=True),
        sa.Column('period_started_at', sa.DateTime(), nullable=True),
        sa.Column('restrict_connections', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('restrict_models', sa.Boolean(), server_default='0', nullable=False),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key_hash')
        )
    if "alpha_router_api_keys" in created:
        op.create_index(op.f('ix_alpha_router_api_keys_owner_user_id'), 'alpha_router_api_keys', ['owner_user_id'], unique=False)
    if "chat_folders" not in existing:
        created.add("chat_folders")
        op.create_table('chat_folders',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('color', sa.String(length=32), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
    if "chat_folders" in created:
        op.create_index(op.f('ix_chat_folders_user_id'), 'chat_folders', ['user_id'], unique=False)
    if "connection_audit_logs" not in existing:
        created.add("connection_audit_logs")
        op.create_table('connection_audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('connection_id', sa.Integer(), nullable=False),
        sa.Column('actor_user_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(length=32), nullable=False),
        sa.Column('changes_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['connection_id'], ['connections.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
    if "connection_audit_logs" in created:
        op.create_index(op.f('ix_connection_audit_logs_connection_id'), 'connection_audit_logs', ['connection_id'], unique=False)
    if "image_generation_attempts" not in existing:
        created.add("image_generation_attempts")
        op.create_table('image_generation_attempts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('request_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('project_id', sa.String(length=36), nullable=True),
        sa.Column('requested_model', sa.String(length=512), nullable=False),
        sa.Column('model_id', sa.String(length=512), nullable=False),
        sa.Column('operation', sa.String(length=32), nullable=False),
        sa.Column('attempt_index', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('response_time_ms', sa.Float(), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('outcome', sa.String(length=32), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
        )
    if "image_generation_attempts" in created:
        op.create_index(op.f('ix_image_generation_attempts_model_id'), 'image_generation_attempts', ['model_id'], unique=False)
    if "image_generation_attempts" in created:
        op.create_index('ix_image_generation_attempts_model_time', 'image_generation_attempts', ['model_id', 'started_at'], unique=False)
    if "image_generation_attempts" in created:
        op.create_index(op.f('ix_image_generation_attempts_project_id'), 'image_generation_attempts', ['project_id'], unique=False)
    if "image_generation_attempts" in created:
        op.create_index(op.f('ix_image_generation_attempts_request_id'), 'image_generation_attempts', ['request_id'], unique=False)
    if "image_generation_attempts" in created:
        op.create_index(op.f('ix_image_generation_attempts_started_at'), 'image_generation_attempts', ['started_at'], unique=False)
    if "image_generation_attempts" in created:
        op.create_index(op.f('ix_image_generation_attempts_user_id'), 'image_generation_attempts', ['user_id'], unique=False)
    if "media_assets" not in existing:
        created.add("media_assets")
        op.create_table('media_assets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('mime_type', sa.String(length=128), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('storage_path', sa.Text(), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('source_model', sa.String(length=512), nullable=True),
        sa.Column('source_prompt', sa.Text(), nullable=True),
        sa.Column('chat_session_id', sa.String(length=128), nullable=True),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
    if "media_assets" in created:
        op.create_index(op.f('ix_media_assets_content_hash'), 'media_assets', ['content_hash'], unique=False)
    if "media_assets" in created:
        op.create_index(op.f('ix_media_assets_user_id'), 'media_assets', ['user_id'], unique=False)
    if "plan_assignments" not in existing:
        created.add("plan_assignments")
        op.create_table('plan_assignments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('plan_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('group_id', sa.Integer(), nullable=True),
        sa.Column('department', sa.String(length=255), nullable=True),
        sa.Column('assigned_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['group_id'], ['user_groups.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['plan_id'], ['budget_plans.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
    if "plan_assignments" in created:
        op.create_index(op.f('ix_plan_assignments_department'), 'plan_assignments', ['department'], unique=False)
    if "plan_assignments" in created:
        op.create_index(op.f('ix_plan_assignments_group_id'), 'plan_assignments', ['group_id'], unique=False)
    if "plan_assignments" in created:
        op.create_index(op.f('ix_plan_assignments_plan_id'), 'plan_assignments', ['plan_id'], unique=False)
    if "plan_assignments" in created:
        op.create_index(op.f('ix_plan_assignments_user_id'), 'plan_assignments', ['user_id'], unique=False)
    if "pricing_snapshots" not in existing:
        created.add("pricing_snapshots")
        op.create_table('pricing_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('connection_id', sa.Integer(), nullable=True),
        sa.Column('provider_type', sa.String(length=64), nullable=False),
        sa.Column('model_id', sa.String(length=512), nullable=True),
        sa.Column('service_type', sa.String(length=32), nullable=False),
        sa.Column('currency', sa.String(length=8), nullable=False),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('fingerprint', sa.String(length=64), nullable=False),
        sa.Column('active_scope_key', sa.String(length=64), nullable=True),
        sa.Column('pricing_json', sa.Text(), nullable=False),
        sa.Column('effective_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['connection_id'], ['connections.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('fingerprint', name='uq_pricing_snapshots_fingerprint')
        )
    if "pricing_snapshots" in created:
        op.create_index(op.f('ix_pricing_snapshots_active_scope_key'), 'pricing_snapshots', ['active_scope_key'], unique=True)
    if "pricing_snapshots" in created:
        op.create_index(op.f('ix_pricing_snapshots_connection_id'), 'pricing_snapshots', ['connection_id'], unique=False)
    if "pricing_snapshots" in created:
        op.create_index(op.f('ix_pricing_snapshots_effective_at'), 'pricing_snapshots', ['effective_at'], unique=False)
    if "pricing_snapshots" in created:
        op.create_index(op.f('ix_pricing_snapshots_model_id'), 'pricing_snapshots', ['model_id'], unique=False)
    if "pricing_snapshots" in created:
        op.create_index('ix_pricing_snapshots_provider_model_effective', 'pricing_snapshots', ['provider_type', 'model_id', 'effective_at'], unique=False)
    if "pricing_snapshots" in created:
        op.create_index(op.f('ix_pricing_snapshots_provider_type'), 'pricing_snapshots', ['provider_type'], unique=False)
    if "pricing_snapshots" in created:
        op.create_index(op.f('ix_pricing_snapshots_service_type'), 'pricing_snapshots', ['service_type'], unique=False)
    if "reconciliation_runs" not in existing:
        created.add("reconciliation_runs")
        op.create_table('reconciliation_runs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('connection_id', sa.Integer(), nullable=True),
        sa.Column('provider_type', sa.String(length=64), nullable=False),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('period_start', sa.DateTime(), nullable=True),
        sa.Column('period_end', sa.DateTime(), nullable=True),
        sa.Column('expected_cost_usd', sa.Numeric(precision=20, scale=12), nullable=False),
        sa.Column('reported_cost_usd', sa.Numeric(precision=20, scale=12), nullable=False),
        sa.Column('adjustment_usd', sa.Numeric(precision=20, scale=12), nullable=False),
        sa.Column('matched_event_count', sa.Integer(), nullable=False),
        sa.Column('unmatched_event_count', sa.Integer(), nullable=False),
        sa.Column('raw_summary_json', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['connection_id'], ['connections.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
        )
    if "reconciliation_runs" in created:
        op.create_index(op.f('ix_reconciliation_runs_connection_id'), 'reconciliation_runs', ['connection_id'], unique=False)
    if "reconciliation_runs" in created:
        op.create_index('ix_reconciliation_runs_provider_time', 'reconciliation_runs', ['provider_type', 'started_at'], unique=False)
    if "reconciliation_runs" in created:
        op.create_index(op.f('ix_reconciliation_runs_provider_type'), 'reconciliation_runs', ['provider_type'], unique=False)
    if "reconciliation_runs" in created:
        op.create_index(op.f('ix_reconciliation_runs_started_at'), 'reconciliation_runs', ['started_at'], unique=False)
    if "reconciliation_runs" in created:
        op.create_index(op.f('ix_reconciliation_runs_status'), 'reconciliation_runs', ['status'], unique=False)
    if "user_api_keys" not in existing:
        created.add("user_api_keys")
        op.create_table('user_api_keys',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('key_prefix', sa.String(length=16), nullable=False),
        sa.Column('key_hash', sa.String(length=128), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key_hash')
        )
    if "user_api_keys" in created:
        op.create_index(op.f('ix_user_api_keys_user_id'), 'user_api_keys', ['user_id'], unique=False)
    if "user_chat_prefs" not in existing:
        created.add("user_chat_prefs")
        op.create_table('user_chat_prefs',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('prefs', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id')
        )
    if "user_group_members" not in existing:
        created.add("user_group_members")
        op.create_table('user_group_members',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('group_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['group_id'], ['user_groups.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'group_id')
        )
    if "user_media_preferences" not in existing:
        created.add("user_media_preferences")
        op.create_table('user_media_preferences',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('cleanup_enabled', sa.Boolean(), nullable=False),
        sa.Column('cleanup_retention_days', sa.Integer(), nullable=False),
        sa.Column('cleanup_hour', sa.Integer(), nullable=False),
        sa.Column('cleanup_minute', sa.Integer(), nullable=False),
        sa.Column('last_cleanup_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id')
        )
    if "user_role_assignments" not in existing:
        created.add("user_role_assignments")
        op.create_table('user_role_assignments',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('role_slug', sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'role_slug')
        )
    if "alpha_router_api_key_audit_logs" not in existing:
        created.add("alpha_router_api_key_audit_logs")
        op.create_table('alpha_router_api_key_audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('alpha_router_api_key_id', sa.Integer(), nullable=True),
        sa.Column('actor_user_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(length=32), nullable=False),
        sa.Column('changes_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['alpha_router_api_key_id'], ['alpha_router_api_keys.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
    if "alpha_router_api_key_audit_logs" in created:
        op.create_index(op.f('ix_alpha_router_api_key_audit_logs_actor_user_id'), 'alpha_router_api_key_audit_logs', ['actor_user_id'], unique=False)
    if "alpha_router_api_key_audit_logs" in created:
        op.create_index(op.f('ix_alpha_router_api_key_audit_logs_alpha_router_api_key_id'), 'alpha_router_api_key_audit_logs', ['alpha_router_api_key_id'], unique=False)
    if "alpha_router_api_key_audit_logs" in created:
        op.create_index(op.f('ix_alpha_router_api_key_audit_logs_created_at'), 'alpha_router_api_key_audit_logs', ['created_at'], unique=False)
    if "alpha_router_api_key_connections" not in existing:
        created.add("alpha_router_api_key_connections")
        op.create_table('alpha_router_api_key_connections',
        sa.Column('alpha_router_api_key_id', sa.Integer(), nullable=False),
        sa.Column('connection_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['alpha_router_api_key_id'], ['alpha_router_api_keys.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['connection_id'], ['connections.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('alpha_router_api_key_id', 'connection_id')
        )
    if "alpha_router_api_key_connections" in created:
        op.create_index(op.f('ix_alpha_router_api_key_connections_connection_id'), 'alpha_router_api_key_connections', ['connection_id'], unique=False)
    if "alpha_router_api_key_models" not in existing:
        created.add("alpha_router_api_key_models")
        op.create_table('alpha_router_api_key_models',
        sa.Column('alpha_router_api_key_id', sa.Integer(), nullable=False),
        sa.Column('model_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['alpha_router_api_key_id'], ['alpha_router_api_keys.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['model_id'], ['ai_models.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('alpha_router_api_key_id', 'model_id')
        )
    if "alpha_router_api_key_models" in created:
        op.create_index(op.f('ix_alpha_router_api_key_models_model_id'), 'alpha_router_api_key_models', ['model_id'], unique=False)
    if "chat_sessions" not in existing:
        created.add("chat_sessions")
        op.create_table('chat_sessions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=512), nullable=False),
        sa.Column('folder_id', sa.String(length=36), nullable=True),
        sa.Column('model_id', sa.String(length=512), nullable=False),
        sa.Column('current_agent_id', sa.String(length=36), nullable=True),
        sa.Column('current_agent_version_id', sa.String(length=36), nullable=True),
        sa.Column('agent_selected_at', sa.DateTime(), nullable=True),
        sa.Column('tools', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('private_mode', sa.Boolean(), nullable=False),
        sa.Column('title_locked', sa.Boolean(), nullable=False),
        sa.Column('title_generated', sa.Boolean(), nullable=False),
        sa.Column('tools_touched', sa.Boolean(), nullable=False),
        sa.Column('message_count', sa.Integer(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.String(length=36), nullable=True),
        sa.Column('channel_kind', sa.String(length=16), server_default='ai', nullable=False),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('archived_at', sa.DateTime(), nullable=True),
        sa.Column('last_message_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("channel_kind IN ('ai', 'member')", name='chk_chat_sessions_channel_kind'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['folder_id'], ['chat_folders.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
    if "chat_sessions" in created:
        op.create_index(op.f('ix_chat_sessions_created_by_user_id'), 'chat_sessions', ['created_by_user_id'], unique=False)
    if "chat_sessions" in created:
        op.create_index(op.f('ix_chat_sessions_current_agent_id'), 'chat_sessions', ['current_agent_id'], unique=False)
    if "chat_sessions" in created:
        op.create_index(op.f('ix_chat_sessions_current_agent_version_id'), 'chat_sessions', ['current_agent_version_id'], unique=False)
    if "chat_sessions" in created:
        op.create_index('ix_chat_sessions_project_channel_updated', 'chat_sessions', ['project_id', 'channel_kind', 'updated_at'], unique=False)
    if "chat_sessions" in created:
        op.create_index(op.f('ix_chat_sessions_project_id'), 'chat_sessions', ['project_id'], unique=False)
    if "chat_sessions" in created:
        op.create_index('ix_chat_sessions_project_updated', 'chat_sessions', ['project_id', 'updated_at'], unique=False)
    if "chat_sessions" in created:
        op.create_index(op.f('ix_chat_sessions_user_id'), 'chat_sessions', ['user_id'], unique=False)
    if "chat_sessions" in created:
        op.create_index('ix_chat_sessions_user_updated', 'chat_sessions', ['user_id', 'updated_at'], unique=False)
    if "model_access_assignments" not in existing:
        created.add("model_access_assignments")
        op.create_table('model_access_assignments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('model_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('group_id', sa.Integer(), nullable=True),
        sa.Column('assigned_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint('(user_id IS NOT NULL AND group_id IS NULL) OR (user_id IS NULL AND group_id IS NOT NULL)', name='chk_model_access_target'),
        sa.ForeignKeyConstraint(['group_id'], ['user_groups.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['model_id'], ['ai_models.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('model_id', 'group_id', name='uq_model_access_group'),
        sa.UniqueConstraint('model_id', 'user_id', name='uq_model_access_user')
        )
    if "model_access_assignments" in created:
        op.create_index(op.f('ix_model_access_assignments_group_id'), 'model_access_assignments', ['group_id'], unique=False)
    if "model_access_assignments" in created:
        op.create_index(op.f('ix_model_access_assignments_model_id'), 'model_access_assignments', ['model_id'], unique=False)
    if "model_access_assignments" in created:
        op.create_index(op.f('ix_model_access_assignments_user_id'), 'model_access_assignments', ['user_id'], unique=False)
    if "model_tool_compatibilities" not in existing:
        created.add("model_tool_compatibilities")
        op.create_table('model_tool_compatibilities',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('connection_id', sa.Integer(), nullable=False),
        sa.Column('model_id', sa.Integer(), nullable=True),
        sa.Column('external_model_id', sa.String(length=512), nullable=False),
        sa.Column('tool', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('consecutive_successes', sa.Integer(), nullable=False),
        sa.Column('consecutive_failures', sa.Integer(), nullable=False),
        sa.Column('total_successes', sa.Integer(), nullable=False),
        sa.Column('total_failures', sa.Integer(), nullable=False),
        sa.Column('reason_code', sa.String(length=64), nullable=True),
        sa.Column('reason_detail', sa.Text(), nullable=True),
        sa.Column('manual_override', sa.String(length=24), nullable=True),
        sa.Column('probe_version', sa.String(length=32), nullable=False),
        sa.Column('evidence_json', sa.Text(), nullable=True),
        sa.Column('last_probe_at', sa.DateTime(), nullable=True),
        sa.Column('last_success_at', sa.DateTime(), nullable=True),
        sa.Column('last_failure_at', sa.DateTime(), nullable=True),
        sa.Column('next_probe_at', sa.DateTime(), nullable=True),
        sa.Column('quarantine_until', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['connection_id'], ['connections.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['model_id'], ['ai_models.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('connection_id', 'external_model_id', 'tool', name='uq_model_tool_compatibility_target')
        )
    if "model_tool_compatibilities" in created:
        op.create_index(op.f('ix_model_tool_compatibilities_connection_id'), 'model_tool_compatibilities', ['connection_id'], unique=False)
    if "model_tool_compatibilities" in created:
        op.create_index(op.f('ix_model_tool_compatibilities_external_model_id'), 'model_tool_compatibilities', ['external_model_id'], unique=False)
    if "model_tool_compatibilities" in created:
        op.create_index(op.f('ix_model_tool_compatibilities_model_id'), 'model_tool_compatibilities', ['model_id'], unique=False)
    if "model_tool_compatibilities" in created:
        op.create_index(op.f('ix_model_tool_compatibilities_next_probe_at'), 'model_tool_compatibilities', ['next_probe_at'], unique=False)
    if "model_tool_compatibilities" in created:
        op.create_index(op.f('ix_model_tool_compatibilities_quarantine_until'), 'model_tool_compatibilities', ['quarantine_until'], unique=False)
    if "model_tool_compatibilities" in created:
        op.create_index(op.f('ix_model_tool_compatibilities_status'), 'model_tool_compatibilities', ['status'], unique=False)
    if "model_tool_compatibilities" in created:
        op.create_index(op.f('ix_model_tool_compatibilities_tool'), 'model_tool_compatibilities', ['tool'], unique=False)
    if "model_tool_compatibilities" in created:
        op.create_index('ix_model_tool_compatibility_due', 'model_tool_compatibilities', ['tool', 'status', 'next_probe_at'], unique=False)
    if "request_logs" not in existing:
        created.add("request_logs")
        op.create_table('request_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('username', sa.String(length=255), nullable=True),
        sa.Column('model_id', sa.String(length=512), nullable=False),
        sa.Column('prompt_language', sa.String(length=32), nullable=True),
        sa.Column('source_ip', sa.String(length=64), nullable=True),
        sa.Column('source', sa.String(length=32), nullable=True),
        sa.Column('client_app', sa.String(length=128), nullable=True),
        sa.Column('alpha_router_api_key_id', sa.Integer(), nullable=True),
        sa.Column('user_api_key_id', sa.Integer(), nullable=True),
        sa.Column('budget_reservation_id', sa.String(length=36), nullable=True),
        sa.Column('prompt_tokens', sa.Integer(), nullable=True),
        sa.Column('completion_tokens', sa.Integer(), nullable=True),
        sa.Column('cached_tokens', sa.Integer(), nullable=True),
        sa.Column('total_cost_usd', sa.Float(), nullable=True),
        sa.Column('provider_cost_usd', sa.Float(), nullable=True),
        sa.Column('calculated_cost_usd', sa.Float(), nullable=True),
        sa.Column('cost_source', sa.String(length=32), nullable=True),
        sa.Column('cost_confidence', sa.String(length=24), nullable=True),
        sa.Column('has_unpriced_usage', sa.Boolean(), nullable=True),
        sa.Column('usage_operation_id', sa.String(length=36), nullable=True),
        sa.Column('reconciled_at', sa.DateTime(), nullable=True),
        sa.Column('project_id', sa.String(length=36), nullable=True),
        sa.Column('request_time', sa.DateTime(), nullable=True),
        sa.Column('response_time_ms', sa.Float(), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['alpha_router_api_key_id'], ['alpha_router_api_keys.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_api_key_id'], ['user_api_keys.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
    if "request_logs" in created:
        op.create_index(op.f('ix_request_logs_alpha_router_api_key_id'), 'request_logs', ['alpha_router_api_key_id'], unique=False)
    if "request_logs" in created:
        op.create_index(op.f('ix_request_logs_budget_reservation_id'), 'request_logs', ['budget_reservation_id'], unique=True)
    if "request_logs" in created:
        op.create_index(op.f('ix_request_logs_cost_confidence'), 'request_logs', ['cost_confidence'], unique=False)
    if "request_logs" in created:
        op.create_index(op.f('ix_request_logs_cost_source'), 'request_logs', ['cost_source'], unique=False)
    if "request_logs" in created:
        op.create_index(op.f('ix_request_logs_has_unpriced_usage'), 'request_logs', ['has_unpriced_usage'], unique=False)
    if "request_logs" in created:
        op.create_index(op.f('ix_request_logs_model_id'), 'request_logs', ['model_id'], unique=False)
    if "request_logs" in created:
        op.create_index(op.f('ix_request_logs_project_id'), 'request_logs', ['project_id'], unique=False)
    if "request_logs" in created:
        op.create_index(op.f('ix_request_logs_request_time'), 'request_logs', ['request_time'], unique=False)
    if "request_logs" in created:
        op.create_index(op.f('ix_request_logs_usage_operation_id'), 'request_logs', ['usage_operation_id'], unique=False)
    if "request_logs" in created:
        op.create_index(op.f('ix_request_logs_user_api_key_id'), 'request_logs', ['user_api_key_id'], unique=False)
    if "request_logs" in created:
        op.create_index(op.f('ix_request_logs_user_id'), 'request_logs', ['user_id'], unique=False)
    if "request_logs" in created:
        op.create_index(op.f('ix_request_logs_username'), 'request_logs', ['username'], unique=False)
    if "request_logs" in created:
        op.create_index('uq_request_logs_budget_reservation_id', 'request_logs', ['budget_reservation_id'], unique=True)
    if "usage_operations" not in existing:
        created.add("usage_operations")
        op.create_table('usage_operations',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('subject_type', sa.String(length=24), nullable=True),
        sa.Column('subject_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('alpha_router_api_key_id', sa.Integer(), nullable=True),
        sa.Column('budget_reservation_id', sa.String(length=36), nullable=True),
        sa.Column('operation_type', sa.String(length=32), nullable=False),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('client_app', sa.String(length=128), nullable=True),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('accounting_status', sa.String(length=24), nullable=False),
        sa.Column('idempotency_key', sa.String(length=200), nullable=False),
        sa.Column('total_cost_usd', sa.Numeric(precision=20, scale=12), nullable=False),
        sa.Column('provider_cost_usd', sa.Numeric(precision=20, scale=12), nullable=True),
        sa.Column('calculated_cost_usd', sa.Numeric(precision=20, scale=12), nullable=True),
        sa.Column('unpriced_event_count', sa.Integer(), nullable=False),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('reconciled_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['alpha_router_api_key_id'], ['alpha_router_api_keys.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
        )
    if "usage_operations" in created:
        op.create_index(op.f('ix_usage_operations_accounting_status'), 'usage_operations', ['accounting_status'], unique=False)
    if "usage_operations" in created:
        op.create_index(op.f('ix_usage_operations_alpha_router_api_key_id'), 'usage_operations', ['alpha_router_api_key_id'], unique=False)
    if "usage_operations" in created:
        op.create_index(op.f('ix_usage_operations_budget_reservation_id'), 'usage_operations', ['budget_reservation_id'], unique=False)
    if "usage_operations" in created:
        op.create_index(op.f('ix_usage_operations_idempotency_key'), 'usage_operations', ['idempotency_key'], unique=True)
    if "usage_operations" in created:
        op.create_index(op.f('ix_usage_operations_operation_type'), 'usage_operations', ['operation_type'], unique=False)
    if "usage_operations" in created:
        op.create_index(op.f('ix_usage_operations_started_at'), 'usage_operations', ['started_at'], unique=False)
    if "usage_operations" in created:
        op.create_index(op.f('ix_usage_operations_status'), 'usage_operations', ['status'], unique=False)
    if "usage_operations" in created:
        op.create_index('ix_usage_operations_status_time', 'usage_operations', ['status', 'started_at'], unique=False)
    if "usage_operations" in created:
        op.create_index(op.f('ix_usage_operations_subject_id'), 'usage_operations', ['subject_id'], unique=False)
    if "usage_operations" in created:
        op.create_index('ix_usage_operations_subject_time', 'usage_operations', ['subject_type', 'subject_id', 'started_at'], unique=False)
    if "usage_operations" in created:
        op.create_index(op.f('ix_usage_operations_subject_type'), 'usage_operations', ['subject_type'], unique=False)
    if "usage_operations" in created:
        op.create_index(op.f('ix_usage_operations_user_id'), 'usage_operations', ['user_id'], unique=False)
    if "video_generation_jobs" not in existing:
        created.add("video_generation_jobs")
        op.create_table('video_generation_jobs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.String(length=36), nullable=True),
        sa.Column('chat_session_id', sa.String(length=128), nullable=True),
        sa.Column('model_id', sa.String(length=512), nullable=False),
        sa.Column('catalog_model_id', sa.Integer(), nullable=True),
        sa.Column('connection_id', sa.Integer(), nullable=True),
        sa.Column('provider_type', sa.String(length=64), nullable=False),
        sa.Column('adapter_key', sa.String(length=64), nullable=False),
        sa.Column('adapter_version', sa.String(length=64), nullable=True),
        sa.Column('operation', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('params_json', sa.Text(), nullable=True),
        sa.Column('provider_job_id', sa.String(length=255), nullable=True),
        sa.Column('provider_polling_url', sa.Text(), nullable=True),
        sa.Column('budget_reservation_id', sa.String(length=64), nullable=True),
        sa.Column('idempotency_key', sa.String(length=160), nullable=True),
        sa.Column('media_asset_id', sa.Integer(), nullable=True),
        sa.Column('error_code', sa.String(length=64), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('persist', sa.Integer(), nullable=False),
        sa.Column('reference_image', sa.Text(), nullable=True),
        sa.Column('reference_storage_path', sa.Text(), nullable=True),
        sa.Column('reference_image_mime', sa.String(length=128), nullable=True),
        sa.Column('capability_snapshot_json', sa.Text(), nullable=True),
        sa.Column('provider_status_raw', sa.Text(), nullable=True),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('next_action_at', sa.DateTime(), nullable=True),
        sa.Column('lease_owner', sa.String(length=128), nullable=True),
        sa.Column('lease_expires_at', sa.DateTime(), nullable=True),
        sa.Column('cancel_requested_at', sa.DateTime(), nullable=True),
        sa.Column('ephemeral_storage_path', sa.Text(), nullable=True),
        sa.Column('ephemeral_expires_at', sa.DateTime(), nullable=True),
        sa.Column('ephemeral_consumed_at', sa.DateTime(), nullable=True),
        sa.Column('source_ip', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['catalog_model_id'], ['ai_models.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['connection_id'], ['connections.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['media_asset_id'], ['media_assets.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
    if "video_generation_jobs" in created:
        op.create_index(op.f('ix_video_generation_jobs_chat_session_id'), 'video_generation_jobs', ['chat_session_id'], unique=False)
    if "video_generation_jobs" in created:
        op.create_index(op.f('ix_video_generation_jobs_connection_id'), 'video_generation_jobs', ['connection_id'], unique=False)
    if "video_generation_jobs" in created:
        op.create_index(op.f('ix_video_generation_jobs_created_at'), 'video_generation_jobs', ['created_at'], unique=False)
    if "video_generation_jobs" in created:
        op.create_index(op.f('ix_video_generation_jobs_idempotency_key'), 'video_generation_jobs', ['idempotency_key'], unique=False)
    if "video_generation_jobs" in created:
        op.create_index(op.f('ix_video_generation_jobs_lease_expires_at'), 'video_generation_jobs', ['lease_expires_at'], unique=False)
    if "video_generation_jobs" in created:
        op.create_index(op.f('ix_video_generation_jobs_next_action_at'), 'video_generation_jobs', ['next_action_at'], unique=False)
    if "video_generation_jobs" in created:
        op.create_index(op.f('ix_video_generation_jobs_project_id'), 'video_generation_jobs', ['project_id'], unique=False)
    if "video_generation_jobs" in created:
        op.create_index(op.f('ix_video_generation_jobs_provider_job_id'), 'video_generation_jobs', ['provider_job_id'], unique=False)
    if "video_generation_jobs" in created:
        op.create_index(op.f('ix_video_generation_jobs_status'), 'video_generation_jobs', ['status'], unique=False)
    if "video_generation_jobs" in created:
        op.create_index(op.f('ix_video_generation_jobs_user_id'), 'video_generation_jobs', ['user_id'], unique=False)
    if "video_generation_jobs" in created:
        op.create_index('ix_video_jobs_due', 'video_generation_jobs', ['status', 'next_action_at'], unique=False)
    if "video_generation_jobs" in created:
        op.create_index('ix_video_jobs_lease', 'video_generation_jobs', ['status', 'lease_expires_at'], unique=False)
    if "video_generation_jobs" in created:
        op.create_index('uq_video_job_user_idempotency', 'video_generation_jobs', ['user_id', 'idempotency_key'], unique=True)
    if "chat_messages" not in existing:
        created.add("chat_messages")
        op.create_table('chat_messages',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('author_display_name', sa.String(length=255), nullable=True),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('client_message_id', sa.String(length=64), nullable=True),
        sa.Column('agent_run_id', sa.String(length=36), nullable=True),
        sa.Column('meta', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id', 'client_message_id', name='ux_chat_messages_client_id'),
        sa.UniqueConstraint('session_id', 'sequence', name='ux_chat_messages_session_sequence')
        )
    if "chat_messages" in created:
        op.create_index(op.f('ix_chat_messages_agent_run_id'), 'chat_messages', ['agent_run_id'], unique=False)
    if "chat_messages" in created:
        op.create_index('ix_chat_messages_created_at', 'chat_messages', ['created_at'], unique=False)
    if "chat_messages" in created:
        op.create_index(op.f('ix_chat_messages_session_id'), 'chat_messages', ['session_id'], unique=False)
    if "chat_messages" in created:
        op.create_index('ix_chat_messages_session_sequence', 'chat_messages', ['session_id', 'sequence'], unique=False)
    if "chat_messages" in created:
        op.create_index(op.f('ix_chat_messages_user_id'), 'chat_messages', ['user_id'], unique=False)
    if "model_tool_compatibility_events" not in existing:
        created.add("model_tool_compatibility_events")
        op.create_table('model_tool_compatibility_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('compatibility_id', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=24), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('reason_code', sa.String(length=64), nullable=True),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.Column('requested_model_id', sa.String(length=512), nullable=True),
        sa.Column('upstream_request_id', sa.String(length=255), nullable=True),
        sa.Column('evidence_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['compatibility_id'], ['model_tool_compatibilities.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
    if "model_tool_compatibility_events" in created:
        op.create_index('ix_model_tool_compatibility_event_time', 'model_tool_compatibility_events', ['compatibility_id', 'created_at'], unique=False)
    if "model_tool_compatibility_events" in created:
        op.create_index(op.f('ix_model_tool_compatibility_events_compatibility_id'), 'model_tool_compatibility_events', ['compatibility_id'], unique=False)
    if "model_tool_compatibility_events" in created:
        op.create_index(op.f('ix_model_tool_compatibility_events_created_at'), 'model_tool_compatibility_events', ['created_at'], unique=False)
    if "usage_events" not in existing:
        created.add("usage_events")
        op.create_table('usage_events',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('operation_id', sa.String(length=36), nullable=False),
        sa.Column('connection_id', sa.Integer(), nullable=True),
        sa.Column('pricing_snapshot_id', sa.Integer(), nullable=True),
        sa.Column('reconciliation_run_id', sa.String(length=36), nullable=True),
        sa.Column('provider_type', sa.String(length=64), nullable=False),
        sa.Column('service_type', sa.String(length=32), nullable=False),
        sa.Column('operation_name', sa.String(length=64), nullable=False),
        sa.Column('model_id', sa.String(length=512), nullable=True),
        sa.Column('attempt_index', sa.Integer(), nullable=False),
        sa.Column('upstream_request_id', sa.String(length=255), nullable=True),
        sa.Column('idempotency_key', sa.String(length=220), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('prompt_tokens', sa.Integer(), nullable=False),
        sa.Column('completion_tokens', sa.Integer(), nullable=False),
        sa.Column('cached_tokens', sa.Integer(), nullable=False),
        sa.Column('cache_write_tokens', sa.Integer(), nullable=False),
        sa.Column('reasoning_tokens', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=True),
        sa.Column('unit', sa.String(length=32), nullable=True),
        sa.Column('provider_cost_usd', sa.Numeric(precision=20, scale=12), nullable=True),
        sa.Column('calculated_cost_usd', sa.Numeric(precision=20, scale=12), nullable=True),
        sa.Column('final_cost_usd', sa.Numeric(precision=20, scale=12), nullable=True),
        sa.Column('cost_source', sa.String(length=32), nullable=False),
        sa.Column('cost_confidence', sa.String(length=24), nullable=False),
        sa.Column('raw_usage_json', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('reconciliation_attempts', sa.Integer(), nullable=False),
        sa.Column('last_reconciliation_attempt_at', sa.DateTime(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('reconciled_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['connection_id'], ['connections.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['operation_id'], ['usage_operations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pricing_snapshot_id'], ['pricing_snapshots.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reconciliation_run_id'], ['reconciliation_runs.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('idempotency_key', name='uq_usage_events_idempotency_key')
        )
    if "usage_events" in created:
        op.create_index(op.f('ix_usage_events_completed_at'), 'usage_events', ['completed_at'], unique=False)
    if "usage_events" in created:
        op.create_index(op.f('ix_usage_events_connection_id'), 'usage_events', ['connection_id'], unique=False)
    if "usage_events" in created:
        op.create_index(op.f('ix_usage_events_cost_confidence'), 'usage_events', ['cost_confidence'], unique=False)
    if "usage_events" in created:
        op.create_index(op.f('ix_usage_events_cost_source'), 'usage_events', ['cost_source'], unique=False)
    if "usage_events" in created:
        op.create_index('ix_usage_events_cost_state_time', 'usage_events', ['cost_confidence', 'completed_at'], unique=False)
    if "usage_events" in created:
        op.create_index(op.f('ix_usage_events_last_reconciliation_attempt_at'), 'usage_events', ['last_reconciliation_attempt_at'], unique=False)
    if "usage_events" in created:
        op.create_index(op.f('ix_usage_events_model_id'), 'usage_events', ['model_id'], unique=False)
    if "usage_events" in created:
        op.create_index('ix_usage_events_operation_attempt', 'usage_events', ['operation_id', 'attempt_index'], unique=False)
    if "usage_events" in created:
        op.create_index(op.f('ix_usage_events_operation_id'), 'usage_events', ['operation_id'], unique=False)
    if "usage_events" in created:
        op.create_index(op.f('ix_usage_events_pricing_snapshot_id'), 'usage_events', ['pricing_snapshot_id'], unique=False)
    if "usage_events" in created:
        op.create_index(op.f('ix_usage_events_provider_type'), 'usage_events', ['provider_type'], unique=False)
    if "usage_events" in created:
        op.create_index(op.f('ix_usage_events_reconciliation_run_id'), 'usage_events', ['reconciliation_run_id'], unique=False)
    if "usage_events" in created:
        op.create_index(op.f('ix_usage_events_service_type'), 'usage_events', ['service_type'], unique=False)
    if "usage_events" in created:
        op.create_index(op.f('ix_usage_events_started_at'), 'usage_events', ['started_at'], unique=False)
    if "usage_events" in created:
        op.create_index(op.f('ix_usage_events_status'), 'usage_events', ['status'], unique=False)
    if "usage_events" in created:
        op.create_index('ix_usage_events_upstream_request', 'usage_events', ['connection_id', 'upstream_request_id'], unique=False)
    if "usage_events" in created:
        op.create_index(op.f('ix_usage_events_upstream_request_id'), 'usage_events', ['upstream_request_id'], unique=False)
    if "chat_message_feedback" not in existing:
        created.add("chat_message_feedback")
        op.create_table('chat_message_feedback',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('message_id', sa.String(length=36), nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('rating', sa.SmallInteger(), nullable=False),
        sa.Column('reason', sa.String(length=64), nullable=True),
        sa.Column('output_kind', sa.String(length=16), nullable=False),
        sa.Column('model_id', sa.String(length=512), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['message_id'], ['chat_messages.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('message_id', 'user_id', name='ux_chat_message_feedback_user')
        )
    if "chat_message_feedback" in created:
        op.create_index('ix_chat_feedback_kind_model', 'chat_message_feedback', ['output_kind', 'model_id'], unique=False)
    if "chat_message_feedback" in created:
        op.create_index(op.f('ix_chat_message_feedback_message_id'), 'chat_message_feedback', ['message_id'], unique=False)
    if "chat_message_feedback" in created:
        op.create_index(op.f('ix_chat_message_feedback_model_id'), 'chat_message_feedback', ['model_id'], unique=False)
    if "chat_message_feedback" in created:
        op.create_index(op.f('ix_chat_message_feedback_session_id'), 'chat_message_feedback', ['session_id'], unique=False)
    if "chat_message_feedback" in created:
        op.create_index(op.f('ix_chat_message_feedback_user_id'), 'chat_message_feedback', ['user_id'], unique=False)
    if "cost_ledger_entries" not in existing:
        created.add("cost_ledger_entries")
        op.create_table('cost_ledger_entries',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('operation_id', sa.String(length=36), nullable=False),
        sa.Column('usage_event_id', sa.String(length=36), nullable=True),
        sa.Column('request_log_id', sa.Integer(), nullable=True),
        sa.Column('reconciliation_run_id', sa.String(length=36), nullable=True),
        sa.Column('subject_type', sa.String(length=24), nullable=True),
        sa.Column('subject_id', sa.Integer(), nullable=True),
        sa.Column('entry_type', sa.String(length=24), nullable=False),
        sa.Column('amount_usd', sa.Numeric(precision=20, scale=12), nullable=False),
        sa.Column('cost_source', sa.String(length=32), nullable=False),
        sa.Column('cost_confidence', sa.String(length=24), nullable=False),
        sa.Column('idempotency_key', sa.String(length=240), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('effective_at', sa.DateTime(), nullable=False),
        sa.Column('is_reversed', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['operation_id'], ['usage_operations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reconciliation_run_id'], ['reconciliation_runs.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['request_log_id'], ['request_logs.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['usage_event_id'], ['usage_events.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('idempotency_key', name='uq_cost_ledger_entries_idempotency_key')
        )
    if "cost_ledger_entries" in created:
        op.create_index(op.f('ix_cost_ledger_entries_created_at'), 'cost_ledger_entries', ['created_at'], unique=False)
    if "cost_ledger_entries" in created:
        op.create_index(op.f('ix_cost_ledger_entries_effective_at'), 'cost_ledger_entries', ['effective_at'], unique=False)
    if "cost_ledger_entries" in created:
        op.create_index(op.f('ix_cost_ledger_entries_entry_type'), 'cost_ledger_entries', ['entry_type'], unique=False)
    if "cost_ledger_entries" in created:
        op.create_index(op.f('ix_cost_ledger_entries_operation_id'), 'cost_ledger_entries', ['operation_id'], unique=False)
    if "cost_ledger_entries" in created:
        op.create_index(op.f('ix_cost_ledger_entries_reconciliation_run_id'), 'cost_ledger_entries', ['reconciliation_run_id'], unique=False)
    if "cost_ledger_entries" in created:
        op.create_index(op.f('ix_cost_ledger_entries_request_log_id'), 'cost_ledger_entries', ['request_log_id'], unique=False)
    if "cost_ledger_entries" in created:
        op.create_index(op.f('ix_cost_ledger_entries_subject_id'), 'cost_ledger_entries', ['subject_id'], unique=False)
    if "cost_ledger_entries" in created:
        op.create_index(op.f('ix_cost_ledger_entries_subject_type'), 'cost_ledger_entries', ['subject_type'], unique=False)
    if "cost_ledger_entries" in created:
        op.create_index(op.f('ix_cost_ledger_entries_usage_event_id'), 'cost_ledger_entries', ['usage_event_id'], unique=False)
    if "cost_ledger_entries" in created:
        op.create_index('ix_cost_ledger_operation_time', 'cost_ledger_entries', ['operation_id', 'created_at'], unique=False)
    if "cost_ledger_entries" in created:
        op.create_index('ix_cost_ledger_subject_time', 'cost_ledger_entries', ['subject_type', 'subject_id', 'created_at'], unique=False)
    if "cost_line_items" not in existing:
        created.add("cost_line_items")
        op.create_table('cost_line_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('usage_event_id', sa.String(length=36), nullable=False),
        sa.Column('category', sa.String(length=64), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('unit', sa.String(length=32), nullable=False),
        sa.Column('unit_price_usd', sa.Numeric(precision=24, scale=14), nullable=True),
        sa.Column('cost_usd', sa.Numeric(precision=20, scale=12), nullable=True),
        sa.Column('pricing_source', sa.String(length=32), nullable=False),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['usage_event_id'], ['usage_events.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
    if "cost_line_items" in created:
        op.create_index(op.f('ix_cost_line_items_category'), 'cost_line_items', ['category'], unique=False)
    if "cost_line_items" in created:
        op.create_index('ix_cost_line_items_event_category', 'cost_line_items', ['usage_event_id', 'category'], unique=False)
    if "cost_line_items" in created:
        op.create_index(op.f('ix_cost_line_items_usage_event_id'), 'cost_line_items', ['usage_event_id'], unique=False)
    if "user_memories" not in existing:
        created.add("user_memories")
        op.create_table('user_memories',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('origin', sa.String(length=16), server_default='auto', nullable=False),
        sa.Column('category', sa.String(length=32), server_default='other', nullable=False),
        sa.Column('sensitivity', sa.String(length=16), server_default='normal', nullable=False),
        sa.Column('confidence', sa.Float(), server_default='0.5', nullable=False),
        sa.Column('salience', sa.Float(), server_default='0.5', nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('use_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('source_session_id', sa.String(length=36), nullable=True),
        sa.Column('source_message_id', sa.String(length=36), nullable=True),
        sa.Column('supersedes_id', sa.String(length=36), nullable=True),
        sa.Column('embedding_status', sa.String(length=16), server_default='pending', nullable=False),
        sa.Column('embedding_model', sa.String(length=255), nullable=True),
        sa.Column('embedding_dims', sa.Integer(), nullable=True),
        sa.Column('indexed_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['source_message_id'], ['chat_messages.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['source_session_id'], ['chat_sessions.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['supersedes_id'], ['user_memories.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'content_hash', name='ux_user_memories_user_hash')
        )
    if "user_memories" in created:
        op.create_index('ix_user_memories_deleted_at', 'user_memories', ['deleted_at'], unique=False)
    if "user_memories" in created:
        op.create_index('ix_user_memories_embedding_status', 'user_memories', ['embedding_status'], unique=False)
    if "user_memories" in created:
        op.create_index('ix_user_memories_expires_at', 'user_memories', ['expires_at'], unique=False)
    if "user_memories" in created:
        op.create_index('ix_user_memories_user_enabled_salience', 'user_memories', ['user_id', 'enabled', 'salience'], unique=False)
    if "user_memories" in created:
        op.create_index(op.f('ix_user_memories_user_id'), 'user_memories', ['user_id'], unique=False)
    if "user_memories" in created:
        op.create_index('ix_user_memories_user_updated', 'user_memories', ['user_id', 'updated_at'], unique=False)


def downgrade() -> None:
    # The baseline is the root of the chain; dropping the whole legacy schema
    # is never a safe automated step. Restore from backup instead.
    raise RuntimeError("The legacy schema baseline cannot be downgraded")
