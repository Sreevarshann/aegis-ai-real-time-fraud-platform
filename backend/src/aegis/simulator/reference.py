"""Synthetic reference data: tenants, customers and merchants.

All identities are artificial. Profiles are generated deterministically from the seed so the
seeding job, the training job and the live stream agree on the same population without
sharing state.

Customer profiles model data a bank legitimately holds *before* a transaction happens
(KYC home country, enrolled devices, account age, typical ticket size). Fraud-only secrets
such as which merchants are compromised live in :mod:`aegis.simulator.generator` and are
never written to the database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import numpy as np

from aegis.events.schema import MerchantCategory

# ISO country -> (currency, UTC offset hours). Offsets are simplified (no DST).
COUNTRIES: dict[str, tuple[str, int]] = {
    "US": ("USD", -5),
    "CA": ("CAD", -5),
    "GB": ("GBP", 0),
    "DE": ("EUR", 1),
    "FR": ("EUR", 1),
    "NL": ("EUR", 1),
    "ES": ("EUR", 1),
    "IN": ("INR", 5),
    "SG": ("SGD", 8),
    "JP": ("JPY", 9),
    "BR": ("BRL", -3),
}
# Fixed synthetic FX rates used to normalise amounts to USD for feature computation.
USD_PER_UNIT: dict[str, float] = {
    "USD": 1.0,
    "CAD": 0.73,
    "GBP": 1.27,
    "EUR": 1.08,
    "INR": 0.012,
    "SGD": 0.74,
    "JPY": 0.0067,
    "BRL": 0.18,
}

# Category -> (relative ticket multiplier, popularity weight)
CATEGORY_PROFILE: dict[MerchantCategory, tuple[float, float]] = {
    MerchantCategory.GROCERY: (1.0, 0.24),
    MerchantCategory.RESTAURANTS: (0.8, 0.18),
    MerchantCategory.FUEL: (0.9, 0.10),
    MerchantCategory.UTILITIES: (2.2, 0.05),
    MerchantCategory.HEALTHCARE: (2.0, 0.04),
    MerchantCategory.FASHION: (1.8, 0.10),
    MerchantCategory.ELECTRONICS: (4.0, 0.06),
    MerchantCategory.TRAVEL: (5.0, 0.04),
    MerchantCategory.DIGITAL_GOODS: (0.6, 0.11),
    MerchantCategory.MONEY_TRANSFER: (3.5, 0.03),
    MerchantCategory.GAMBLING: (1.5, 0.02),
    MerchantCategory.CRYPTO_EXCHANGE: (4.5, 0.03),
}
CATEGORIES: list[MerchantCategory] = list(CATEGORY_PROFILE)


@dataclass(frozen=True)
class TenantProfile:
    tenant_id: str
    name: str
    prefix: str
    home_countries: tuple[tuple[str, float], ...]


DEFAULT_TENANTS: tuple[TenantProfile, ...] = (
    TenantProfile("northwind", "Northwind Bank (synthetic)", "NW", (("US", 0.9), ("CA", 0.1))),
    TenantProfile(
        "meridian",
        "Meridian Credit Union (synthetic)",
        "MR",
        (("GB", 0.6), ("DE", 0.15), ("FR", 0.1), ("NL", 0.08), ("ES", 0.07)),
    ),
)


@dataclass(frozen=True)
class CustomerProfile:
    tenant_id: str
    customer_id: str
    home_country: str
    registered_devices: tuple[str, ...]
    account_opened_at: datetime
    avg_ticket_usd: float
    daily_rate: float
    active_hour: float  # centre of the customer's typical local activity window
    preferred_merchants: tuple[int, ...] = field(default=())


@dataclass(frozen=True)
class MerchantProfile:
    tenant_id: str
    merchant_id: str
    name: str
    category: MerchantCategory
    country: str


@dataclass
class Population:
    tenant: TenantProfile
    customers: list[CustomerProfile]
    merchants: list[MerchantProfile]
    merchants_by_category: dict[MerchantCategory, list[int]]


_NAME_A = [
    "Harbor",
    "Summit",
    "Atlas",
    "Cobalt",
    "Lumen",
    "Orchid",
    "Granite",
    "Vela",
    "Juniper",
    "Ember",
    "Quill",
    "Nimbus",
    "Cedar",
    "Pioneer",
    "Aurora",
    "Kestrel",
]
_NAME_B = {
    MerchantCategory.GROCERY: "Market",
    MerchantCategory.RESTAURANTS: "Kitchen",
    MerchantCategory.FUEL: "Fuel Stop",
    MerchantCategory.UTILITIES: "Utilities",
    MerchantCategory.HEALTHCARE: "Clinic",
    MerchantCategory.FASHION: "Apparel",
    MerchantCategory.ELECTRONICS: "Electronics",
    MerchantCategory.TRAVEL: "Travel",
    MerchantCategory.DIGITAL_GOODS: "Digital",
    MerchantCategory.MONEY_TRANSFER: "Remit",
    MerchantCategory.GAMBLING: "Gaming",
    MerchantCategory.CRYPTO_EXCHANGE: "Crypto Exchange",
}

REFERENCE_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


def device_id_for(rng: np.random.Generator) -> str:
    return "dev-" + "".join(rng.choice(list("0123456789abcdef"), size=12))


def build_population(
    tenant: TenantProfile, n_customers: int, n_merchants: int, seed: int, tenant_index: int
) -> Population:
    rng = np.random.default_rng([seed, tenant_index, 7])
    merchants: list[MerchantProfile] = []
    weights = np.array([CATEGORY_PROFILE[c][1] for c in CATEGORIES])
    cat_idx = rng.choice(len(CATEGORIES), size=n_merchants, p=weights / weights.sum())
    home_codes = [c for c, _ in tenant.home_countries]
    home_p = np.array([p for _, p in tenant.home_countries])
    for i in range(n_merchants):
        cat = CATEGORIES[int(cat_idx[i])]
        country = str(rng.choice(home_codes, p=home_p))
        merchants.append(
            MerchantProfile(
                tenant.tenant_id,
                f"{tenant.prefix}-M{i:05d}",
                f"{_NAME_A[int(rng.integers(len(_NAME_A)))]} {_NAME_B[cat]} #{i}",
                cat,
                country,
            )
        )
    by_cat: dict[MerchantCategory, list[int]] = {c: [] for c in CATEGORIES}
    for i, m in enumerate(merchants):
        by_cat[m.category].append(i)

    customers: list[CustomerProfile] = []
    countries = rng.choice(home_codes, size=n_customers, p=home_p)
    avg_ticket = rng.lognormal(mean=3.4, sigma=0.55, size=n_customers)  # ~ $30 median
    rates = rng.gamma(shape=2.0, scale=2.0, size=n_customers)  # ~4 tx/day mean
    hours = rng.normal(14.0, 3.0, size=n_customers).clip(7, 22)
    ages = rng.integers(30, 3650, size=n_customers)
    n_devices = rng.choice([1, 2, 3], size=n_customers, p=[0.55, 0.35, 0.10])
    for i in range(n_customers):
        devices = tuple(device_id_for(rng) for _ in range(int(n_devices[i])))
        prefs = tuple(int(x) for x in rng.choice(n_merchants, size=6, replace=False))
        customers.append(
            CustomerProfile(
                tenant_id=tenant.tenant_id,
                customer_id=f"{tenant.prefix}-C{i:06d}",
                home_country=str(countries[i]),
                registered_devices=devices,
                account_opened_at=REFERENCE_EPOCH - timedelta(days=int(ages[i])),
                avg_ticket_usd=round(float(avg_ticket[i]), 2),
                daily_rate=float(max(rates[i], 0.3)),
                active_hour=float(hours[i]),
                preferred_merchants=prefs,
            )
        )
    return Population(tenant, customers, merchants, by_cat)
