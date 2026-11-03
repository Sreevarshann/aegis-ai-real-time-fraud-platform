"""Seeded synthetic transaction generator.

The generator is a thinned Poisson process over the customer population: arrivals are
drawn at the population's aggregate rate, a customer is picked in proportion to their
personal rate, and the arrival is kept with a probability that follows the customer's
time-of-day habit. On top of that baseline it injects:

* fraud incidents (label 1) - card-testing bursts, account takeover from a new device and
  country, high-value anomalies, impossible-travel card cloning and collusive merchants;
* hard negatives (label 0) - legitimate travel, new phones and occasional big purchases,
  so the model cannot learn "anything unusual is fraud".

The same code path produces both the offline training history (``generate``) and the
live stream (``stream``), so train/serve skew comes only from what we deliberately vary.
"""

from __future__ import annotations

import heapq
import itertools
import math
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

import numpy as np

from aegis.events.schema import (
    MerchantCategory,
    PaymentChannel,
    SimulationMetadata,
    TransactionPayload,
    TransactionStatus,
)
from aegis.simulator.reference import (
    CATEGORIES,
    CATEGORY_PROFILE,
    COUNTRIES,
    DEFAULT_TENANTS,
    USD_PER_UNIT,
    CustomerProfile,
    Population,
    build_population,
    device_id_for,
)

FRAUD_SCENARIOS: dict[str, float] = {
    "card_testing_burst": 0.24,
    "account_takeover": 0.20,
    "high_value_anomaly": 0.20,
    "impossible_travel": 0.16,
    "collusive_merchant": 0.20,
}
_FOREIGN_FRAUD_COUNTRIES = ["BR", "IN", "SG", "JP", "NL", "ES", "US", "GB"]
_CNP = [PaymentChannel.ECOMMERCE, PaymentChannel.MOBILE_WALLET]


@dataclass(frozen=True)
class SimulatedEvent:
    payload: TransactionPayload
    label: SimulationMetadata
    event_id: uuid.UUID


@dataclass(frozen=True)
class SimulatorConfig:
    seed: int = 42
    customers_per_tenant: int = 30_000
    merchants_per_tenant: int = 600
    # Probability that an accepted arrival triggers a fraud incident instead of a normal txn.
    fraud_incident_rate: float = 0.0028
    rate_multiplier: float = 1.0
    # Seed for the event stream itself; defaults to ``seed``. The population always uses ``seed``
    # so a live stream with a fresh stream_seed still matches the seeded reference data.
    stream_seed: int | None = None


def _channel_for(category: MerchantCategory, rng: np.random.Generator) -> PaymentChannel:
    if category in (
        MerchantCategory.GROCERY,
        MerchantCategory.FUEL,
        MerchantCategory.RESTAURANTS,
        MerchantCategory.HEALTHCARE,
    ):
        return PaymentChannel.CARD_PRESENT if rng.random() < 0.85 else PaymentChannel.MOBILE_WALLET
    if category in (MerchantCategory.DIGITAL_GOODS, MerchantCategory.GAMBLING, MerchantCategory.CRYPTO_EXCHANGE):
        return PaymentChannel.ECOMMERCE
    if category is MerchantCategory.MONEY_TRANSFER:
        return PaymentChannel.BANK_TRANSFER if rng.random() < 0.6 else PaymentChannel.MOBILE_WALLET
    r = rng.random()
    return (
        PaymentChannel.CARD_PRESENT
        if r < 0.45
        else PaymentChannel.ECOMMERCE
        if r < 0.85
        else PaymentChannel.MOBILE_WALLET
    )


def _local_hour(ts: datetime, country: str) -> float:
    return (ts.hour + ts.minute / 60 + COUNTRIES[country][1]) % 24


