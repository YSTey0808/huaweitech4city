"""Tests for gnn/llm_stage.py's prompt construction and the human-feedback
report section added on top of it. No real Anthropic calls are made --
run_llm_reasoning's tests monkeypatch _get_client with a fake client."""

import json

import pytest

from gnn import llm_stage


EVIDENCE = [
    {"message_id": "m1", "sender_id": "u1", "score": 0.91, "text": "send me $500 now"},
    {"message_id": "m2", "sender_id": "u2", "score": 0.10, "text": "ok sure"},
]


def test_build_prompt_without_report_has_no_report_section():
    prompt = llm_stage.build_prompt("conv1", EVIDENCE, 0.75)
    assert "REPORTED" not in prompt
    assert "conv1" in prompt
    assert "0.7500" in prompt  # conversation_score formatted to 4dp


def test_build_prompt_includes_evidence_lines():
    prompt = llm_stage.build_prompt("conv1", EVIDENCE, 0.75)
    assert 'id=m1, sender=u1, model_score=0.91: "send me $500 now"' in prompt
    assert 'id=m2, sender=u2, model_score=0.10: "ok sure"' in prompt


def test_build_prompt_with_report_includes_message_id_and_reason():
    user_report = {"message_id": "m2", "reason": "this is grooming, not just small talk"}
    prompt = llm_stage.build_prompt("conv1", EVIDENCE, 0.05, user_report=user_report)
    assert "REPORTED message id=m2" in prompt
    assert "this is grooming, not just small talk" in prompt


def test_build_prompt_report_section_placed_before_output_spec():
    user_report = {"message_id": "m2", "reason": "scam"}
    prompt = llm_stage.build_prompt("conv1", EVIDENCE, 0.05, user_report=user_report)
    assert prompt.index("REPORTED") < prompt.index("Respond with ONLY")


def test_build_prompt_report_tells_llm_not_to_rubber_stamp():
    # The veto framing is what stops a bogus/mistaken report from being an
    # automatic override -- assert the instruction is actually present, not
    # just that a report section exists at all. Normalize whitespace since
    # the source f-string wraps this sentence across a line break.
    user_report = {"message_id": "m2", "reason": "scam"}
    prompt = llm_stage.build_prompt("conv1", EVIDENCE, 0.05, user_report=user_report)
    normalized = " ".join(prompt.split())
    assert "Do not rubber-stamp it either" in normalized


class _FakeMessage:
    def __init__(self, text):
        self.content = [type("Block", (), {"text": text})()]


class _FakeMessages:
    def __init__(self, response_text):
        self._response_text = response_text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeMessage(self._response_text)


class _FakeClient:
    def __init__(self, response_text):
        self.messages = _FakeMessages(response_text)


def test_run_llm_reasoning_forwards_user_report_to_prompt(monkeypatch):
    canned = json.dumps({
        "conversation_label": "harmful", "conversation_confidence": 0.8,
        "severity": "medium", "top_evidence_messages": [], "gentle_alert_text": "x",
    })
    fake_client = _FakeClient(canned)
    monkeypatch.setattr(llm_stage, "_get_client", lambda: fake_client)

    user_report = {"message_id": "m2", "reason": "this is a scam"}
    result_text = llm_stage.run_llm_reasoning("conv1", EVIDENCE, 0.05, user_report=user_report)

    assert result_text == canned
    sent_prompt = fake_client.messages.calls[0]["messages"][0]["content"]
    assert "REPORTED message id=m2" in sent_prompt
    assert "this is a scam" in sent_prompt


def test_run_llm_reasoning_without_report_has_clean_prompt(monkeypatch):
    canned = json.dumps({
        "conversation_label": "safe", "conversation_confidence": 0.1,
        "severity": None, "top_evidence_messages": [], "gentle_alert_text": None,
    })
    fake_client = _FakeClient(canned)
    monkeypatch.setattr(llm_stage, "_get_client", lambda: fake_client)

    llm_stage.run_llm_reasoning("conv1", EVIDENCE, 0.75)

    sent_prompt = fake_client.messages.calls[0]["messages"][0]["content"]
    assert "REPORTED" not in sent_prompt
