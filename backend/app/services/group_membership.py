"""Who is in a group, for the code that asks "given a group, list its members".

Soft delete used to answer this question by deleting the rows: moving a user to
Deleted Users removed every ``user_group_members`` row they had. That made the
membership table a correct answer to this question by construction - and made
restoring a user impossible, because nothing anywhere had recorded what they
belonged to. An LDAP user pruned by an OU change and picked up again by the next
sync came back with no groups, and therefore no inherited budget plan, no group
model access and no group knowledge or agent access. Silently.

So memberships now survive a soft delete, and this module is how the question
stays correctly answered: a deleted account is not a member for any purpose a
person or a bill can see.

Queries that go the other way - "given this user, which groups do they have?" -
do not need this. They start from an account that has already authenticated, and
a deleted account cannot.
"""

from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.sql import ColumnElement

from app.models.user import User, user_group_members


def _live_user() -> ColumnElement[bool]:
    return (User.deleted_at.is_(None)) & (User.purged_at.is_(None))


def live_member_ids_stmt(group_id: int) -> Select:
    """User ids in one group, excluding deleted and purged accounts."""

    return (
        select(user_group_members.c.user_id)
        .join(User, User.id == user_group_members.c.user_id)
        .where(user_group_members.c.group_id == group_id, _live_user())
    )


def live_member_ids_for_groups_stmt(group_ids) -> Select:
    """User ids across several groups, excluding deleted and purged accounts."""

    return (
        select(user_group_members.c.user_id)
        .join(User, User.id == user_group_members.c.user_id)
        .where(user_group_members.c.group_id.in_(group_ids), _live_user())
    )


def live_member_counts_stmt(group_ids) -> Select:
    """(group_id, member count) for several groups, counting live accounts only."""

    from sqlalchemy import func

    return (
        select(user_group_members.c.group_id, func.count())
        .join(User, User.id == user_group_members.c.user_id)
        .where(user_group_members.c.group_id.in_(group_ids), _live_user())
        .group_by(user_group_members.c.group_id)
    )
