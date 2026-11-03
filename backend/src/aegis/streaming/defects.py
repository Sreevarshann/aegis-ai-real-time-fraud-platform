"""Deliberate data defects for exercising the pipeline's reliability guarantees.

Turns a clean :class:`SimulatedEvent` stream into the messy stream a real platform sees:
exact replays, out-of-order (delayed) delivery, stale events, schema violations, malformed
JSON and referential-integrity failures. Each emitted message carries the *intended*
outcome in ``expected`` so tests can assert the consumer's behaviour.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from aegis.events.schema import build_envelope
from aegis.simulator.generator import SimulatedEvent


@dataclass(frozen=True)
class DefectRates:
    duplicate: float = 0.02
    out_of_order: float = 0.03
    stale: float = 0.002
    invalid: float = 0.01

    @classmethod
    def none(cls) -> DefectRates:
        return cls(0.0, 0.0, 0.0, 0.0)


@dataclass
class OutboundMessage:
    key: str
    value: bytes
    expected: str  # "accept", "duplicate", "late", "dead_letter:<reason>"
    meta: dict = field(default_factory=dict)


INVALID_KINDS = (
    "missing_field",
    "negative_amount",
    "bad_currency",
    "bad_country",
    "malformed_json",
    "unsupported_version",
    "naive_timestamp",
    "unknown_customer",
)
_EXPECTED_REASON = {
    "missing_field": "schema_validation_failed",
    "negative_amount": "schema_validation_failed",
    "bad_currency": "schema_validation_failed",
    "bad_country": "schema_validation_failed",
    "naive_timestamp": "schema_validation_failed",
    "malformed_json": "malformed_json",
    "unsupported_version": "unsupported_schema_version",
    "unknown_customer": "unknown_customer",
}


def encode(ev: SimulatedEvent, produced_at: datetime) -> dict:
    return build_envelope(ev.payload, ev.event_id, produced_at, ev.label)


def corrupt(doc: dict, kind: str) -> bytes:
    d = json.loads(json.dumps(doc))
    p = d["payload"]
    if kind == "missing_field":
        p.pop("merchant_id")
    elif kind == "negative_amount":
        p["transaction_amount"] = "-42.00"
    elif kind == "bad_currency":
        p["currency"] = "XXX"
    elif kind == "bad_country":
        p["transaction_country"] = "Narnia"
    elif kind == "unsupported_version":
        d["schema_version"] = "0.9"
    elif kind == "naive_timestamp":
        p["event_timestamp"] = p["event_timestamp"].replace("Z", "").split("+")[0]
    elif kind == "unknown_customer":
        p["customer_id"] = "GHOST-C999999"
    elif kind == "malformed_json":
        return (json.dumps(d)[:-17] + ',"oops":').encode()
    return json.dumps(d).encode()


def inject_defects(
    events: Iterable[SimulatedEvent], rates: DefectRates, seed: int, clock: Callable[[], datetime] | None = None
) -> Iterator[OutboundMessage]:
    """Yield wire messages with defects injected at the configured rates."""
    rng = np.random.default_rng(seed + 991)
    recent: deque[OutboundMessage] = deque(maxlen=200)
    delayed: list[tuple[int, OutboundMessage]] = []
    i = 0
    for ev in events:
        i += 1
        produced = clock() if clock else ev.payload.event_timestamp
        doc = encode(ev, produced)
        key = ev.payload.customer_id
        r = rng.random()
        if r < rates.invalid:
            kind = INVALID_KINDS[int(rng.integers(len(INVALID_KINDS)))]
            yield OutboundMessage(key, corrupt(doc, kind), f"dead_letter:{_EXPECTED_REASON[kind]}", {"kind": kind})
            continue
        if r < rates.invalid + rates.stale:
            stale = ev.payload.event_timestamp - timedelta(days=3)
            doc["payload"]["event_timestamp"] = stale.isoformat().replace("+00:00", "Z")
            yield OutboundMessage(key, json.dumps(doc).encode(), "dead_letter:stale_event")
            continue
        msg = OutboundMessage(
            key, json.dumps(doc).encode(), "accept", {"transaction_id": str(ev.payload.transaction_id)}
        )
        if rng.random() < rates.out_of_order:
            # Deliver later than its successors: partition ordering is per key, so different-key
            # successors overtake it; if the gap exceeds the tolerance the consumer flags it late.
            msg.meta["delayed"] = True
            # Mostly short reorderings; a quarter are held long enough (~7-15 min of stream time at the
            # default rate) to exceed the consumer's lateness tolerance and be flagged late.
            hold = int(rng.integers(1200, 2500)) if rng.random() < 0.25 else int(rng.integers(5, 60))
            delayed.append((i + hold, msg))
        else:
            yield msg
            recent.append(msg)
        due = [m for when, m in delayed if when <= i]
        delayed = [(w, m) for w, m in delayed if w > i]
        for m in due:
            yield m
            recent.append(m)
        if recent and rng.random() < rates.duplicate:
            orig = recent[int(rng.integers(len(recent)))]
            yield OutboundMessage(orig.key, orig.value, "duplicate", dict(orig.meta))
    for _, m in delayed:
        yield m
