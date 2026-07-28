"""
Watchlist: past user reports that scoring subsequently CONFIRMED harmful,
served as few-shot reference patterns to every scoring call (automatic and
report-triggered alike). This is the generalizing half of the human-feedback
loop before any retrain: a pattern reported once in one conversation can
inform the LLM's judgment on every other conversation immediately, while the
GNN's weights only catch up at the next retrain.

"Confirmed" is deliberately stricter than "reported": a report only enters
the watchlist once a message_scores row with source='user_report' exists for
its msg_id -- i.e. the LLM reviewed the report and agreed (see
report_service.py / scoring_service.write_scores). Unreviewed reports never
reach other conversations' prompts, which is what keeps a spam/bogus report
from poisoning global scoring.

Mirrors embedding_store.py's Protocol pattern: WatchlistProvider is the
interface callers depend on, SupabaseWatchlist is today's implementation
(plain queries -- at current data volume a full fetch beats any index), and
a future similarity-based implementation (e.g. pgvector kNN over reported-
message embeddings, returning only examples relevant to the window being
scored) can swap in behind the same method without touching callers.

Privacy note: confirmed example text crosses conversation boundaries --
server-side only, into LLM prompts, never into any user-facing response.
The examples are messages whose own conversation members reported them, but
worth remembering if retention policies tighten later.
"""

from typing import Protocol

WATCHLIST_LIMIT = 20        # max confirmed examples per prompt -- bounds prompt growth
_REPORT_FETCH_BOUND = 200   # how many recent reports to consider before confirmation filtering


class WatchlistProvider(Protocol):
    def get_confirmed_examples(self, limit: int = WATCHLIST_LIMIT) -> list:
        """Returns up to `limit` dicts {text, reason, label} -- newest
        confirmed reports first -- for the LLM prompt's reference-pattern
        section. Must never raise: scoring proceeds without examples on
        any failure."""
        ...


class SupabaseWatchlist:
    def __init__(self, supabase):
        self._supabase = supabase

    def get_confirmed_examples(self, limit: int = WATCHLIST_LIMIT) -> list:
        try:
            return self._fetch(limit)
        except Exception as e:  # a watchlist failure must never fail scoring itself
            print(f"watchlist fetch failed (scoring proceeds without examples): {e}")
            return []

    def _fetch(self, limit: int) -> list:
        reports_res = (
            self._supabase.table("message_reports")
            .select("msg_id, reason, created_at")
            .order("created_at", desc=True)
            .limit(_REPORT_FETCH_BOUND)
            .execute()
        )
        if not reports_res.data:
            return []

        # Multiple members may report the same message (unique per reporter,
        # not per message) -- keep the most recent reason per msg_id.
        reason_by_id = {}
        ordered_ids = []
        for r in reports_res.data:  # newest first per the order() above
            if r["msg_id"] not in reason_by_id:
                reason_by_id[r["msg_id"]] = r["reason"]
                ordered_ids.append(r["msg_id"])

        # Confirmation filter: only reports whose message ended up with a
        # source='user_report' score row (the LLM agreed) qualify.
        confirmed_res = (
            self._supabase.table("message_scores")
            .select("msg_id, label")
            .in_("msg_id", ordered_ids)
            .eq("source", "user_report")
            .execute()
        )
        label_by_id = {row["msg_id"]: row["label"] for row in confirmed_res.data}

        confirmed_ids = [mid for mid in ordered_ids if mid in label_by_id][:limit]
        if not confirmed_ids:
            return []

        messages_res = (
            self._supabase.table("messages")
            .select("id, content")
            .in_("id", confirmed_ids)
            .execute()
        )
        text_by_id = {m["id"]: m["content"] for m in messages_res.data}

        return [
            {"text": text_by_id[mid] or "", "reason": reason_by_id[mid], "label": label_by_id[mid]}
            for mid in confirmed_ids
            if mid in text_by_id  # message deleted since -> skip
        ]
