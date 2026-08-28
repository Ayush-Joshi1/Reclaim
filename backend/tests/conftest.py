"""Test configuration for the Reclaim backend."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")
os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/reclaim")
