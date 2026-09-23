"""SMTP says which kind of TLS it uses instead of one "Use TLS" switch.

Revision ID: 4ce0678f5e1c
Revises: 5dca7b7bddf9
Create Date: 2026-09-23

SMTP has two incompatible ways to use TLS. Port 587 starts in plain text and
upgrades with STARTTLS; port 465 speaks TLS from the first byte. The single
``use_tls`` switch meant the second one, and shipped switched on with port
587 — a combination that can never connect ("[SSL: WRONG_VERSION_NUMBER]").
Switched off, it meant "upgrade if the server offers it", which sends the
password in plain text when the offer is missing or stripped.

``security`` names the mode: ``starttls`` (required, never a silent fall-back),
``ssl``, or ``none``. Each existing row keeps what it evidently meant:

* ``use_tls`` on a STARTTLS port (25, 587, 2525) → ``starttls``. This is the
  combination that never worked; it now does.
* ``use_tls`` on any other port → ``ssl``, exactly as before.
* ``use_tls`` off → ``starttls``. Before, the upgrade happened when offered;
  now it is required. A relay that offers no STARTTLS has to be set to
  ``none`` on purpose.

The mapping is repeated in ``smtp_service.security_from_legacy`` for a page
loaded before this change; a test keeps the two in step.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4ce0678f5e1c"
down_revision: str | None = "5dca7b7bddf9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "smtp_settings"


def _columns() -> set[str] | None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return None
    return {column["name"] for column in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    columns = _columns()
    if columns is None:
        return
    if "security" not in columns:
        op.add_column(
            _TABLE,
            sa.Column("security", sa.String(length=16), nullable=False, server_default="starttls"),
        )
    if "use_tls" in columns:
        op.execute(
            sa.text(
                "UPDATE smtp_settings SET security = CASE "
                "WHEN use_tls AND (port IS NULL OR port NOT IN (25, 587, 2525)) THEN 'ssl' "
                "ELSE 'starttls' END"
            )
        )
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column("use_tls")


def downgrade() -> None:
    columns = _columns()
    if columns is None:
        return
    if "use_tls" not in columns:
        op.add_column(_TABLE, sa.Column("use_tls", sa.Boolean(), nullable=True))
    if "security" in columns:
        # The old switch meant implicit TLS when on and "STARTTLS if offered"
        # when off, so only ``ssl`` maps to on.
        op.execute(sa.text("UPDATE smtp_settings SET use_tls = CASE WHEN security = 'ssl' THEN TRUE ELSE FALSE END"))
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column("security")
