#!/usr/bin/env python3
"""Project Argus — database reconciliation helper.

This script is safe to run repeatedly. It bridges historical schema/version
drift so `alembic upgrade head` can run predictably across old and fresh DBs.
"""

from __future__ import annotations

import logging

from sqlalchemy import text

from app.db.session import engine

logger = logging.getLogger("argus.db.reconcile")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

KNOWN_REVISIONS = {"001_initial", "002_person_metadata"}
HEAD_REVISION = "002_person_metadata"


def _run_reconciliation(conn: any) -> None:
    # Ensure required person-metadata columns exist even if legacy DB
    # skipped migration 002.
    conn.execute(text(
        """
        ALTER TABLE declarant_profiles
        ADD COLUMN IF NOT EXISTS user_declarant_id INTEGER
        """
    ))
    conn.execute(text(
        """
        ALTER TABLE declarant_profiles
        ADD COLUMN IF NOT EXISTS declaration_year INTEGER
        """
    ))
    conn.execute(text(
        """
        ALTER TABLE declarant_profiles
        ADD COLUMN IF NOT EXISTS declaration_type INTEGER
        """
    ))
    conn.execute(text(
        """
        CREATE INDEX IF NOT EXISTS ix_declarant_profiles_user_declarant_id
        ON declarant_profiles(user_declarant_id)
        """
    ))
    conn.execute(text(
        """
        CREATE INDEX IF NOT EXISTS ix_declarant_profiles_declaration_year
        ON declarant_profiles(declaration_year)
        """
    ))

    # Ensure alembic version table exists.
    conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS alembic_version (
            version_num VARCHAR(32) NOT NULL
        )
        """
    ))

    row = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).fetchone()
    if row is None:
        conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
            {"v": HEAD_REVISION},
        )
        logger.info("Initialized alembic_version to %s", HEAD_REVISION)
        return

    current = row[0]
    if current not in KNOWN_REVISIONS:
        conn.execute(
            text("UPDATE alembic_version SET version_num = :v"),
            {"v": HEAD_REVISION},
        )
        logger.warning(
            "Unknown Alembic revision '%s' detected; reconciled to '%s'.",
            current,
            HEAD_REVISION,
        )
    else:
        logger.info("Alembic revision is known: %s", current)


def reconcile(db_engine: any = engine) -> None:
    with db_engine.begin() as conn:
        _run_reconciliation(conn)


if __name__ == "__main__":
    reconcile()
    logger.info("DB reconciliation complete.")
