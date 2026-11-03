"""Point-in-time feature engineering shared by offline training and online scoring.

``compute_features`` is a pure function of (transaction payload, customer reference data,
entity history strictly before the transaction). It never sees the simulation label.
Missing-by-design values (e.g. no history yet) are ``NaN`` rather than a fake default so the
model can learn cold-start behaviour explicitly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from aegis.events.schema import PaymentChannel, TransactionPayload, TransactionStatus
from aegis.features.store import (
    CustomerEvent,
    DeviceEvent,
    EntityHistory,
    FeatureStore,
    MerchantEvent,
)
from aegis.simulator.reference import COUNTRIES, USD_PER_UNIT

NAN = float("nan")

# Order matters: it is the column order of the model matrix. ``merchant_category_risk`` is
# appended by the model bundle because it is a target encoding fitted on the training split.
BASE_FEATURES: tuple[str, ...] = (
    "amount_usd_log",
    "amount_vs_typical_log",
    "amount_zscore_customer",
    "customer_txn_count_1h",
    "customer_txn_count_24h",
    "customer_amount_sum_1h_log",
    "minutes_since_last_txn",
    "local_hour_sin",
    "local_hour_cos",
    "hour_rarity",
    "is_new_device",
    "device_customer_count_24h",
    "is_foreign_country",
    "is_new_country",
    "minutes_since_other_country",
    "distinct_countries_24h",
    "merchant_txn_count_1h",
    "merchant_distinct_customers_1h",
    "merchant_decline_rate_24h",
    "channel_ecommerce",
    "channel_mobile_wallet",
    "channel_bank_transfer",
    "is_declined",
    "account_age_days",
)

FEATURE_DESCRIPTIONS: dict[str, str] = {
    "amount_usd_log": "transaction amount (USD, log scale)",
    "amount_vs_typical_log": "amount relative to the customer's typical spend",
    "amount_zscore_customer": "amount z-score against the customer's own history",
    "customer_txn_count_1h": "customer transactions in the previous hour",
    "customer_txn_count_24h": "customer transactions in the previous 24 hours",
    "customer_amount_sum_1h_log": "customer spend in the previous hour",
    "minutes_since_last_txn": "minutes since the customer's previous transaction",
    "local_hour_sin": "local time of day",
    "local_hour_cos": "local time of day",
    "hour_rarity": "how unusual this hour is for the customer",
    "is_new_device": "device never seen for this customer",
    "device_customer_count_24h": "distinct customers on this device in 24 hours",
    "is_foreign_country": "transaction outside the customer's home country",
    "is_new_country": "country never seen for this customer",
    "minutes_since_other_country": "minutes since a transaction in a different country",
    "distinct_countries_24h": "distinct countries in 24 hours",
    "merchant_txn_count_1h": "merchant transactions in the previous hour",
    "merchant_distinct_customers_1h": "distinct customers at the merchant in the previous hour",
    "merchant_decline_rate_24h": "merchant decline rate over 24 hours",
    "channel_ecommerce": "card-not-present e-commerce channel",
    "channel_mobile_wallet": "mobile wallet channel",
    "channel_bank_transfer": "bank transfer channel",
    "is_declined": "authorisation was declined",
    "account_age_days": "account age in days",
    "merchant_category_risk": "historical fraud rate of the merchant category",
}


@dataclass(frozen=True, slots=True)
class CustomerReference:
    """Reference data a bank holds before the transaction (KYC + enrolment)."""

    home_country: str
    registered_devices: frozenset[str]
    account_opened_at: datetime
    avg_ticket_usd: float


def amount_usd(payload: TransactionPayload) -> float:
    return float(payload.transaction_amount) * USD_PER_UNIT[payload.currency]


def local_hour(ts: datetime, country: str) -> float:
    offset = COUNTRIES.get(country, ("USD", 0))[1]
    return (ts.hour + ts.minute / 60 + offset) % 24


def _hour_distance(a: float, b: float) -> float:
    d = abs(a - b) % 24
    return min(d, 24 - d)


def compute_features(payload: TransactionPayload, ref: CustomerReference, hist: EntityHistory) -> dict[str, float]:
    ts = payload.event_timestamp.timestamp()
    amt = amount_usd(payload)
    hour = local_hour(payload.event_timestamp, ref.home_country)
    cust = hist.customer
    c1h = [e for e in cust if e.ts >= ts - 3600]
    c24h = [e for e in cust if e.ts >= ts - 86_400]

    if len(cust) >= 5:
        logs = [math.log1p(e.amount_usd) for e in cust]
        mean = sum(logs) / len(logs)
        std = math.sqrt(sum((x - mean) ** 2 for x in logs) / (len(logs) - 1)) or 1e-6
        zscore = (math.log1p(amt) - mean) / max(std, 0.05)
        typical = math.exp(mean) - 1
        hour_rarity = 1.0 - sum(1 for e in cust if _hour_distance(e.local_hour, hour) <= 2) / len(cust)
    else:
        zscore = NAN
        typical = ref.avg_ticket_usd
        hour_rarity = NAN

    known_devices = ref.registered_devices | {e.device_id for e in cust}
    seen_countries = {e.country for e in cust}
    other_country = [e for e in c24h if e.country != payload.transaction_country]
    last = max((e.ts for e in cust), default=None)

    merch = hist.merchant
    m1h = [e for e in merch if e.ts >= ts - 3600]
    m24h = [e for e in merch if e.ts >= ts - 86_400]
    dev24 = {e.customer_id for e in hist.device if e.ts >= ts - 86_400} | {payload.customer_id}

    channel = payload.payment_channel
    angle = 2 * math.pi * hour / 24
    return {
        "amount_usd_log": math.log1p(amt),
        "amount_vs_typical_log": math.log((amt + 1) / (max(typical, 0.0) + 1)),
        "amount_zscore_customer": zscore,
        "customer_txn_count_1h": float(len(c1h)),
        "customer_txn_count_24h": float(len(c24h)),
        "customer_amount_sum_1h_log": math.log1p(sum(e.amount_usd for e in c1h)),
        "minutes_since_last_txn": min((ts - last) / 60, 7 * 1440) if last is not None else NAN,
        "local_hour_sin": math.sin(angle),
        "local_hour_cos": math.cos(angle),
        "hour_rarity": hour_rarity,
        "is_new_device": float(payload.device_id not in known_devices),
        "device_customer_count_24h": float(len(dev24)),
        "is_foreign_country": float(payload.transaction_country != ref.home_country),
        "is_new_country": float(
            payload.transaction_country != ref.home_country and payload.transaction_country not in seen_countries
        ),
        "minutes_since_other_country": (ts - max(e.ts for e in other_country)) / 60 if other_country else NAN,
        "distinct_countries_24h": float(len({e.country for e in c24h} | {payload.transaction_country})),
        "merchant_txn_count_1h": float(len(m1h)),
        "merchant_distinct_customers_1h": float(len({e.customer_id for e in m1h})),
        "merchant_decline_rate_24h": (sum(e.declined for e in m24h) / len(m24h)) if len(m24h) >= 5 else NAN,
        "channel_ecommerce": float(channel is PaymentChannel.ECOMMERCE),
        "channel_mobile_wallet": float(channel is PaymentChannel.MOBILE_WALLET),
        "channel_bank_transfer": float(channel is PaymentChannel.BANK_TRANSFER),
        "is_declined": float(payload.transaction_status is TransactionStatus.DECLINED),
        "account_age_days": float((payload.event_timestamp - ref.account_opened_at).days),
    }


class FeatureEngine:
    """Compute features for a transaction, then fold it into the rolling state."""

    def __init__(self, store: FeatureStore) -> None:
        self.store = store

    def process(self, payload: TransactionPayload, ref: CustomerReference) -> dict[str, float]:
        ts = payload.event_timestamp.timestamp()
        txn = str(payload.transaction_id)
        hist = self.store.history(
            payload.tenant_id, payload.customer_id, payload.merchant_id, payload.device_id, txn, ts
        )
        features = compute_features(payload, ref, hist)
        self.store.record(
            payload.tenant_id,
            payload.customer_id,
            payload.merchant_id,
            CustomerEvent(
                txn,
                ts,
                round(amount_usd(payload), 4),
                payload.transaction_country,
                payload.device_id,
                round(local_hour(payload.event_timestamp, ref.home_country), 4),
            ),
            MerchantEvent(txn, ts, payload.customer_id, payload.transaction_status is TransactionStatus.DECLINED),
            DeviceEvent(txn, ts, payload.customer_id),
        )
        return features
