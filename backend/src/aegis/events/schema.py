"""Versioned JSON event contract for the ``transactions.v1`` topic.

Wire format (schema_version 1.0)::

    {
      "schema_version": "1.0",
      "event_type": "transaction.created",
      "event_id": "<uuid>",
      "produced_at": "<iso8601>",
      "payload": { ...TransactionPayload... },
      "simulation": { "ground_truth_label": 0|1, "scenario": "<name>" }   # optional
    }

The ``simulation`` block exists only because the data is synthetic. It is split off at the
edge of the consumer (:func:`parse_envelope`) and the scoring path only ever receives a
:class:`TransactionPayload`, which has no label field. This makes label leakage into live
inference structurally impossible rather than a matter of discipline.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0"})
CURRENT_SCHEMA_VERSION = "1.0"
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


class MerchantCategory(StrEnum):
    GROCERY = "grocery"
    RESTAURANTS = "restaurants"
    FUEL = "fuel"
    TRAVEL = "travel"
    ELECTRONICS = "electronics"
    FASHION = "fashion"
    DIGITAL_GOODS = "digital_goods"
    GAMBLING = "gambling"
    CRYPTO_EXCHANGE = "crypto_exchange"
    MONEY_TRANSFER = "money_transfer"
    UTILITIES = "utilities"
    HEALTHCARE = "healthcare"


class PaymentChannel(StrEnum):
    CARD_PRESENT = "card_present"
    ECOMMERCE = "ecommerce"
    MOBILE_WALLET = "mobile_wallet"
    BANK_TRANSFER = "bank_transfer"


class TransactionStatus(StrEnum):
    APPROVED = "approved"
    DECLINED = "declined"
    PENDING = "pending"


SUPPORTED_CURRENCIES = frozenset({"USD", "EUR", "GBP", "CAD", "JPY", "INR", "BRL", "SGD"})


class TransactionPayload(BaseModel):
    """Everything that is legitimately known at authorisation time. No labels."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transaction_id: UUID
    tenant_id: str = Field(min_length=1, max_length=32)
    event_timestamp: datetime
    customer_id: str
    merchant_id: str
    merchant_category: MerchantCategory
    transaction_amount: Decimal = Field(gt=0, le=Decimal("1000000"), decimal_places=2)
    currency: str
    transaction_country: str
    device_id: str
    payment_channel: PaymentChannel
    transaction_status: TransactionStatus

    @field_validator("customer_id", "merchant_id", "device_id", "tenant_id")
    @classmethod
    def _safe_identifier(cls, v: str) -> str:
        if not _ID_PATTERN.match(v):
            raise ValueError("identifier must be 1-64 chars of [A-Za-z0-9_-]")
        return v

    @field_validator("currency")
    @classmethod
    def _currency(cls, v: str) -> str:
        if v not in SUPPORTED_CURRENCIES:
            raise ValueError(f"unsupported currency {v!r}")
        return v

    @field_validator("transaction_country")
    @classmethod
    def _country(cls, v: str) -> str:
        if len(v) != 2 or not v.isalpha() or not v.isupper():
            raise ValueError("country must be an ISO-3166 alpha-2 code")
        return v

    @field_validator("event_timestamp")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("event_timestamp must include a timezone offset")
        return v.astimezone(UTC)


class SimulationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ground_truth_label: Literal[0, 1]
    scenario: str = Field(max_length=32)


class TransactionEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    event_type: Literal["transaction.created"]
    event_id: UUID
    produced_at: datetime
    payload: TransactionPayload
    simulation: SimulationMetadata | None = None

    @field_validator("schema_version")
    @classmethod
    def _version(cls, v: str) -> str:
        if v not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(f"unsupported schema_version {v!r}")
        return v


class EventRejected(Exception):
    """Raised when a raw message cannot be accepted. ``reason`` is a stable machine code."""

    def __init__(self, reason: str, detail: str, tenant_id: str | None = None) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail
        self.tenant_id = tenant_id


def parse_envelope(raw: bytes | str) -> TransactionEnvelope:
    """Decode and validate a raw Kafka value, raising :class:`EventRejected` with a reason code."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise EventRejected("malformed_json", str(exc)[:500]) from exc
    if not isinstance(data, dict):
        raise EventRejected("malformed_json", "top-level JSON value must be an object")

    tenant_hint = None
    payload = data.get("payload")
    if isinstance(payload, dict) and isinstance(payload.get("tenant_id"), str):
        tenant_hint = payload["tenant_id"][:32]

    version = data.get("schema_version")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise EventRejected("unsupported_schema_version", f"schema_version={version!r}", tenant_hint)
    try:
        return TransactionEnvelope.model_validate(data)
    except ValidationError as exc:
        errors = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors(include_url=False))
        raise EventRejected("schema_validation_failed", errors[:1000], tenant_hint) from exc


def payload_hash(payload: TransactionPayload) -> str:
    """Stable content hash used to tell an exact replay from a conflicting re-use of an id."""
    canonical = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def build_envelope(
    payload: TransactionPayload,
    event_id: UUID,
    produced_at: datetime,
    simulation: SimulationMetadata | None = None,
) -> dict[str, Any]:
    env = TransactionEnvelope(
        schema_version=CURRENT_SCHEMA_VERSION,
        event_type="transaction.created",
        event_id=event_id,
        produced_at=produced_at,
        payload=payload,
        simulation=simulation,
    )
    return env.model_dump(mode="json", exclude_none=True)
