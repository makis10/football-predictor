from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.app.database import Base


class Feedback(Base):
    """A Contact-form message from a logged-in user → read in the admin panel."""
    __tablename__ = "feedback"

    id:         Mapped[int]                = mapped_column(Integer, primary_key=True)
    user_id:    Mapped[Optional[int]]      = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    user_email: Mapped[Optional[str]]      = mapped_column(String(255), nullable=True)
    user_name:  Mapped[Optional[str]]      = mapped_column(String(255), nullable=True)
    message:    Mapped[str]                = mapped_column(Text, nullable=False)
    is_read:    Mapped[bool]               = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime]           = mapped_column(DateTime(timezone=True), server_default=func.now())
