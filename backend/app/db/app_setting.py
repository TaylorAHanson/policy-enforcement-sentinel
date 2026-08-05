from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text

from app.db.base import Base


class AppSettingModel(Base):
    """One admin-set override of a configuration value.

    Only keys listed in ``settings_store.EDITABLE_FIELDS`` are ever read back,
    so a stale row for a removed setting is inert rather than surprising.
    """

    __tablename__ = "app_settings"

    key = Column(String, primary_key=True, comment="Settings attribute name, e.g. ENFORCEMENT_ENABLED")
    value = Column(Text, nullable=True, comment="Serialised override value; coerced on load")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(String, nullable=True, comment="Who last changed it")
