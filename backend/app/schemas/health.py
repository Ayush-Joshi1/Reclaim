"""Response schemas for service health endpoints."""

from pydantic import BaseModel


class ServiceHealthResponse(BaseModel):
    """Service availability response."""

    status: str
    service: str


class DatabaseHealthResponse(BaseModel):
    """Database connectivity response."""

    status: str
    database: str
