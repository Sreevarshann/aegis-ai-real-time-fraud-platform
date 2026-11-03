import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from aegis.events.schema import TransactionPayload
from aegis.features.compute import BASE_FEATURES, CustomerReference, FeatureEngine
from aegis.features.store import InMemoryFeatureStore

T0 = datetime(2026, 10, 1, 15, tzinfo=UTC)
REF = CustomerReference("US", frozenset({"dev-home"}), datetime(2024, 1, 1, tzinfo=UTC), 40.0)


def txn(
    minutes: float = 0,
    amount: str = "40.00",
    device: str = "dev-home",
    country: str = "US",
    merchant: str = "NW-M00001",
    customer: str = "NW-C000001",
    tid=None,
) -> TransactionPayload:
    return TransactionPayload(
        transaction_id=tid or uuid4(),
        tenant_id="northwind",
        event_timestamp=T0 + timedelta(minutes=minutes),
        customer_id=customer,
        merchant_id=merchant,
        merchant_category="grocery",
        transaction_amount=Decimal(amount),
        currency="USD" if country == "US" else "EUR",
        transaction_country=country,
        device_id=device,
        payment_channel="card_present",
        transaction_status="approved",
    )


def test_feature_vector_is_complete_and_cold_start_uses_nan():
    f = FeatureEngine(InMemoryFeatureStore()).process(txn(), REF)
    assert set(f) == set(BASE_FEATURES)
    assert math.isnan(f["amount_zscore_customer"]) and math.isnan(f["minutes_since_last_txn"])
    assert f["customer_txn_count_1h"] == 0 and f["is_new_device"] == 0.0


def test_velocity_novelty_and_travel_features():
    eng = FeatureEngine(InMemoryFeatureStore())
    for i in range(6):
        eng.process(txn(minutes=-300 + i * 10), REF)
    f = eng.process(txn(minutes=0, amount="900.00", device="dev-new", country="DE"), REF)
    assert f["customer_txn_count_24h"] == 6 and f["customer_txn_count_1h"] == 0
    assert f["is_new_device"] == 1.0 and f["is_foreign_country"] == 1.0 and f["is_new_country"] == 1.0
    assert f["amount_zscore_customer"] > 3
    assert f["minutes_since_other_country"] == 250.0


def test_merchant_and_device_sharing_features():
    eng = FeatureEngine(InMemoryFeatureStore())
    for i in range(5):
        eng.process(txn(minutes=-30 + i, customer=f"NW-C00000{i}", device="dev-shared"), REF)
    f = eng.process(txn(minutes=0, customer="NW-C000009", device="dev-shared"), REF)
    assert f["merchant_txn_count_1h"] == 5 and f["merchant_distinct_customers_1h"] == 5
    assert f["device_customer_count_24h"] == 6


def test_replaying_a_transaction_does_not_change_its_features():
    """At-least-once redelivery must be harmless: the stored copy of a txn is excluded when re-scored."""
    eng = FeatureEngine(InMemoryFeatureStore())
    eng.process(txn(minutes=-5), REF)
    tid = uuid4()
    first = eng.process(txn(minutes=0, tid=tid), REF)
    again = eng.process(txn(minutes=0, tid=tid), REF)
    assert first == again or all(
        (math.isnan(a) and math.isnan(b)) or a == b for a, b in zip(first.values(), again.values(), strict=True)
    )


def test_late_event_does_not_see_the_future():
    eng = FeatureEngine(InMemoryFeatureStore())
    eng.process(txn(minutes=0), REF)
    late = eng.process(txn(minutes=-120), REF)
    assert late["customer_txn_count_24h"] == 0
