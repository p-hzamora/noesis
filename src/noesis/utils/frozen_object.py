"""Immutable pydantic base used for value objects, commands, queries and DTOs."""

from pydantic import BaseModel, ConfigDict


class FrozenObject(BaseModel):
    """Immutable model, comparable by value, buildable from attributes."""

    model_config = ConfigDict(frozen=True, from_attributes=True)
