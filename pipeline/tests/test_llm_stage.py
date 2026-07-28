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


def test_build_prompt_report_asks_for_dismissal_reasoning():
    # The backend stores gentle_alert_text as the report's outcome_reasoning
    # on dismissal (see backend report_service) -- the prompt must actually
    # ask for a reporter-addressed explanation or that field is generic.
    user_report = {"message_id": "m2", "reason": "scam"}
    prompt = llm_stage.build_prompt("conv1", EVIDENCE, 0.05, user_report=user_report)
    normalized = " ".join(prompt.split())
    assert 'If you conclude "safe" despite this report' in normalized


def test_build_prompt_safe_claim_renders_dispute_section():
    user_report = {"message_id": "m1", "reason": "thats just my aunt", "claim": "safe"}
    prompt = llm_stage.build_prompt("conv1", EVIDENCE, 0.9, user_report=user_report)
    assert "DISPUTED the flag on message" in prompt
    assert "thats just my aunt" in prompt
    assert "REPORTED message id=" not in prompt  # not the harmful-claim framing
    # And the flag-stands explanation ask is present for rejections.
    normalized = " ".join(prompt.split())
    assert 'If you conclude "harmful" despite this dispute' in normalized


def test_build_prompt_missing_claim_defaults_to_harmful_framing():
    # Pre-claim callers pass {message_id, reason} only -- must keep the
    # original report framing, not the dispute one.
    user_report = {"message_id": "m2", "reason": "scam"}
    prompt = llm_stage.build_prompt("conv1", EVIDENCE, 0.05, user_report=user_report)
    assert "REPORTED message id=m2" in prompt
    assert "DISPUTED" not in prompt


def test_build_prompt_safe_examples_render_as_false_positive_section():
    examples = [
        {"text": "send otp now", "reason": "otp scam", "label": "scam"},
        {"text": "eh you free tonight", "reason": "just my aunt", "label": "safe"},
    ]
    prompt = llm_stage.build_prompt("conv1", EVIDENCE, 0.5, confirmed_examples=examples)
    assert "Known harmful patterns" in prompt
    assert "Known FALSE-POSITIVE patterns" in prompt
    assert '"eh you free tonight"' in prompt
    # Safe examples live in the false-positive section, after the harmful one.
    assert prompt.index("Known harmful patterns") < prompt.index("Known FALSE-POSITIVE patterns")


def test_build_prompt_only_safe_examples_renders_only_false_positive_section():
    examples = [{"text": "eh you free tonight", "reason": "just my aunt", "label": "safe"}]
    prompt = llm_stage.build_prompt("conv1", EVIDENCE, 0.5, confirmed_examples=examples)
    assert "Known FALSE-POSITIVE patterns" in prompt
    assert "Known harmful patterns" not in prompt


def test_build_prompt_without_examples_has_no_examples_section():
    prompt = llm_stage.build_prompt("conv1", EVIDENCE, 0.75)
    assert "Known harmful patterns" not in prompt


def test_build_prompt_with_confirmed_examples_includes_them():
    examples = [
        {"text": "send otp now", "reason": "asked for my otp", "label": "scam"},
        {"text": "nobody likes you", "reason": "bullying my kid", "label": "cyberbullying"},
    ]
    prompt = llm_stage.build_prompt("conv1", EVIDENCE, 0.75, confirmed_examples=examples)
    assert "Known harmful patterns" in prompt
    assert 'label=scam, reporter said "asked for my otp": "send otp now"' in prompt
    assert 'label=cyberbullying, reporter said "bullying my kid": "nobody likes you"' in prompt
    # Reference patterns must come after the conversation's own messages and
    # before the output spec.
    assert prompt.index("ok sure") < prompt.index("Known harmful patterns") < prompt.index("Respond with ONLY")


def test_build_prompt_examples_and_report_can_coexist():
    examples = [{"text": "send otp now", "reason": "otp scam", "label": "scam"}]
    user_report = {"message_id": "m2", "reason": "same pattern happening to me"}
    prompt = llm_stage.build_prompt("conv1", EVIDENCE, 0.05,
                                    user_report=user_report, confirmed_examples=examples)
    assert "Known harmful patterns" in prompt
    assert "REPORTED message id=m2" in prompt


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
