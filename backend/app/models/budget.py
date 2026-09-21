"""Budget plans and assignments to users or groups."""

import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base, MoneyUSD


class BudgetPlan(Base):
    __tablename__ = "budget_plans"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), unique=True, nullable=False)
    monthly_budget_usd = Column(MoneyUSD, nullable=False, default=0.0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    assignments = relationship("PlanAssignment", back_populates="plan")


class PlanAssignment(Base):
    __tablename__ = "plan_assignments"

    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey("budget_plans.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    group_id = Column(Integer, ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=True, index=True)
    # Assign plan to every user in this department (e.g. IT, Marketing)
    department = Column(String(255), nullable=True, index=True)
    assigned_at = Column(DateTime, default=datetime.datetime.utcnow)

    plan = relationship("BudgetPlan", back_populates="assignments")
    user = relationship("User", back_populates="plan_assignments", foreign_keys=[user_id])
    group = relationship("UserGroup", back_populates="plan_assignments")
