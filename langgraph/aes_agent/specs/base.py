from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """Base model for versioned AES contracts."""

    model_config = ConfigDict(extra="forbid")
