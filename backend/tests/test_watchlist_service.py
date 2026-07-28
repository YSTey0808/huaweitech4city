"""Tests for watchlist_service.SupabaseWatchlist -- the confirmed-reports
few-shot source. Uses the shared FakeSupabase; "confirmed" means a
message_scores row with source='user_report' exists for the reported msg_id."""

from app.services.watchlist_service import SupabaseWatchlist


def seed(fake_supabase, *, reports=(), scores=(), messages=()):
    fake_supabase.store["message_reports"] = list(reports)
    fake_supabase.store["message_scores"] = list(scores)
    fake_supabase.store["messages"] = list(messages)


def report(msg_id, reason, created_at):
    return {"msg_id": msg_id, "reason": reason, "created_at": created_at}


def score(msg_id, label="scam", source="user_report"):
    return {"msg_id": msg_id, "label": label, "source": source}


def message(msg_id, content):
    return {"id": msg_id, "content": content}


def test_no_reports_returns_empty(fake_supabase):
    seed(fake_supabase)
    assert SupabaseWatchlist(fake_supabase).get_confirmed_examples() == []


def test_unconfirmed_reports_are_excluded(fake_supabase):
    # Reported, but no source='user_report' score row -> the LLM never
    # agreed -> must not reach other conversations' prompts.
    seed(
        fake_supabase,
        reports=[report("m1", "looks like a scam", "2026-07-27T10:00:00+00:00")],
        messages=[message("m1", "send money now")],
    )
    assert SupabaseWatchlist(fake_supabase).get_confirmed_examples() == []


def test_model_sourced_scores_do_not_confirm(fake_supabase):
    # A score row that exists but with source='model' is an automatic
    # finding, not a confirmation of this report.
    seed(
        fake_supabase,
        reports=[report("m1", "looks like a scam", "2026-07-27T10:00:00+00:00")],
        scores=[score("m1", source="model")],
        messages=[message("m1", "send money now")],
    )
    assert SupabaseWatchlist(fake_supabase).get_confirmed_examples() == []


def test_confirmed_report_returned_with_text_reason_label(fake_supabase):
    seed(
        fake_supabase,
        reports=[report("m1", "urgent transfer demand", "2026-07-27T10:00:00+00:00")],
        scores=[score("m1", label="scam")],
        messages=[message("m1", "transfer $5000 in 10 minutes or account locked")],
    )
    out = SupabaseWatchlist(fake_supabase).get_confirmed_examples()
    assert out == [{
        "text": "transfer $5000 in 10 minutes or account locked",
        "reason": "urgent transfer demand",
        "label": "scam",
    }]


def test_newest_confirmed_first_and_limit_respected(fake_supabase):
    seed(
        fake_supabase,
        reports=[
            report("m1", "r1", "2026-07-27T10:00:00+00:00"),
            report("m2", "r2", "2026-07-27T11:00:00+00:00"),
            report("m3", "r3", "2026-07-27T12:00:00+00:00"),
        ],
        scores=[score("m1"), score("m2"), score("m3")],
        messages=[message("m1", "t1"), message("m2", "t2"), message("m3", "t3")],
    )
    out = SupabaseWatchlist(fake_supabase).get_confirmed_examples(limit=2)
    assert [e["text"] for e in out] == ["t3", "t2"]  # newest first, capped at 2


def test_duplicate_reports_on_same_message_deduped_to_most_recent_reason(fake_supabase):
    seed(
        fake_supabase,
        reports=[
            report("m1", "older reason", "2026-07-27T10:00:00+00:00"),
            report("m1", "newer reason", "2026-07-27T11:00:00+00:00"),
        ],
        scores=[score("m1")],
        messages=[message("m1", "t1")],
    )
    out = SupabaseWatchlist(fake_supabase).get_confirmed_examples()
    assert len(out) == 1
    assert out[0]["reason"] == "newer reason"


def test_deleted_message_is_skipped(fake_supabase):
    seed(
        fake_supabase,
        reports=[report("m1", "r1", "2026-07-27T10:00:00+00:00")],
        scores=[score("m1")],
        messages=[],  # message row gone (deleted since the report)
    )
    assert SupabaseWatchlist(fake_supabase).get_confirmed_examples() == []


def test_fetch_failure_returns_empty_never_raises():
    class ExplodingSupabase:
        def table(self, name):
            raise RuntimeError("connection reset")

    out = SupabaseWatchlist(ExplodingSupabase()).get_confirmed_examples()
    assert out == []
