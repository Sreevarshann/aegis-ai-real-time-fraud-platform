import jwt
import pytest

from aegis.investigation.llm import validate_grounding
from aegis.security import create_access_token, decode_access_token, hash_password, verify_password

EVIDENCE = [
    {"id": "E1", "title": "Transaction", "summary": "USD 950.00 at Atlas Electronics", "data": {"amount": 950.0}},
    {"id": "E2", "title": "Prediction", "summary": "Risk score 91/100", "data": {"risk_score": 91}},
]


def test_password_hashing():
    h = hash_password("correct horse")
    assert h != "correct horse" and verify_password("correct horse", h)
    assert not verify_password("wrong", h)
    assert not verify_password("x", "not-a-bcrypt-hash")


def test_jwt_round_trip_and_tamper_detection():
    token, ttl = create_access_token("00000000-0000-0000-0000-000000000001", "northwind", "analyst", "a@b.demo")
    claims = decode_access_token(token)
    assert claims["tid"] == "northwind" and claims["role"] == "analyst" and ttl > 0
    forged = jwt.encode(
        {**claims, "tid": "meridian"}, "attacker-controlled-secret-of-sufficient-length", algorithm="HS256"
    )
    with pytest.raises(jwt.InvalidSignatureError):
        decode_access_token(forged)


def test_grounding_accepts_cited_facts():
    text = "The transaction of 950.00 at Atlas Electronics [E1] scored 91 [E2]; human review is advised."
    assert validate_grounding(text, EVIDENCE) is None


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("Scored 91 [E2].", "fewer than two"),
        ("Amount 950.00 [E1] and score 91 [E2] and device history [E9].", "unknown evidence"),
        ("Amount 950.00 [E1] scored 91 [E2] after 47 prior chargebacks.", "not present"),
    ],
)
def test_grounding_rejects_hallucinations(text, problem):
    result = validate_grounding(text, EVIDENCE)
    assert result is not None and problem in result
