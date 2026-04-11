"""
Project Argus — SQLAlchemy engine and session factory.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

_database_url = settings.database_url
_connect_args = {"connect_timeout": 3}
_engine_kwargs = {
    "echo": False,
    "pool_pre_ping": True,
}

if _database_url.startswith("sqlite"):
    # sqlite engines reject postgres pool/connect args
    _connect_args = {"check_same_thread": False}
else:
    _engine_kwargs.update(
        {
            "pool_size": int(os.getenv("ARGUS_DB_POOL_SIZE", "5")),
            "max_overflow": int(os.getenv("ARGUS_DB_MAX_OVERFLOW", "10")),
        }
    )

engine = create_engine(
    _database_url,
    connect_args=_connect_args,
    **_engine_kwargs,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency that yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
