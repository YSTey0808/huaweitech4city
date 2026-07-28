import pytest
from pydantic import ValidationError

from app.schemas.report import ReportRequest


def test_report_request_valid_trims_reason():
    r = ReportRequest(conversation_id="c1", msg_id="m1", reason="  this is a scam  ")
    assert r.reason == "this is a scam"


def test_report_request_blank_reason_rejected():
    with pytest.raises(ValidationError):
        ReportRequest(conversation_id="c1", msg_id="m1", reason="   ")


def test_report_request_missing_field_rejected():
    with pytest.raises(ValidationError):
        ReportRequest(conversation_id="c1", reason="scam")  # msg_id missing


def test_report_request_claim_defaults_to_harmful():
    r = ReportRequest(conversation_id="c1", msg_id="m1", reason="scam")
    assert r.claim == "harmful"


def test_report_request_claim_safe_accepted():
    r = ReportRequest(conversation_id="c1", msg_id="m1", reason="not a scam", claim="safe")
    assert r.claim == "safe"


def test_report_request_unknown_claim_rejected():
    with pytest.raises(ValidationError):
        ReportRequest(conversation_id="c1", msg_id="m1", reason="x", claim="maybe")
