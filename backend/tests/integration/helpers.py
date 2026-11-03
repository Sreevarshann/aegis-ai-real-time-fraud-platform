from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from aegis.simulator.generator import SimulatedEvent, SimulatorConfig, TransactionSimulator
from aegis.streaming.defects import encode
from aegis.streaming.processor import RawMessage


def recent_events(n: int, seed: int = 11, tenant: str | None = None) -> list[SimulatedEvent]:
    sim = TransactionSimulator(SimulatorConfig(seed=42, stream_seed=seed))
    out = []
    for ev in sim.stream(datetime.now(UTC) - timedelta(minutes=30)):
        if tenant is None or ev.payload.tenant_id == tenant:
            out.append(ev)
        if len(out) >= n:
            return out
    return out


def to_messages(events: list[SimulatedEvent], topic: str = "t", start_offset: int = 0) -> list[RawMessage]:
    now = datetime.now(UTC)
    return [RawMessage(json.dumps(encode(e, now)).encode(), topic, 0, start_offset + i) for i, e in enumerate(events)]
