"""The Supabase row -> pipeline message translation, with particular attention
to reply_to.

reply_to was a dead column until the chat UI started writing it: every
production row was null, so the GNN's `reply_to` edge relation received an
empty edge index on every inference. These tests pin the one hop that carries
the value across the naming boundary (`reply_to` in the DB and frontend,
`reply_to_message_id` everywhere in pipeline/), because a silent rename here
would not fail anything loudly -- it would just quietly switch the relation
back off.
"""

from datetime import datetime, timezone

from app.services.message_mapper import supabase_row_to_pipeline_message


def _row(**overrides):
    row = {
        "id": "m2",
        "sender_id": "u1",
        "content": "ya can, what time?",
        "reply_to": "m1",
        "created_at": "2026-07-22T00:00:05+00:00",
    }
    row.update(overrides)
    return row


def test_maps_reply_to_to_reply_to_message_id():
    out = supabase_row_to_pipeline_message(_row())
    assert out["reply_to_message_id"] == "m1"


def test_reply_to_null_stays_none():
    out = supabase_row_to_pipeline_message(_row(reply_to=None))
    assert out["reply_to_message_id"] is None


def test_reply_to_absent_is_none_not_keyerror():
    # fetch_message_window selects the column explicitly, but the public API
    # path builds rows from partner payloads -- an absent key must not raise.
    row = _row()
    del row["reply_to"]
    assert supabase_row_to_pipeline_message(row)["reply_to_message_id"] is None


def test_maps_remaining_fields():
    out = supabase_row_to_pipeline_message(_row())
    assert out["message_id"] == "m2"
    assert out["sender_id"] == "u1"
    assert out["text"] == "ya can, what time?"


def test_content_null_becomes_empty_string():
    # content is nullable in the schema; the pipeline expects a str to embed.
    assert supabase_row_to_pipeline_message(_row(content=None))["text"] == ""


def test_created_at_becomes_epoch_seconds():
    # Built from components rather than hardcoded, so this checks the ISO
    # parse rather than restating it.
    expected = datetime(2026, 7, 22, tzinfo=timezone.utc).timestamp()
    out = supabase_row_to_pipeline_message(_row(created_at="2026-07-22T00:00:00+00:00"))
    assert out["timestamp"] == expected


def test_created_at_z_suffix_parses():
    # Postgres/PostgREST can hand back a trailing Z; fromisoformat rejects it
    # on older Pythons, hence the replace() in the mapper.
    expected = datetime(2026, 7, 22, tzinfo=timezone.utc).timestamp()
    assert supabase_row_to_pipeline_message(_row(created_at="2026-07-22T00:00:00Z"))["timestamp"] == expected