class TransactionSimulator:
    def __init__(self, config: SimulatorConfig | None = None, populations: list[Population] | None = None) -> None:
        self.config = config or SimulatorConfig()
        self.rng = np.random.default_rng(
            self.config.seed if self.config.stream_seed is None else self.config.stream_seed
        )
        secrets_rng = np.random.default_rng([self.config.seed, 99])
        self.populations = populations or [
            build_population(t, self.config.customers_per_tenant, self.config.merchants_per_tenant, self.config.seed, i)
            for i, t in enumerate(DEFAULT_TENANTS)
        ]
        self._customers: list[tuple[Population, CustomerProfile]] = [
            (p, c) for p in self.populations for c in p.customers
        ]
        rates = np.array([c.daily_rate for _, c in self._customers])
        self._cum_weights = np.cumsum(rates / rates.sum())
        # Thinning keeps ~45% of arrivals, so scale the proposal rate to compensate.
        self._arrivals_per_s = rates.sum() / 86_400 * self.config.rate_multiplier / 0.45
        # Simulation-only secrets: compromised merchants and mutable customer state.
        self._compromised: dict[str, list[int]] = {}
        for pop in self.populations:
            risky = [
                i
                for i, m in enumerate(pop.merchants)
                if m.category
                in (
                    MerchantCategory.ELECTRONICS,
                    MerchantCategory.DIGITAL_GOODS,
                    MerchantCategory.FASHION,
                    MerchantCategory.CRYPTO_EXCHANGE,
                )
            ]
            k = max(3, len(pop.merchants) // 100)
            self._compromised[pop.tenant.tenant_id] = [
                int(x) for x in secrets_rng.choice(risky, size=min(k, len(risky)), replace=False)
            ]
        self._extra_devices: dict[str, list[str]] = {}
        self._trips: dict[str, tuple[str, datetime]] = {}
        self._seq = itertools.count()
        self._victim_limit: int | None = None

    # ------------------------------------------------------------------ public API
    @property
    def expected_events_per_second(self) -> float:
        return self._arrivals_per_s * 0.45

    def stream(self, start: datetime, customer_limit: int | None = None) -> Iterator[SimulatedEvent]:
        """Infinite, timestamp-ordered event stream starting at ``start``."""
        pool = self._customers
        cum = self._cum_weights
        rate = self._arrivals_per_s
        if customer_limit is not None:
            pool = [pc for pc in self._customers if int(pc[1].customer_id[-6:]) < customer_limit]
            rates = np.array([c.daily_rate for _, c in pool])
            cum = np.cumsum(rates / rates.sum())
            rate = rates.sum() / 86_400 * self.config.rate_multiplier / 0.45
        # Collusive-merchant victims must come from the same customer pool, otherwise "no history"
        # would become a spurious fraud signal when training on a subset of the population.
        self._victim_limit = customer_limit
        heap: list[tuple[datetime, int, SimulatedEvent]] = []
        t = start
        while True:
            t = t + timedelta(seconds=float(self.rng.exponential(1.0 / rate)))
            pop, cust = pool[int(np.searchsorted(cum, self.rng.random()))]
            country = self._current_country(cust, t)
            hour = _local_hour(t, country)
            affinity = 0.04 + math.exp(
                -((min(abs(hour - cust.active_hour), 24 - abs(hour - cust.active_hour))) ** 2) / (2 * 4.0**2)
            )
            if self.rng.random() < self.config.fraud_incident_rate:
                events = self._fraud_incident(pop, cust, t)
            elif self.rng.random() < min(affinity, 1.0):
                events = [self._normal(pop, cust, t)]
                if self.rng.random() < 0.01:  # hard negative: a legitimate quick run of purchases
                    events += [
                        self._normal(pop, cust, t + timedelta(seconds=float(self.rng.uniform(30, 600))))
                        for _ in range(int(self.rng.integers(1, 4)))
                    ]
            else:
                events = []
            for ev in events:
                heapq.heappush(heap, (ev.payload.event_timestamp, next(self._seq), ev))
            while heap and heap[0][0] <= t:
                yield heapq.heappop(heap)[2]

    def generate(self, start: datetime, end: datetime, customer_limit: int | None = None) -> list[SimulatedEvent]:
        out: list[SimulatedEvent] = []
        for ev in self.stream(start, customer_limit):
            if ev.payload.event_timestamp >= end:
                break
            out.append(ev)
        return out

    def customer(self, tenant_id: str, customer_id: str) -> CustomerProfile:
        pop = next(p for p in self.populations if p.tenant.tenant_id == tenant_id)
        return pop.customers[int(customer_id[-6:])]

    # ------------------------------------------------------------------ building blocks
    def _uuid(self) -> uuid.UUID:
        return uuid.UUID(bytes=self.rng.bytes(16), version=4)

    def _current_country(self, cust: CustomerProfile, t: datetime) -> str:
        trip = self._trips.get(cust.customer_id)
        if trip and t < trip[1]:
            return trip[0]
        return cust.home_country

    def _devices(self, cust: CustomerProfile) -> list[str]:
        return list(cust.registered_devices) + self._extra_devices.get(cust.customer_id, [])

    def _make(
        self,
        pop: Population,
        cust: CustomerProfile,
        t: datetime,
        merchant_idx: int,
        amount_usd: float,
        country: str,
        device: str,
        channel: PaymentChannel,
        status: TransactionStatus,
        label: int,
        scenario: str,
    ) -> SimulatedEvent:
        currency = COUNTRIES[country][0]
        local_amount = max(amount_usd / USD_PER_UNIT[currency], 0.5)
        amount = Decimal(str(local_amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        m = pop.merchants[merchant_idx]
        payload = TransactionPayload(
            transaction_id=self._uuid(),
            tenant_id=pop.tenant.tenant_id,
            event_timestamp=t,
            customer_id=cust.customer_id,
            merchant_id=m.merchant_id,
            merchant_category=m.category,
            transaction_amount=amount,
            currency=currency,
            transaction_country=country,
            device_id=device,
            payment_channel=channel,
            transaction_status=status,
        )
        return SimulatedEvent(payload, SimulationMetadata(ground_truth_label=label, scenario=scenario), self._uuid())

    def _pick_merchant(
        self, pop: Population, cust: CustomerProfile, categories: list[MerchantCategory] | None = None
    ) -> int:
        if categories is None and self.rng.random() < 0.7:
            return cust.preferred_merchants[int(self.rng.integers(len(cust.preferred_merchants)))]
        if categories is None:
            w = np.array([CATEGORY_PROFILE[c][1] for c in CATEGORIES])
            cat = CATEGORIES[int(self.rng.choice(len(CATEGORIES), p=w / w.sum()))]
        else:
            cat = categories[int(self.rng.integers(len(categories)))]
        idx = pop.merchants_by_category[cat] or list(range(len(pop.merchants)))
        return idx[int(self.rng.integers(len(idx)))]

    def _status(self, fraud: bool) -> TransactionStatus:
        r = self.rng.random()
        if fraud:
            return TransactionStatus.DECLINED if r < 0.18 else TransactionStatus.APPROVED
        return (
            TransactionStatus.DECLINED
            if r < 0.02
            else TransactionStatus.PENDING
            if r < 0.025
            else TransactionStatus.APPROVED
        )

    def _normal(self, pop: Population, cust: CustomerProfile, t: datetime) -> SimulatedEvent:
        rng = self.rng
        scenario = "normal"
        country = self._current_country(cust, t)
        if country == cust.home_country and rng.random() < 0.0015:
            dest = str(rng.choice([c for c in COUNTRIES if c != cust.home_country]))
            self._trips[cust.customer_id] = (dest, t + timedelta(days=float(rng.uniform(2, 7))))
            country = dest
        if country != cust.home_country:
            scenario = "legit_travel"

        devices = self._devices(cust)
        device = devices[0] if rng.random() < 0.75 else devices[int(rng.integers(len(devices)))]
        if rng.random() < 0.006:
            device = device_id_for(rng)
            self._extra_devices.setdefault(cust.customer_id, []).append(device)
            scenario = "legit_new_device"

        m_idx = self._pick_merchant(pop, cust)
        cat = pop.merchants[m_idx].category
        amount = cust.avg_ticket_usd * CATEGORY_PROFILE[cat][0] * float(rng.lognormal(0.0, 0.55))
        if rng.random() < 0.008:
            m_idx = self._pick_merchant(
                pop, cust, [MerchantCategory.ELECTRONICS, MerchantCategory.TRAVEL, MerchantCategory.CRYPTO_EXCHANGE]
            )
            cat = pop.merchants[m_idx].category
            amount = cust.avg_ticket_usd * float(rng.uniform(4, 20))
            scenario = "legit_large_purchase"
        return self._make(
            pop, cust, t, m_idx, amount, country, device, _channel_for(cat, rng), self._status(False), 0, scenario
        )

    def fraud_incident(self, tenant_id: str, t: datetime, scenario: str) -> list[SimulatedEvent]:
        """Force a specific fraud scenario (used by the demo scenario pack)."""
        pop = next(p for p in self.populations if p.tenant.tenant_id == tenant_id)
        cust = pop.customers[int(self.rng.integers(len(pop.customers)))]
        return self._fraud_incident(pop, cust, t, scenario)

    def _fraud_incident(
        self, pop: Population, cust: CustomerProfile, t: datetime, scenario: str | None = None
    ) -> list[SimulatedEvent]:
        rng = self.rng
        if scenario is None:
            names = list(FRAUD_SCENARIOS)
            p = np.array(list(FRAUD_SCENARIOS.values()))
            scenario = names[int(rng.choice(len(names), p=p / p.sum()))]
        home = self._current_country(cust, t)
        out: list[SimulatedEvent] = []

        if scenario == "card_testing_burst":
            device = device_id_for(rng) if rng.random() < 0.8 else self._devices(cust)[0]
            m_idx = self._pick_merchant(pop, cust, [MerchantCategory.DIGITAL_GOODS, MerchantCategory.GAMBLING])
            ts = t
            for _ in range(int(rng.integers(4, 10))):
                out.append(
                    self._make(
                        pop,
                        cust,
                        ts,
                        m_idx,
                        float(rng.uniform(1, 15)),
                        home,
                        device,
                        PaymentChannel.ECOMMERCE,
                        self._status(True),
                        1,
                        scenario,
                    )
                )
                ts += timedelta(seconds=float(rng.uniform(15, 90)))
            if rng.random() < 0.4:
                out.append(
                    self._make(
                        pop,
                        cust,
                        ts,
                        self._pick_merchant(pop, cust, [MerchantCategory.ELECTRONICS]),
                        float(rng.uniform(150, 600)),
                        home,
                        device,
                        PaymentChannel.ECOMMERCE,
                        self._status(True),
                        1,
                        scenario,
                    )
                )
        elif scenario == "account_takeover":
            device = device_id_for(rng)
            country = str(rng.choice(_FOREIGN_FRAUD_COUNTRIES)) if rng.random() < 0.6 else home
            if country == cust.home_country:
                country = home
            ts = t
            for _ in range(int(rng.integers(1, 4))):
                m_idx = self._pick_merchant(
                    pop,
                    cust,
                    [MerchantCategory.ELECTRONICS, MerchantCategory.MONEY_TRANSFER, MerchantCategory.CRYPTO_EXCHANGE],
                )
                amount = cust.avg_ticket_usd * float(rng.uniform(2, 25))
                out.append(
                    self._make(
                        pop,
                        cust,
                        ts,
                        m_idx,
                        amount,
                        country,
                        device,
                        _CNP[int(rng.integers(2))],
                        self._status(True),
                        1,
                        scenario,
                    )
                )
                ts += timedelta(minutes=float(rng.uniform(2, 15)))
        elif scenario == "high_value_anomaly":
            devices = self._devices(cust)
            device = devices[0] if rng.random() < 0.5 else device_id_for(rng)
            ts = t
            if rng.random() < 0.6:  # shift into the small hours, local time
                local = _local_hour(t, home)
                ts = t + timedelta(hours=(24 - local + float(rng.uniform(0.5, 4.5))) % 24)
            m_idx = self._pick_merchant(
                pop,
                cust,
                [
                    MerchantCategory.ELECTRONICS,
                    MerchantCategory.TRAVEL,
                    MerchantCategory.CRYPTO_EXCHANGE,
                    MerchantCategory.FASHION,
                ],
            )
            amount = cust.avg_ticket_usd * float(rng.uniform(3, 30))
            out.append(
                self._make(
                    pop,
                    cust,
                    ts,
                    m_idx,
                    amount,
                    home,
                    device,
                    _CNP[int(rng.integers(2))],
                    self._status(True),
                    1,
                    scenario,
                )
            )
        elif scenario == "impossible_travel":
            # A genuine home transaction, then a cloned-card purchase far away shortly after.
            out.append(self._normal(pop, cust, t))
            far = str(rng.choice([c for c in _FOREIGN_FRAUD_COUNTRIES if c != home]))
            ts = t + timedelta(minutes=float(rng.uniform(8, 60)))
            device = device_id_for(rng) if rng.random() < 0.5 else self._devices(cust)[0]
            m_idx = self._pick_merchant(
                pop, cust, [MerchantCategory.ELECTRONICS, MerchantCategory.FASHION, MerchantCategory.TRAVEL]
            )
            amount = cust.avg_ticket_usd * float(rng.uniform(1, 10))
            out.append(
                self._make(
                    pop,
                    cust,
                    ts,
                    m_idx,
                    amount,
                    far,
                    device,
                    PaymentChannel.CARD_PRESENT,
                    self._status(True),
                    1,
                    scenario,
                )
            )
        else:  # collusive_merchant: one compromised merchant charges many cards in a short window
            compromised = self._compromised[pop.tenant.tenant_id]
            m_idx = compromised[int(rng.integers(len(compromised)))]
            ts = t
            pool_size = min(len(pop.customers), self._victim_limit or len(pop.customers))
            victims = rng.choice(pool_size, size=int(rng.integers(4, 9)), replace=False)
            for v in victims:
                victim = pop.customers[int(v)]
                amount = victim.avg_ticket_usd * float(rng.uniform(1.2, 9))
                status = TransactionStatus.DECLINED if rng.random() < 0.35 else TransactionStatus.APPROVED
                out.append(
                    self._make(
                        pop,
                        victim,
                        ts,
                        m_idx,
                        amount,
                        victim.home_country,
                        self._devices(victim)[0],
                        PaymentChannel.ECOMMERCE,
                        status,
                        1,
                        scenario,
                    )
                )
                ts += timedelta(minutes=float(rng.uniform(1, 10)))
        return out
