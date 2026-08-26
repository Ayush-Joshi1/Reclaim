"""Command-line entry point for local database table creation."""

from app.database import create_tables


def main() -> None:
    """Create database tables from the current SQLAlchemy metadata."""
    create_tables()


if __name__ == "__main__":
    main()
