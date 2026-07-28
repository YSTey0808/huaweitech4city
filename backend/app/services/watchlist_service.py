"""
Watchlist: past user reports that scoring subsequently CONFIRMED harmful,
served as few-shot reference patterns to every scoring call (automatic and
report-triggered alike). This is the generalizing half of the human-feedback
loop before any retrain: a pattern reported once in one conversation can
inform the LLM's judgment on every other conversation immediately, while the
GNN's weights only catch up at the next retrain.

Both report directions feed it (see migration 010): a confirmed
claim='harmful' report becomes a harmful reference pattern (label from its
score row, e.g. 'scam'), and a confirmed claim='safe' dispute becomes a
false-positive counterexample (label 'safe') that nudges the LLM away from
re-flagging similar ordinary messages.

"Confirmed" is deliberately stricter than "reported": only reports whose
status is 'confirmed' (stamped by report_service after the LLM reviewed the
report and agreed -- migration 009) enter the watchlist. Unreviewed or
dismissed reports never reach other conversations' prompts, which is what
keeps a spam/bogus report from poisoning global scoring. Status is the
authority here rather than a join against score rows, because a confirmed
dispute ANNULS its score rows (report_service) -- there is nothing left to
join against in that direction.

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
            .select("msg_id, reason, claim, created_at")
            .eq("status", "confirmed")
            .order("created_at", desc=True)
            .limit(_REPORT_FETCH_BOUND)
            .execute()
        )
        if not reports_res.data:
            return []

        # Multiple members may report the same message (unique per reporter,
        # not per message) -- keep the most recent confirmed report per msg_id.
        report_by_id = {}
        ordered_ids = []
        for r in reports_res.data:  # newest first per the order() above
            if r["msg_id"] not in report_by_id:
                report_by_id[r["msg_id"]] = r
                ordered_ids.append(r["msg_id"])
        ordered_ids = ordered_ids[:limit]

        # Harmful-claim confirmations still have score rows (the annulment
        # only happens for confirmed disputes) -- use them for the typed
        # label ('scam'/...). Confirmed disputes are labeled 'safe' directly.
        harmful_ids = [mid for mid in ordered_ids if report_by_id[mid]["claim"] != "safe"]
        label_by_id = {}
        if harmful_ids:
            scores_res = (
                self._supabase.table("message_scores")
                .select("msg_id, label")
                .in_("msg_id", harmful_ids)
                .eq("source", "user_report")
                .execute()
            )
            label_by_id = {row["msg_id"]: row["label"] for row in scores_res.data}

        messages_res = (
            self._supabase.table("messages")
            .select("id, content")
            .in_("id", ordered_ids)
            .execute()
        )
        text_by_id = {m["id"]: m["content"] for m in messages_res.data}

        examples = []
        for mid in ordered_ids:
            if mid not in text_by_id:
                continue  # message deleted since -> skip
            r = report_by_id[mid]
            if r["claim"] == "safe":
                label = "safe"
            else:
                # 'harmful' fallback covers a confirmed report whose score
                # rows were since removed (e.g. later annulled by a dispute).
                label = label_by_id.get(mid, "harmful")
            examples.append({"text": text_by_id[mid] or "", "reason": r["reason"], "label": label})
        return examples
