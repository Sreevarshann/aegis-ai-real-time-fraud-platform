"""Request bodies validated server-side. Responses are plain JSON documents from repositories."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(_Strict):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class InvestigationCreate(_Strict):
    transaction_id: UUID


class InvestigationReview(_Strict):
    review_status: Literal["in_review", "escalated", "closed_fraud", "closed_legitimate"]
    notes: str | None = Field(default=None, max_length=4000)


class AlertStatusUpdate(_Strict):
    status: Literal["open", "investigating", "escalated", "dismissed", "confirmed_fraud"]


class SimulationRequest(_Strict):
    mode: Literal["burst", "scenarios", "incident"] = "burst"
    count: int = Field(default=200, ge=1, le=5000)
    include_defects: bool = True
