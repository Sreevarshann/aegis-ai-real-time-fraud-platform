"""Rolling behavioural state for feature computation.

Two interchangeable implementations of :class:`FeatureStore`:

* :class:`InMemoryFeatureStore` - used to build the offline training set by replaying the
  historical stream in event-time order;
* :class:`RedisFeatureStore` - used by the live consumer.

Every write is keyed by ``transaction_id`` (sorted-set member / dict key), so recording the
same transaction twice is a no-op. Combined with readers excluding the transaction being
scored, this makes the online state safe under Kafka at-least-once redelivery.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Protocol

import redis

CUSTOMER_RETENTION_S = 30 * 86_400
ENTITY_RETENTION_S = 2 * 86_400
MAX_CUSTOMER_EVENTS = 500


@dataclass(frozen=True, slots=True)
class CustomerEvent:
    txn_id: str
    ts: float
    amount_usd: float
    country: str
    device_id: str
    local_hour: float


@dataclass(frozen=True, slots=True)
class MerchantEvent:
    txn_id: str
    ts: float
    customer_id: str
    declined: bool


@dataclass(frozen=True, slots=True)
class DeviceEvent:
    txn_id: str
    ts: float
    customer_id: str


@dataclass(frozen=True, slots=True)
class EntityHistory:
    customer: list[CustomerEvent]
    merchant: list[MerchantEvent]
    device: list[DeviceEvent]


class FeatureStore(Protocol):
    def history(
        self, tenant_id: str, customer_id: str, merchant_id: str, device_id: str, exclude_txn: str, now_ts: float
    ) -> EntityHistory: ...

    def record(
        self, tenant_id: str, customer_id: str, merchant_id: str, c: CustomerEvent, m: MerchantEvent, d: DeviceEvent
    ) -> None: ...

    def advance_watermark(self, tenant_id: str, ts: datetime) -> datetime: ...


def _prior(events: list, now_ts: float, horizon_s: float, exclude: str) -> list:
    lo = now_ts - horizon_s
    # Only events strictly before the scored one in event time: late events must not "see the future".
    return [e for e in events if lo <= e.ts <= now_ts and e.txn_id != exclude]


class InMemoryFeatureStore:
    def __init__(self) -> None:
        self._cust: dict[tuple[str, str], dict[str, CustomerEvent]] = defaultdict(dict)
        self._merch: dict[tuple[str, str], dict[str, MerchantEvent]] = defaultdict(dict)
        self._dev: dict[tuple[str, str], dict[str, DeviceEvent]] = defaultdict(dict)
        self._watermarks: dict[str, datetime] = {}

    def history(
        self, tenant_id: str, customer_id: str, merchant_id: str, device_id: str, exclude_txn: str, now_ts: float
    ) -> EntityHistory:
        return EntityHistory(
            customer=_prior(
                list(self._cust[(tenant_id, customer_id)].values()), now_ts, CUSTOMER_RETENTION_S, exclude_txn
            ),
            merchant=_prior(
                list(self._merch[(tenant_id, merchant_id)].values()), now_ts, ENTITY_RETENTION_S, exclude_txn
            ),
            device=_prior(list(self._dev[(tenant_id, device_id)].values()), now_ts, ENTITY_RETENTION_S, exclude_txn),
        )

    def record(
        self, tenant_id: str, customer_id: str, merchant_id: str, c: CustomerEvent, m: MerchantEvent, d: DeviceEvent
    ) -> None:
        cust = self._cust[(tenant_id, customer_id)]
        cust[c.txn_id] = c
        if len(cust) > MAX_CUSTOMER_EVENTS:  # keep the most recent events, like ZREMRANGEBYRANK
            for key in sorted(cust, key=lambda k: cust[k].ts)[: len(cust) - MAX_CUSTOMER_EVENTS]:
                del cust[key]
        merch = self._merch[(tenant_id, merchant_id)]
        merch[m.txn_id] = m
        dev = self._dev[(tenant_id, c.device_id)]
        dev[d.txn_id] = d
        # Bound memory for long offline replays: drop merchant/device events beyond retention.
        for store in (merch, dev):
            if len(store) > 5000:
                cutoff = c.ts - ENTITY_RETENTION_S
                for key in [k for k, v in store.items() if v.ts < cutoff]:
                    del store[key]

    def advance_watermark(self, tenant_id: str, ts: datetime) -> datetime:
        current = self._watermarks.get(tenant_id)
        if current is None or ts > current:
            self._watermarks[tenant_id] = ts
            return ts
        return current


class RedisFeatureStore:
    """Sorted sets per entity: member = compact JSON incl. txn id, score = event epoch seconds."""

    def __init__(self, client: redis.Redis, prefix: str = "aegis") -> None:
        self.r = client
        self.prefix = prefix

    def _k(self, tenant_id: str, kind: str, entity: str) -> str:
        return f"{self.prefix}:{tenant_id}:{kind}:{entity}"

    def history(
        self, tenant_id: str, customer_id: str, merchant_id: str, device_id: str, exclude_txn: str, now_ts: float
    ) -> EntityHistory:
        pipe = self.r.pipeline(transaction=False)
        pipe.zrangebyscore(self._k(tenant_id, "cust", customer_id), now_ts - CUSTOMER_RETENTION_S, now_ts)
        pipe.zrangebyscore(self._k(tenant_id, "merch", merchant_id), now_ts - ENTITY_RETENTION_S, now_ts)
        pipe.zrangebyscore(self._k(tenant_id, "dev", device_id), now_ts - ENTITY_RETENTION_S, now_ts)
        raw_c, raw_m, raw_d = pipe.execute()
        cust = [CustomerEvent(**json.loads(x)) for x in raw_c]
        merch = [MerchantEvent(**json.loads(x)) for x in raw_m]
        dev = [DeviceEvent(**json.loads(x)) for x in raw_d]
        return EntityHistory(
            customer=[e for e in cust if e.txn_id != exclude_txn],
            merchant=[e for e in merch if e.txn_id != exclude_txn],
            device=[e for e in dev if e.txn_id != exclude_txn],
        )

    def record(
        self, tenant_id: str, customer_id: str, merchant_id: str, c: CustomerEvent, m: MerchantEvent, d: DeviceEvent
    ) -> None:
        kc = self._k(tenant_id, "cust", customer_id)
        km = self._k(tenant_id, "merch", merchant_id)
        kd = self._k(tenant_id, "dev", c.device_id)
        pipe = self.r.pipeline(transaction=True)
        for key, ev, retention in (
            (kc, c, CUSTOMER_RETENTION_S),
            (km, m, ENTITY_RETENTION_S),
            (kd, d, ENTITY_RETENTION_S),
        ):
            member = json.dumps(asdict(ev), separators=(",", ":"), sort_keys=True)
            pipe.zadd(key, {member: ev.ts})
            pipe.zremrangebyscore(key, "-inf", ev.ts - retention)
            pipe.expire(key, retention + 86_400)
        pipe.zremrangebyrank(kc, 0, -(MAX_CUSTOMER_EVENTS + 1))
        pipe.execute()

    def advance_watermark(self, tenant_id: str, ts: datetime) -> datetime:
        key = f"{self.prefix}:{tenant_id}:watermark"
        # GT flag: only ever move the watermark forward (Redis >= 6.2).
        self.r.zadd(key, {"wm": ts.timestamp()}, gt=True)
        score = self.r.zscore(key, "wm")
        return datetime.fromtimestamp(float(score or ts.timestamp()), tz=ts.tzinfo)
