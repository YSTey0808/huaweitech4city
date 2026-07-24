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
