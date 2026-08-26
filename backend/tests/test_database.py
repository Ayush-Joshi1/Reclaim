"""Database connectivity tests."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal


def test_database_select_one_when_postgresql_is_available() -> None:
    try:
        with SessionLocal() as session:
            assert session.execute(text("SELECT 1")).scalar_one() == 1
    except SQLAlchemyError as error:
        pytest.skip(f"PostgreSQL is unavailable for this test: {error.__class__.__name__}")
