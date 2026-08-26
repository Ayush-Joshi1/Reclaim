"""Test configuration for the Reclaim backend."""

import os

# Database tests are skipped if this local PostgreSQL instance is unavailable.
os.environ.setdefault("DATABASE_URL", "postgresql://recoverai:localdev@localhost:5432/reclaim")
