"""SMTP, scheduled reports, key-value settings, and system metric snapshots."""

import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text

from app.database import Base


class SmtpSettings(Base):
    __tablename__ = "smtp_settings"

    id = Column(Integer, primary_key=True)
    host = Column(String(255), nullable=False)
    port = Column(Integer, default=587)
    username = Column(String(255), nullable=True)
    password_encrypted = Column(Text, nullable=True)
    from_address = Column(String(255), nullable=False)
    use_tls = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)


class ReportSchedule(Base):
    __tablename__ = "report_schedules"

    id = Column(Integer, primary_key=True)
    owner_user_id = Column(Integer, nullable=True)  # null = admin system schedule
    report_type = Column(String(64), nullable=False)
    cron_expression = Column(String(128), nullable=False)
    recipients = Column(Text, nullable=False)  # comma-separated emails
    parameters_json = Column(Text, nullable=True)
    format = Column(String(16), default="pdf")  # csv | xls | pdf
    is_active = Column(Boolean, default=True)
    last_run_at = Column(DateTime, nullable=True)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key = Column(String(128), primary_key=True)
    value = Column(Text, nullable=True)


class SystemMetricSnapshot(Base):
    """Hourly (or on-demand) host/DB metrics for the Operations dashboard."""

    __tablename__ = "system_metric_snapshots"

    id = Column(Integer, primary_key=True)
    recorded_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    db_engine = Column(String(32), nullable=True)
    host_cpu_percent = Column(Float, nullable=True)
    host_memory_percent = Column(Float, nullable=True)
    process_cpu_percent = Column(Float, nullable=True)
    process_rss_bytes = Column(Integer, nullable=True)
    db_ping_ms = Column(Float, nullable=True)
    db_size_bytes = Column(Integer, nullable=True)
