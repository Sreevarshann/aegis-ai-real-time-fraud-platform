"""Idempotent seeding of demo tenants, users and synthetic reference data.

    python -m aegis.seed

Demo passwords come from AEGIS_DEMO_USER_PASSWORD (a non-production local value, see
.env.example). Everything seeded here is synthetic.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Engine, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from aegis.config import get_settings
from aegis.db.engine import get_engine
from aegis.db.tables import customers, merchants, tenants, users
from aegis.observability.logging import configure_logging, get_logger
from aegis.security import hash_password
from aegis.simulator.generator import SimulatorConfig
from aegis.simulator.reference import DEFAULT_TENANTS, build_population

log = get_logger(__name__)

DEMO_USERS = (
    ("northwind", "admin@northwind.demo", "Avery Admin", "admin"),
    ("northwind", "analyst@northwind.demo", "Riley Analyst", "analyst"),
    ("northwind", "viewer@northwind.demo", "Jordan Viewer", "viewer"),
    ("meridian", "admin@meridian.demo", "Morgan Admin", "admin"),
    ("meridian", "analyst@meridian.demo", "Casey Analyst", "analyst"),
)


def seed(engine: Engine | None = None, customers_per_tenant: int | None = None) -> dict[str, int]:
    s = get_settings()
    engine = engine or get_engine()
    cfg = SimulatorConfig(seed=s.simulator_seed)
    n_customers = customers_per_tenant or cfg.customers_per_tenant
    with engine.begin() as conn:
        for t in DEFAULT_TENANTS:
            conn.execute(pg_insert(tenants).values(tenant_id=t.tenant_id, name=t.name).on_conflict_do_nothing())
        pw_hash = hash_password(s.demo_user_password)
        for tenant_id, email, name, role in DEMO_USERS:
            conn.execute(
                pg_insert(users)
                .values(
                    user_id=uuid.uuid5(uuid.NAMESPACE_DNS, email),
                    tenant_id=tenant_id,
                    email=email,
                    full_name=name,
                    password_hash=pw_hash,
                    role=role,
                )
                .on_conflict_do_nothing()
            )

        for i, t in enumerate(DEFAULT_TENANTS):
            existing = conn.execute(
                select(func.count()).select_from(customers).where(customers.c.tenant_id == t.tenant_id)
            ).scalar_one()
            if existing >= n_customers:
                continue
            pop = build_population(t, n_customers, cfg.merchants_per_tenant, s.simulator_seed, i)
            mrows = [
                {
                    "tenant_id": m.tenant_id,
                    "merchant_id": m.merchant_id,
                    "name": m.name,
                    "category": m.category.value,
                    "country": m.country,
                }
                for m in pop.merchants
            ]
            conn.execute(pg_insert(merchants).on_conflict_do_nothing(), mrows)
            crows = [
                {
                    "tenant_id": c.tenant_id,
                    "customer_id": c.customer_id,
                    "home_country": c.home_country,
                    "registered_devices": list(c.registered_devices),
                    "account_opened_at": c.account_opened_at,
                    "avg_ticket_usd": c.avg_ticket_usd,
                }
                for c in pop.customers
            ]
            for start in range(0, len(crows), 5000):
                conn.execute(pg_insert(customers).on_conflict_do_nothing(), crows[start : start + 5000])
        counts = {
            tbl.name: int(conn.execute(select(func.count()).select_from(tbl)).scalar_one())
            for tbl in (tenants, users, customers, merchants)
        }
    log.info("seed_complete", **counts)
    return counts


def main() -> None:
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    seed()


if __name__ == "__main__":
    main()
