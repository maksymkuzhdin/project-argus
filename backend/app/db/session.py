"""
Project Argus — SQLAlchemy engine and session factory.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

engine = create_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    connect_args={"connect_timeout": 3},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency that yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
