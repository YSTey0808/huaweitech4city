from app.services.scoring_service import fetch_message_window, write_scores


def make_messages(n: int, conv: str = "c1"):
    return [
        {
            "id": f"{conv}-{i}", "conversation_id": conv, "sender_id": "u1",
            "content": f"t{i}", "reply_to": None,
            "created_at": f"2026-07-22T00:00:{i:02d}+00:00",
        }
        for i in range(n)
    ]


# ---- fetch_message_window ----

def test_fetch_message_window_default_last_n(fake_supabase):
    fake_supabase.store["messages"] = make_messages(15)
    out = fetch_message_window(fake_supabase, "c1")
    assert [m["message_id"] for m in out] == [f"c1-{i}" for i in range(5, 15)]


def test_fetch_message_window_anchored_ends_at_target(fake_supabase):
    fake_supabase.store["messages"] = make_messages(15)
    out = fetch_message_window(fake_supabase, "c1", up_to_message_id="c1-7")
    assert [m["message_id"] for m in out] == [f"c1-{i}" for i in range(8)]
    assert out[-1]["message_id"] == "c1-7"


def test_fetch_message_window_unknown_anchor_returns_empty(fake_supabase):
    fake_supabase.store["messages"] = make_messages(5)
    assert fetch_message_window(fake_supabase, "c1", up_to_message_id="nope") == []


def test_fetch_message_window_anchor_from_other_conversation_returns_empty(fake_supabase):
    fake_supabase.store["messages"] = make_messages(5, conv="c1") + make_messages(3, conv="c2")
    # c2-1 exists, but not in c1 -- must not silently score the wrong conversation.
    assert fetch_message_window(fake_supabase, "c1", up_to_message_id="c2-1") == []


# ---- write_scores ----

def _harmful_result(msg_id="m1", confidence=0.9, severity="high", reasoning="alert"):
    return {
        "conversation_label": "harmful",
        "conversation_confidence": confidence,
        "severity": severity,
        "gentle_alert_text": reasoning,
        "top_evidence_messages": [{"message_id": msg_id, "score": 0.8}],
    }


def _safe_result():
    return {"conversation_label": "safe", "conversation_confidence": 0.99}


def test_write_scores_safe_writes_nothing(fake_supabase):
    out = write_scores(fake_supabase, "c1", _safe_result())
    assert out == {"conversation_scores": "safe", "message_scores_inserted": 0}
    assert fake_supabase.store.get("conversation_scores", []) == []
    assert fake_supabase.store.get("message_scores", []) == []


def test_write_scores_inserts_with_source(fake_supabase):
    out = write_scores(fake_supabase, "c1", _harmful_result(), source="model")
    assert out["conversation_scores"] == "inserted"
    row = fake_supabase.store["conversation_scores"][0]
    assert row["label"] == "harmful"
    assert row["source"] == "model"
    assert fake_supabase.store["message_scores"][0]["source"] == "model"


def test_write_scores_updates_existing_row_in_place(fake_supabase):
    write_scores(fake_supabase, "c1", _harmful_result(confidence=0.5), source="model")
    out = write_scores(fake_supabase, "c1", _harmful_result(confidence=0.9), source="model")
    assert out["conversation_scores"] == "updated"
    assert len(fake_supabase.store["conversation_scores"]) == 1
    assert fake_supabase.store["conversation_scores"][0]["confidence"] == 0.9


def test_write_scores_source_sticky_user_report_survives_later_automatic_update(fake_supabase):
    # Report confirms the conversation first.
    write_scores(fake_supabase, "c1", _harmful_result(msg_id="m5"), source="user_report")
    # A later, unrelated automatic pass independently agrees it's harmful too.
    write_scores(fake_supabase, "c1", _harmful_result(msg_id="m9"), source="model")

    row = fake_supabase.store["conversation_scores"][0]
    assert row["source"] == "user_report"  # must not be downgraded back to 'model'
    assert row["confidence"] == 0.9  # other fields still update normally


def test_write_scores_model_to_model_stays_model(fake_supabase):
    write_scores(fake_supabase, "c1", _harmful_result(), source="model")
    write_scores(fake_supabase, "c1", _harmful_result(), source="model")
    assert fake_supabase.store["conversation_scores"][0]["source"] == "model"


def test_write_scores_message_scores_dedup_same_label(fake_supabase):
    write_scores(fake_supabase, "c1", _harmful_result(msg_id="m1"), source="model")
    out = write_scores(fake_supabase, "c1", _harmful_result(msg_id="m1"), source="model")
    assert out["message_scores_inserted"] == 0
    assert len(fake_supabase.store["message_scores"]) == 1
