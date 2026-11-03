"""Transaction event producer.

    python -m aegis.streaming.producer live      [--rate-multiplier 1.0] [--duration 0]
    python -m aegis.streaming.producer burst     --count 500 [--tenant northwind]
    python -m aegis.streaming.producer scenarios                     # demo pack: every fraud + defect type
    python -m aegis.streaming.producer incident                     # malformed-data incident drill

Messages are keyed by ``customer_id`` so a customer's events keep their relative order
within a partition (the consumer's per-customer features rely on that).
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from confluent_kafka import Producer

from aegis.config import Settings, get_settings
from aegis.observability.logging import configure_logging, get_logger
from aegis.simulator.generator import FRAUD_SCENARIOS, SimulatedEvent, SimulatorConfig, TransactionSimulator
from aegis.streaming.defects import (
    INVALID_KINDS,
    DefectRates,
    OutboundMessage,
    corrupt,
    encode,
    inject_defects,
)
from aegis.streaming.kafka import delivery_report, ensure_topics, make_producer

log = get_logger(__name__)


@dataclass
class PublishSummary:
    sent: int
    expected: dict[str, int]

    def as_dict(self) -> dict:
        return {"sent": self.sent, "expected_outcomes": self.expected}


def _sim(settings: Settings, stream_seed: int | None, rate_multiplier: float = 1.0) -> TransactionSimulator:
    return TransactionSimulator(
        SimulatorConfig(seed=settings.simulator_seed, stream_seed=stream_seed, rate_multiplier=rate_multiplier)
    )


def publish(producer: Producer, topic: str, messages: Iterable[OutboundMessage]) -> PublishSummary:
    counts: Counter[str] = Counter()
    n = 0
    for m in messages:
        while True:
            try:
                producer.produce(topic, key=m.key.encode(), value=m.value, on_delivery=delivery_report)
                break
            except BufferError:  # local queue full: let librdkafka drain, then retry
                producer.poll(0.5)
        producer.poll(0)
        counts[m.expected.split(":")[0]] += 1
        n += 1
    remaining = producer.flush(30)
    if remaining:
        raise RuntimeError(f"{remaining} messages were not delivered to Kafka")
    return PublishSummary(n, dict(counts))


def burst_events(settings: Settings, count: int, tenant: str | None, stream_seed: int | None) -> list[SimulatedEvent]:
    """``count`` realistic events whose timestamps end at 'now' (back-dated by their natural spacing)."""
    sim = _sim(settings, stream_seed)
    span = timedelta(seconds=count / sim.expected_events_per_second * (2 if tenant else 1))
    start = datetime.now(UTC) - span
    out: list[SimulatedEvent] = []
    for ev in sim.stream(start):
        if tenant and ev.payload.tenant_id != tenant:
            continue
        out.append(ev)
        if len(out) >= count:
            break
    now = datetime.now(UTC)
    return [ev for ev in out if ev.payload.event_timestamp <= now + timedelta(seconds=5)]


def run_burst(
    count: int,
    tenant: str | None = None,
    defects: bool = True,
    seed: int | None = None,
    settings: Settings | None = None,
) -> PublishSummary:
    s = settings or get_settings()
    stream_seed = seed if seed is not None else int(time.time())
    events = burst_events(s, count, tenant, stream_seed)
    rates = DefectRates() if defects else DefectRates.none()
    producer = make_producer(s)
    return publish(
        producer,
        s.kafka_transactions_topic,
        inject_defects(events, rates, stream_seed, clock=lambda: datetime.now(UTC)),
    )


def scenario_pack(settings: Settings, seed: int, tenant: str | None = None) -> list[OutboundMessage]:
    """One incident of every fraud scenario per tenant, background traffic and every defect type."""
    sim = _sim(settings, seed + 1)  # distinct stream seed: ids must not collide with the background burst
    now = datetime.now(UTC)
    msgs: list[OutboundMessage] = []
    clean = burst_events(settings, 300 if tenant is None else 150, tenant, seed)
    for ev in clean:
        msgs.append(OutboundMessage(ev.payload.customer_id, json.dumps(encode(ev, now)).encode(), "accept"))
    for tenant_id in [tenant] if tenant else ["northwind", "meridian"]:
        for i, scenario in enumerate(FRAUD_SCENARIOS):
            t = now - timedelta(minutes=4) + timedelta(seconds=10 * i)
            for ev in sim.fraud_incident(tenant_id, t, scenario):
                if ev.payload.event_timestamp <= now:
                    msgs.append(OutboundMessage(ev.payload.customer_id, json.dumps(encode(ev, now)).encode(), "accept"))
    msgs.extend(incident_messages(clean[: len(INVALID_KINDS) + 2], now))
    msgs.append(OutboundMessage(msgs[0].key, msgs[0].value, "duplicate"))
    msgs.append(OutboundMessage(msgs[1].key, msgs[1].value, "duplicate"))
    return msgs


def incident_messages(templates: list[SimulatedEvent], now: datetime) -> list[OutboundMessage]:
    """The documented malformed-data incident: one message per defect class."""
    out = []
    for ev, kind in zip(templates, INVALID_KINDS, strict=False):
        out.append(OutboundMessage(ev.payload.customer_id, corrupt(encode(ev, now), kind), f"dead_letter:{kind}"))
    stale = templates[-1]
    doc = encode(stale, now)
    doc["payload"]["event_timestamp"] = (now - timedelta(days=3)).isoformat().replace("+00:00", "Z")
    out.append(OutboundMessage(stale.payload.customer_id, json.dumps(doc).encode(), "dead_letter:stale_event"))
    out.append(OutboundMessage("garbage", b"\x00\xff not even json", "dead_letter:malformed_json"))
    return out


def run_pack(mode: str, tenant: str, seed: int, settings: Settings | None = None) -> PublishSummary:
    """Scenario pack or malformed-data incident restricted to one tenant (used by the API)."""
    s = settings or get_settings()
    if mode == "scenarios":
        messages = scenario_pack(s, seed, tenant)
    else:
        messages = incident_messages(burst_events(s, len(INVALID_KINDS) + 2, tenant, seed), datetime.now(UTC))
        messages = [m for m in messages if m.key != "garbage"]  # unattributable junk is not tenant-scoped
    return publish(make_producer(s), s.kafka_transactions_topic, messages)


def run_live(settings: Settings, rate_multiplier: float, duration_s: float) -> None:
    sim = _sim(settings, int(time.time()), rate_multiplier)
    producer = make_producer(settings, "aegis-live-simulator")
    start = datetime.now(UTC)
    log.info("live_stream_started", expected_eps=round(sim.expected_events_per_second, 2))
    sent = 0
    deadline = time.monotonic() + duration_s if duration_s > 0 else None
    for m in inject_defects(sim.stream(start), DefectRates(), int(time.time()), clock=lambda: datetime.now(UTC)):
        ts = json.loads(m.value)["payload"]["event_timestamp"] if m.expected == "accept" else None
        if ts:  # pace the stream so event time tracks wall-clock time
            due = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            while (wait := (due - datetime.now(UTC)).total_seconds()) > 0:
                producer.poll(min(wait, 1.0))  # serve delivery callbacks while waiting
        producer.produce(
            settings.kafka_transactions_topic, key=m.key.encode(), value=m.value, on_delivery=delivery_report
        )
        producer.poll(0)
        sent += 1
        if sent % 500 == 0:
            log.info("live_stream_progress", sent=sent)
        if deadline and time.monotonic() > deadline:
            break
    producer.flush(30)


def main(argv: list[str] | None = None) -> None:
    s = get_settings()
    ap = argparse.ArgumentParser(description="AEGIS synthetic transaction producer")
    sub = ap.add_subparsers(dest="mode", required=True)
    live = sub.add_parser("live")
    live.add_argument("--rate-multiplier", type=float, default=1.0)
    live.add_argument("--duration", type=float, default=0.0, help="seconds; 0 = forever")
    burst = sub.add_parser("burst")
    burst.add_argument("--count", type=int, default=500)
    burst.add_argument("--tenant", default=None)
    burst.add_argument("--seed", type=int, default=None)
    burst.add_argument("--no-defects", action="store_true")
    pack = sub.add_parser("scenarios")
    pack.add_argument("--seed", type=int, default=None)
    sub.add_parser("incident")
    args = ap.parse_args(argv)
    configure_logging(s.log_level, s.log_json)
    ensure_topics(s)

    if args.mode == "live":
        run_live(s, args.rate_multiplier, args.duration)
        return
    if args.mode == "burst":
        summary = run_burst(args.count, args.tenant, not args.no_defects, args.seed, s)
    elif args.mode == "scenarios":
        seed = args.seed if args.seed is not None else int(time.time())
        summary = publish(make_producer(s), s.kafka_transactions_topic, scenario_pack(s, seed))
    else:
        templates = burst_events(s, len(INVALID_KINDS) + 2, None, int(time.time()))
        summary = publish(make_producer(s), s.kafka_transactions_topic, incident_messages(templates, datetime.now(UTC)))
    log.info("published", mode=args.mode, **summary.as_dict())
    print(json.dumps(summary.as_dict()))


if __name__ == "__main__":
    main()
