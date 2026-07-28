import { useCallback, useEffect, useState } from 'react'
import { supabase } from '../lib/supabase'
import { useAuth } from '../context/AuthContext'

// Fire-and-forget re-scoring trigger, same shape as useMessages.ts's
// requestScoring — must never block or fail the "reported" UX.
function requestReportRescoring(conversationId: string, msgId: string, reason: string) {
  void supabase.functions
    .invoke('report-message', { body: { conversation_id: conversationId, msg_id: msgId, reason } })
    .then(({ error }) => {
      if (error) console.warn('report-message failed:', error.message)
    })
    .catch((e) => console.warn('report-message failed:', e))
}

// Lets a user flag a message the model missed. Tracks which messages the
// current user has already reported in this conversation -- backed by the
// database (not just local state), so the "already reported" state survives
// a refresh instead of resetting every session.
export function useMessageReport(conversationId: string | undefined) {
  const { user } = useAuth()
  const [reportedIds, setReportedIds] = useState<Set<string>>(new Set())

  useEffect(() => {
    if (!conversationId) return
    let cancelled = false
    setReportedIds(new Set())

    // RLS already restricts this to the current user's own reports (see
    // migration 008), so no reporter_id filter is needed client-side.
    supabase
      .from('message_reports')
      .select('msg_id')
      .eq('conversation_id', conversationId)
      .then(({ data, error }) => {
        if (cancelled) return
        if (error) {
          console.warn('loading prior reports failed:', error.message)
          return
        }
        setReportedIds(new Set(data.map((r) => r.msg_id as string)))
      })

    return () => {
      cancelled = true
    }
  }, [conversationId])

  const report = useCallback(
    async (msgId: string, reason: string): Promise<boolean> => {
      if (!conversationId || !user) return false
      const trimmed = reason.trim()
      if (!trimmed) return false

      const { error: insertErr } = await supabase
        .from('message_reports')
        .insert({ msg_id: msgId, conversation_id: conversationId, reporter_id: user.id, reason: trimmed })

      // 23505 = already reported this message (unique(msg_id, reporter_id))
      // -- treat as success, matching useMessages.ts's insert-retry handling.
      if (insertErr && insertErr.code !== '23505') {
        console.warn('report insert failed:', insertErr.message)
        return false
      }

      setReportedIds((prev) => new Set(prev).add(msgId))
      requestReportRescoring(conversationId, msgId, trimmed)
      return true
    },
    [conversationId, user],
  )

  return { reportedIds, report }
}
