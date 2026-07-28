"""Tests for watchlist_service.SupabaseWatchlist -- the confirmed-reports
few-shot source. Uses the shared FakeSupabase. Since migration 009/010,
"confirmed" means message_reports.status='confirmed' (the LLM agreed with
the claim); claim decides the direction: 'harmful' reports carry the typed
label from their score row, 'safe' disputes become false-positive
counterexamples labeled 'safe' (their score rows were annulled, so there is
deliberately no join for them)."""

from app.services.watchlist_service import SupabaseWatchlist


def seed(fake_supabase, *, reports=(), scores=(), messages=()):
    fake_supabase.store["message_reports"] = list(reports)
    fake_supabase.store["message_scores"] = list(scores)
    fake_supabase.store["messages"] = list(messages)


def report(msg_id, reason, created_at, status="confirmed", claim="harmful"):
    return {"msg_id": msg_id, "reason": reason, "created_at": created_at,
            "status": status, "claim": claim}


def score(msg_id, label="scam", source="user_report"):
    return {"msg_id": msg_id, "label": label, "source": source}


def message(msg_id, content):
    return {"id": msg_id, "content": content}


def test_no_reports_returns_empty(fake_supabase):
    seed(fake_supabase)
    assert SupabaseWatchlist(fake_supabase).get_confirmed_examples() == []


def test_pending_and_dismissed_reports_are_excluded(fake_supabase):
    # Only status='confirmed' (the LLM agreed) may reach other
    # conversations' prompts -- the poisoning guard.
    seed(
        fake_supabase,
        reports=[
            report("m1", "r1", "2026-07-28T10:00:00+00:00", status="pending"),
            report("m2", "r2", "2026-07-28T11:00:00+00:00", status="dismissed"),
        ],
        messages=[message("m1", "t1"), message("m2", "t2")],
    )
    assert SupabaseWatchlist(fake_supabase).get_confirmed_examples() == []


def test_confirmed_harmful_report_uses_score_row_label(fake_supabase):
    seed(
        fake_supabase,
        reports=[report("m1", "urgent transfer demand", "2026-07-28T10:00:00+00:00")],
        scores=[score("m1", label="scam")],
        messages=[message("m1", "transfer $5000 in 10 minutes or account locked")],
    )
    out = SupabaseWatchlist(fake_supabase).get_confirmed_examples()
    assert out == [{
        "text": "transfer $5000 in 10 minutes or account locked",
        "reason": "urgent transfer demand",
        "label": "scam",
    }]


def test_confirmed_harmful_report_with_missing_score_row_falls_back_to_harmful(fake_supabase):
    seed(
        fake_supabase,
        reports=[report("m1", "r1", "2026-07-28T10:00:00+00:00")],
        scores=[],  # score rows gone (edge case) -- label falls back
        messages=[message("m1", "t1")],
    )
    out = SupabaseWatchlist(fake_supabase).get_confirmed_examples()
    assert out[0]["label"] == "harmful"


def test_confirmed_safe_dispute_becomes_safe_example_without_score_join(fake_supabase):
    # A confirmed dispute's score rows were annulled -- 'safe' comes from
    # the claim itself, no join involved.
    seed(
        fake_supabase,
        reports=[report("m1", "just my aunt asking about dinner", "2026-07-28T10:00:00+00:00",
                        claim="safe")],
        scores=[],
        messages=[message("m1", "eh you free tonight or not")],
    )
    out = SupabaseWatchlist(fake_supabase).get_confirmed_examples()
    assert out == [{
        "text": "eh you free tonight or not",
        "reason": "just my aunt asking about dinner",
        "label": "safe",
    }]


def test_newest_confirmed_first_and_limit_respected(fake_supabase):
    seed(
        fake_supabase,
        reports=[
            report("m1", "r1", "2026-07-28T10:00:00+00:00"),
            report("m2", "r2", "2026-07-28T11:00:00+00:00", claim="safe"),
            report("m3", "r3", "2026-07-28T12:00:00+00:00"),
        ],
        scores=[score("m1"), score("m3")],
        messages=[message("m1", "t1"), message("m2", "t2"), message("m3", "t3")],
    )
    out = SupabaseWatchlist(fake_supabase).get_confirmed_examples(limit=2)
    assert [e["text"] for e in out] == ["t3", "t2"]  # newest first, capped at 2
    assert [e["label"] for e in out] == ["scam", "safe"]  # mixed directions coexist


def test_duplicate_reports_on_same_message_deduped_to_most_recent(fake_supabase):
    seed(
        fake_supabase,
        reports=[
            report("m1", "older reason", "2026-07-28T10:00:00+00:00"),
            report("m1", "newer reason", "2026-07-28T11:00:00+00:00"),
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
        reports=[report("m1", "r1", "2026-07-28T10:00:00+00:00")],
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
