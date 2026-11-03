from datetime import UTC, datetime, timedelta

from aegis.events.schema import TransactionPayload
from aegis.simulator.generator import FRAUD_SCENARIOS, SimulatorConfig, TransactionSimulator

START = datetime(2026, 9, 1, tzinfo=UTC)


def small_sim(seed: int = 7, **kw) -> TransactionSimulator:
    return TransactionSimulator(SimulatorConfig(seed=seed, customers_per_tenant=400, merchants_per_tenant=40, **kw))


def test_generation_is_reproducible_for_a_fixed_seed():
    a = small_sim().generate(START, START + timedelta(hours=12))
    b = small_sim().generate(START, START + timedelta(hours=12))
    assert len(a) > 100
    assert [e.payload for e in a] == [e.payload for e in b]
    assert [e.label for e in a] == [e.label for e in b]


def test_different_seeds_produce_different_streams():
    a = small_sim(seed=1).generate(START, START + timedelta(hours=6))
    b = small_sim(seed=2).generate(START, START + timedelta(hours=6))
    assert [e.payload.transaction_id for e in a[:20]] != [e.payload.transaction_id for e in b[:20]]


def test_events_are_time_ordered_valid_and_bounded():
    events = small_sim().generate(START, START + timedelta(days=1))
    ts = [e.payload.event_timestamp for e in events]
    assert ts == sorted(ts)
    assert all(START <= t < START + timedelta(days=1) for t in ts)
    for e in events[:200]:
        TransactionPayload.model_validate(e.payload.model_dump())  # round-trips through the contract


def test_fraud_rate_is_realistic_and_all_scenarios_occur():
    events = small_sim().generate(START, START + timedelta(days=10))
    labels = [e.label for e in events]
    rate = sum(lbl.ground_truth_label for lbl in labels) / len(labels)
    assert 0.005 < rate < 0.06
    fraud_scenarios = {lbl.scenario for lbl in labels if lbl.ground_truth_label == 1}
    assert fraud_scenarios == set(FRAUD_SCENARIOS)
    # Hard negatives exist so "unusual" is not synonymous with "fraud".
    assert {"legit_travel", "legit_new_device", "legit_large_purchase"} <= {lbl.scenario for lbl in labels}


def test_forced_scenarios_are_labelled_fraud():
    sim = small_sim()
    for scenario in FRAUD_SCENARIOS:
        events = sim.fraud_incident("northwind", START, scenario)
        assert any(e.label.ground_truth_label == 1 and e.label.scenario == scenario for e in events)
        assert all(e.payload.tenant_id == "northwind" for e in events)


def test_identities_are_synthetic():
    events = small_sim().generate(START, START + timedelta(hours=6))
    for e in events:
        assert e.payload.customer_id.startswith(("NW-C", "MR-C"))
        assert e.payload.merchant_id.startswith(("NW-M", "MR-M"))
