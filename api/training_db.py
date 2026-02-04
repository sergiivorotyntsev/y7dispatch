"""SQLModel database setup for training system.

This module provides SQLModel/SQLAlchemy session management for the training
system, separate from the main SQLite-based database.py module.
"""

import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

# Training database path - can be overridden via TRAINING_DB_PATH env var
_default_training_path = Path(__file__).parent.parent / "data" / "training.db"
TRAINING_DB_PATH = Path(os.environ.get("TRAINING_DB_PATH", str(_default_training_path)))

# Ensure data directory exists
TRAINING_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# SQLModel engine
engine = create_engine(
    f"sqlite:///{TRAINING_DB_PATH}",
    echo=False,  # Set to True for SQL debugging
    connect_args={"check_same_thread": False},  # Allow multi-thread access
)


def init_training_db():
    """Initialize training database tables."""
    from models.training import (
        ExtractionPattern,
        ExtractionRule,
        FieldCorrection,
        TrainingExample,
    )

    SQLModel.metadata.create_all(
        engine,
        tables=[
            ExtractionRule.__table__,
            FieldCorrection.__table__,
            TrainingExample.__table__,
            ExtractionPattern.__table__,
        ],
    )


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Get a SQLModel session for dependency injection."""
    with Session(engine) as session:
        yield session
