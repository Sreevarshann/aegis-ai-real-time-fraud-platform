import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from aegis.events.schema import EventRejected, TransactionPayload, parse_envelope, payload_hash
from aegis.streaming.defects import INVALID_KINDS, corrupt


def envelope(**payload_overrides) -> dict:
    payload = {
        "transaction_id": str(uuid4()),
        "tenant_id": "northwind",
        "event_timestamp": "2026-11-02T10:00:00Z",
        "customer_id": "NW-C000001",
        "merchant_id": "NW-M00001",
        "merchant_category": "grocery",
        "transaction_amount": "42.10",
        "currency": "USD",
        "transaction_country": "US",
        "device_id": "dev-abc",
        "payment_channel": "card_present",
        "transaction_status": "approved",
    } | payload_overrides
    return {
        "schema_version": "1.0",
        "event_type": "transaction.created",
        "event_id": str(uuid4()),
        "produced_at": "2026-11-02T10:00:01Z",
        "payload": payload,
        "simulation": {"ground_truth_label": 0, "scenario": "normal"},
    }


def test_valid_envelope_parses_and_normalises_timezone():
    env = parse_envelope(json.dumps(envelope(event_timestamp="2026-11-02T05:00:00-05:00")))
    assert env.payload.event_timestamp == datetime(2026, 11, 2, 10, tzinfo=UTC)
    assert env.simulation is not None and env.simulation.ground_truth_label == 0


def test_payload_model_has_no_label_field():
    # Structural guard against target leakage: the scoring input cannot carry the label.
    assert "ground_truth_label" not in TransactionPayload.model_fields
    with pytest.raises(EventRejected):
        parse_envelope(json.dumps(envelope(ground_truth_label=1)))  # extra fields are forbidden


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"transaction_amount": "-5.00"}, "schema_validation_failed"),
        ({"transaction_amount": "0"}, "schema_validation_failed"),
        ({"currency": "ZZZ"}, "schema_validation_failed"),
        ({"transaction_country": "usa"}, "schema_validation_failed"),
        ({"customer_id": "bad id; drop table"}, "schema_validation_failed"),
        ({"event_timestamp": "2026-11-02T10:00:00"}, "schema_validation_failed"),
        ({"merchant_category": "weapons"}, "schema_validation_failed"),
    ],
)
def test_invalid_payloads_are_rejected_with_reason(overrides, reason):
    with pytest.raises(EventRejected) as exc:
        parse_envelope(json.dumps(envelope(**overrides)))
    assert exc.value.reason == reason
    assert exc.value.tenant_id == "northwind"


def test_malformed_json_and_versions():
    with pytest.raises(EventRejected) as e1:
        parse_envelope(b"{not json")
    assert e1.value.reason == "malformed_json"
    with pytest.raises(EventRejected) as e2:
        parse_envelope(b"[1,2,3]")
    assert e2.value.reason == "malformed_json"
    doc = envelope()
    doc["schema_version"] = "2.0"
    with pytest.raises(EventRejected) as e3:
        parse_envelope(json.dumps(doc))
    assert e3.value.reason == "unsupported_schema_version"


@pytest.mark.parametrize("kind", [k for k in INVALID_KINDS if k != "unknown_customer"])
def test_every_injected_defect_is_rejected(kind):
    with pytest.raises(EventRejected):
        parse_envelope(corrupt(envelope(), kind))


def test_payload_hash_is_content_based():
    a = parse_envelope(json.dumps(envelope())).payload
    b = TransactionPayload.model_validate(a.model_dump())
    c = TransactionPayload.model_validate(a.model_dump() | {"transaction_amount": "42.11"})
    assert payload_hash(a) == payload_hash(b)
    assert payload_hash(a) != payload_hash(c)
