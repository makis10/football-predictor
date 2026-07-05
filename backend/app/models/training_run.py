from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base


class TrainingRun(Base):
    __tablename__ = "training_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    model_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Data split sizes
    n_train: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    n_cal:   Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    n_test:  Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cal_cutoff:   Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    train_cutoff: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    test_cutoff:  Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # Result model metrics (test set)
    result_test_accuracy:  Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    result_home_recall:    Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    result_draw_recall:    Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    result_away_recall:    Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    result_home_precision: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    result_draw_precision: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    result_away_precision: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Goals model metrics (test set)
    goals_test_accuracy:  Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    goals_over_recall:    Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    goals_under_recall:   Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    goals_over_precision: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Draw specialist calibration
    draw_raw_mean:    Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    draw_cal_mean:    Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    draw_actual_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # BTTS (Both Teams To Score) — Poisson model evaluated on test set
    btts_test_accuracy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    btts_gg_recall:     Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    btts_ng_recall:     Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    btts_gg_precision:  Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    btts_ng_precision:  Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    btts_threshold:     Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
