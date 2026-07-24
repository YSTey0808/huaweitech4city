"""Tests for inference.py: rank_messages' ranking logic, and
score_conversation's cost short-circuit + user_report wiring. build_message_graph
and the real MessageGraphSAGE are swapped for fakes -- these tests are about
the decision logic added around them, not GraphSAGE itself."""

import json

import pytest
import torch

import inference
from gnn.config import SKIP_LLM_BELOW


def make_messages(n):
    return [
        {"message_id": f"m{i}", "sender_id": "u1", "text": f"text {i}", "reply_to_message_id": None}
        for i in range(n)
    ]


# ---- rank_messages ----

def test_rank_messages_orders_by_score_descending():
    messages = make_messages(5)
    scores = torch.tensor([0.9, 0.8, 0.7, 0.1, 0.05])
    out = inference.rank_messages(messages, scores)
    assert [e["message_id"] for e in out] == ["m0", "m1", "m2", "m3", "m4"]


def test_rank_messages_never_filters_anything_out():
    # Load-bearing for the whole "LLM as final judge" design: nothing gets
    # excluded regardless of how low a message's own score is.
    messages = make_messages(5)
    scores = torch.tensor([0.9, 0.8, 0.7, 0.1, 0.01])
    out = inference.rank_messages(messages, scores)
    assert len(out) == 5
    assert {e["message_id"] for e in out} == {"m0", "m1", "m2", "m3", "m4"}


def test_rank_messages_preserves_message_fields():
    messages = make_messages(2)
    scores = torch.tensor([0.5, 0.5])
    out = inference.rank_messages(messages, scores)
    assert out[0]["sender_id"] == "u1"
    assert out[0]["text"] == "text 0" or out[0]["text"] == "text 1"


# ---- score_conversation ----

class FakeModel:
    """Stands in for MessageGraphSAGE: score_conversation only ever calls
    .eval() and .forward_full(graph) on it."""

    def __init__(self, conv_score: float, per_message_scores: list):
        self._conv_score = torch.tensor(conv_score)
        self._per_message_scores = torch.tensor(per_message_scores)

    def eval(self):
        pass

    def forward_full(self, graph):
        return self._conv_score, self._per_message_scores


@pytest.fixture(autouse=True)
def stub_build_message_graph(monkeypatch):
    # The graph structure itself is irrelevant to the logic under test --
    # FakeModel.forward_full ignores whatever it's handed.
    monkeypatch.setattr(inference, "build_message_graph", lambda messages: messages)


@pytest.fixture
def llm_spy(monkeypatch):
    calls = []

    def fake_run_llm_reasoning(conversation_id, messages, conversation_score, user_report=None):
        calls.append({
            "conversation_id": conversation_id,
            "messages": messages,
            "conversation_score": conversation_score,
            "user_report": user_report,
        })
        return json.dumps({
            "conversation_label": "harmful",
            "conversation_confidence": 0.9,
            "severity": "high",
            "top_evidence_messages": messages,
            "gentle_alert_text": "flagged",
        })

    monkeypatch.setattr(inference, "run_llm_reasoning", fake_run_llm_reasoning)
    return calls


def test_score_conversation_skips_llm_below_threshold_with_no_report(llm_spy):
    messages = make_messages(3)
    model = FakeModel(conv_score=SKIP_LLM_BELOW / 2, per_message_scores=[0.01, 0.01, 0.01])

    result = inference.score_conversation("conv1", messages, model)

    assert llm_spy == []  # LLM never called
    assert result["conversation_label"] == "safe"
    assert result["top_evidence_messages"] == []
    assert result["severity"] is None
    assert result["gentle_alert_text"] is None


def test_score_conversation_calls_llm_above_threshold(llm_spy):
    messages = make_messages(3)
    model = FakeModel(conv_score=SKIP_LLM_BELOW * 10, per_message_scores=[0.9, 0.5, 0.1])

    result = inference.score_conversation("conv1", messages, model)

    assert len(llm_spy) == 1
    assert llm_spy[0]["user_report"] is None
    assert result["conversation_label"] == "harmful"


def test_score_conversation_always_calls_llm_when_reported_even_below_threshold(llm_spy):
    messages = make_messages(3)
    model = FakeModel(conv_score=SKIP_LLM_BELOW / 2, per_message_scores=[0.01, 0.01, 0.01])
    user_report = {"message_id": "m1", "reason": "this is a scam"}

    result = inference.score_conversation("conv1", messages, model, user_report=user_report)

    assert len(llm_spy) == 1  # the short-circuit must never apply to a report
    assert llm_spy[0]["user_report"] == user_report
    assert result["conversation_label"] == "harmful"


def test_score_conversation_reported_message_reaches_llm_even_with_lowest_score(llm_spy):
    messages = make_messages(5)
    # m4 (the one being reported) has the lowest per-message score -- exactly
    # the scenario that got it missed in the first place. rank_messages
    # includes it regardless (no filtering), so no force-include logic is
    # needed anywhere in this path anymore.
    model = FakeModel(conv_score=0.9, per_message_scores=[0.9, 0.8, 0.7, 0.6, 0.01])
    user_report = {"message_id": "m4", "reason": "this looks like grooming"}

    inference.score_conversation("conv1", messages, model, user_report=user_report)

    message_ids = {e["message_id"] for e in llm_spy[0]["messages"]}
    assert "m4" in message_ids
    assert len(message_ids) == 5  # every message reached the LLM, not a subset
