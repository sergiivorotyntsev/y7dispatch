"""SQLModel database setup for training system.

This module provides SQLModel/SQLAlchemy session management for the training
system, separate from the main SQLite-based database.py module.
"""

import os
from collections.abc import Generator
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


def get_session() -> Generator[Session, None, None]:
    """Get a SQLModel session for FastAPI dependency injection.

    Note: Do NOT use @contextmanager decorator here - it's incompatible
    with FastAPI's Depends() which expects a raw generator function.
    """
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()


class SessionContext:
    """Context manager wrapper for get_session() for use outside FastAPI.

    Use this when you need `with ... as session:` syntax in non-FastAPI code.

    Example:
        with SessionContext() as session:
            service = TrainingService(session)
            ...
    """

    def __init__(self):
        self.session = None

    def __enter__(self) -> Session:
        self.session = Session(engine)
        return self.session

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            self.session.close()
        return False
