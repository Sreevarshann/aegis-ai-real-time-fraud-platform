"""Offline training set construction.

The historical stream is generated in event-time order and replayed through the *same*
:class:`~aegis.features.compute.FeatureEngine` the live consumer uses (backed by an
in-memory store instead of Redis). Labels are attached only after features are computed.
Training uses an independent synthetic population drawn from the same distributions as the
live one, scaled down while preserving the *customer-to-merchant density*. That keeps
merchant-level velocity features (transactions / distinct customers per merchant-hour) on the
same scale offline and online - training on a customer subset against the full merchant
catalogue would make every live merchant look anomalously busy.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from aegis.features.compute import CustomerReference, FeatureEngine
from aegis.features.store import InMemoryFeatureStore
from aegis.simulator.generator import SimulatorConfig, TransactionSimulator
from aegis.simulator.reference import CustomerProfile

DEFAULT_HISTORY_START = datetime(2026, 8, 1, tzinfo=UTC)


def reference_for(profile: CustomerProfile) -> CustomerReference:
    return CustomerReference(
        home_country=profile.home_country,
        registered_devices=frozenset(profile.registered_devices),
        account_opened_at=profile.account_opened_at,
        avg_ticket_usd=profile.avg_ticket_usd,
    )


def build_training_frame(
    seed: int = 42,
    customers_per_tenant: int = 3000,
    days: int = 7,
    warmup_days: int = 0,
    start: datetime = DEFAULT_HISTORY_START,
) -> pd.DataFrame:
    live = SimulatorConfig()
    merchants = max(12, round(live.merchants_per_tenant * customers_per_tenant / live.customers_per_tenant))
    sim = TransactionSimulator(
        SimulatorConfig(seed=seed, customers_per_tenant=customers_per_tenant, merchants_per_tenant=merchants)
    )
    engine = FeatureEngine(InMemoryFeatureStore())
    end = start + timedelta(days=warmup_days + days)
    train_from = start + timedelta(days=warmup_days)
    refs: dict[tuple[str, str], CustomerReference] = {}
    records: list[dict] = []
    for ev in sim.generate(start, end):
        p = ev.payload
        key = (p.tenant_id, p.customer_id)
        if key not in refs:
            refs[key] = reference_for(sim.customer(*key))
        feats = engine.process(p, refs[key])
        if p.event_timestamp < train_from:
            continue
        records.append(
            {
                **feats,
                "event_timestamp": p.event_timestamp,
                "tenant_id": p.tenant_id,
                "merchant_category": p.merchant_category.value,
                "label": ev.label.ground_truth_label,
                "scenario": ev.label.scenario,
            }
        )
    return pd.DataFrame.from_records(records)
