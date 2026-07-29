import { useCallback, useEffect, useState } from 'react'
import { supabase } from '../lib/supabase'
import { useAuth } from '../context/AuthContext'
import type { MessageReport } from '../types/db'

export type ReportClaim = 'harmful' | 'safe'

export interface ReportOutcome {
  status: string // 'pending' | 'confirmed' | 'dismissed' (open-ended, see types/db.ts)
  claim: string // 'harmful' (model missed this) | 'safe' (false-positive dispute)
  outcomeReasoning: string | null
  escalatedAt: string | null // set once the reporter escalates a dismissal (migration 011)
}

// Fire-and-forget re-scoring trigger, same shape as useMessages.ts's
// requestScoring — must never block or fail the "reported" UX.
function requestReportRescoring(conversationId: string, msgId: string, reason: string, claim: ReportClaim) {
  void supabase.functions
    .invoke('report-message', {
      body: { conversation_id: conversationId, msg_id: msgId, reason, claim },
    })
    .then(({ error }) => {
      if (error) console.warn('report-message failed:', error.message)
    })
    .catch((e) => console.warn('report-message failed:', e))
}

// Lets a user flag a message the model missed, and tracks each report's
// outcome (pending -> confirmed/dismissed, stamped by the backend after the
// LLM reviews it -- see migration 009). State is DB-backed and streamed:
// the initial fetch survives a refresh, and the Realtime subscription
// delivers the verdict live a few seconds after submitting. Unlike
// message_scores, message_reports has a conversation_id column, so the
// subscription is server-side filtered (no unfiltered-stream workaround
// needed); RLS additionally scopes rows to the reporter's own.
export function useMessageReport(conversationId: string | undefined) {
  const { user } = useAuth()
  const [reports, setReports] = useState<Map<string, ReportOutcome>>(new Map())

  const upsertOutcome = useCallback((msgId: string, outcome: ReportOutcome) => {
    setReports((prev) => {
      // A resolved outcome never regresses to 'pending' (same idea as
      // useMessages' sent-never-regresses-to-sending guard): the initial
      // fetch can resolve AFTER a fresher Realtime UPDATE already landed,
      // and the optimistic 'pending' from report() must not clobber an
      // already-known verdict either.
      const existing = prev.get(msgId)
      if (existing && existing.status !== 'pending' && outcome.status === 'pending') return prev
      // Escalation only ever goes null -> set and is never reset (RPC guard,
      // migration 011), so a known escalatedAt is preserved against any
      // stale row that predates it (e.g. a late echo of the pre-escalation
      // outcome, or the optimistic escalate racing the Realtime confirm).
      const escalatedAt = outcome.escalatedAt ?? existing?.escalatedAt ?? null
      return new Map(prev).set(msgId, { ...outcome, escalatedAt })
    })
  }, [])

  useEffect(() => {
    if (!conversationId) return
    let cancelled = false
    setReports(new Map())

    const applyRow = (row: MessageReport) => {
      if (!cancelled) {
        upsertOutcome(row.msg_id, {
          status: row.status,
          claim: row.claim,
          outcomeReasoning: row.outcome_reasoning,
          escalatedAt: row.escalated_at,
        })
      }
    }

    // Subscribe before fetching (same ordering as useMessages/useScores) so
    // an outcome landing mid-load can't fall between fetch and stream.
    const channel = supabase
      .channel(`reports:${conversationId}`)
      .on(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'message_reports',
          filter: `conversation_id=eq.${conversationId}`,
        },
        (payload) => applyRow(payload.new as MessageReport),
      )
      .on(
        'postgres_changes',
        {
          event: 'UPDATE',
          schema: 'public',
          table: 'message_reports',
          filter: `conversation_id=eq.${conversationId}`,
        },
        (payload) => applyRow(payload.new as MessageReport),
      )
      .subscribe()

    supabase
      .from('message_reports')
      .select('msg_id, status, claim, outcome_reasoning, escalated_at')
      .eq('conversation_id', conversationId)
      .then(({ data, error }) => {
        if (cancelled) return
        if (error) {
          console.warn('loading prior reports failed:', error.message)
          return
        }
        for (const row of data) {
          upsertOutcome(row.msg_id as string, {
            status: row.status as string,
            claim: row.claim as string,
            outcomeReasoning: row.outcome_reasoning as string | null,
            escalatedAt: row.escalated_at as string | null,
          })
        }
      })

    return () => {
      cancelled = true
      supabase.removeChannel(channel)
    }
  }, [conversationId, upsertOutcome])

  const report = useCallback(
    async (msgId: string, reason: string, claim: ReportClaim = 'harmful'): Promise<boolean> => {
      if (!conversationId || !user) return false
      const trimmed = reason.trim()
      if (!trimmed) return false

      const { error: insertErr } = await supabase
        .from('message_reports')
        .insert({
          msg_id: msgId,
          conversation_id: conversationId,
          reporter_id: user.id,
          reason: trimmed,
          claim,
        })

      // 23505 = already reported this message (unique(msg_id, reporter_id))
      // -- treat as success, matching useMessages.ts's insert-retry handling.
      if (insertErr && insertErr.code !== '23505') {
        console.warn('report insert failed:', insertErr.message)
        return false
      }

      // Optimistic 'pending'; the Realtime echo (and later the backend's
      // outcome UPDATE) converge through the same upsert.
      upsertOutcome(msgId, { status: 'pending', claim, outcomeReasoning: null, escalatedAt: null })
      requestReportRescoring(conversationId, msgId, trimmed, claim)
      return true
    },
    [conversationId, user, upsertOutcome],
  )

  // Escalate a dismissed report for human review. The RPC (migration 011)
  // is the single authoritative write -- it pins the change to escalated_at
  // and enforces the guards (own row, dismissed, not already escalated)
  // server-side, so the client only reflects the result optimistically.
  const escalate = useCallback(
    async (msgId: string): Promise<boolean> => {
      if (!conversationId) return false
      const { error } = await supabase.rpc('escalate_report', {
        _msg_id: msgId,
        _conversation_id: conversationId,
      })
      if (error) {
        console.warn('escalate failed:', error.message)
        return false
      }
      // Optimistically stamp escalatedAt on the existing outcome; the
      // Realtime UPDATE echo brings the authoritative timestamp, preserved
      // by upsertOutcome's null->set monotonicity.
      setReports((prev) => {
        const existing = prev.get(msgId)
        if (!existing || existing.escalatedAt) return prev
        return new Map(prev).set(msgId, { ...existing, escalatedAt: new Date().toISOString() })
      })
      return true
    },
    [conversationId],
  )

  return { reports, report, escalate }
}
