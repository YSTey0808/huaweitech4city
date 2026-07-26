import { useEffect, useState } from 'react'
import { supabase } from '../lib/supabase'
import type { ConversationScore, MessageScore } from '../types/db'

export interface FlaggedMessage {
  id: string
  conversation_id: string
  content: string | null
  created_at: string
}

export interface MessageReport {
  score: MessageScore
  message: FlaggedMessage
}

export interface ConversationReport {
  score: ConversationScore
  evidence: FlaggedMessage[] // resolved rows; may be shorter than evidence_msg_ids
}

// All score rows across every conversation I'm a member of, with the flagged
// message text attached. RLS scopes both queries — no user filter needed.
// On any score INSERT/UPDATE we refetch: the message_scores payload lacks a
// conversation_id and conversation_scores need an evidence fetch anyway.
export function useReports(): {
  messageReports: MessageReport[]
  conversationReports: ConversationReport[]
  loading: boolean
  error: string | null
} {
  const [messageReports, setMessageReports] = useState<MessageReport[]>([])
  const [conversationReports, setConversationReports] = useState<ConversationReport[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      const [msgRes, convRes] = await Promise.all([
        supabase
          .from('message_scores')
          .select('*, messages!inner(id, conversation_id, content, created_at)'),
        supabase.from('conversation_scores').select('*'),
      ])
      if (cancelled) return
      if (msgRes.error || convRes.error) {
        console.warn('reports fetch failed:', msgRes.error?.message, convRes.error?.message)
        setError("Couldn't load safety reports.")
        setLoading(false)
        return
      }

      const msgReports = msgRes.data.map((row) => {
        const { messages: joined, ...score } = row as MessageScore & { messages: FlaggedMessage }
        return { score, message: joined }
      })

      const convScores = convRes.data as ConversationScore[]
      const evidenceIds = [...new Set(convScores.flatMap((s) => s.evidence_msg_ids ?? []))]
      const evidenceById = new Map<string, FlaggedMessage>()
      if (evidenceIds.length > 0) {
        const evRes = await supabase
          .from('messages')
          .select('id, conversation_id, content, created_at')
          .in('id', evidenceIds)
        if (cancelled) return
        if (evRes.error) {
          console.warn('evidence fetch failed:', evRes.error.message)
          setError("Couldn't load safety reports.")
          setLoading(false)
          return
        }
        for (const m of evRes.data as FlaggedMessage[]) evidenceById.set(m.id, m)
      }
      const convReports = convScores.map((score) => ({
        score,
        evidence: (score.evidence_msg_ids ?? []).flatMap((id) => {
          const msg = evidenceById.get(id)
          return msg ? [msg] : []
        }),
      }))

      setMessageReports(msgReports)
      setConversationReports(convReports)
      // Realtime-triggered reloads retry naturally, so a transient failure self-heals.
      setError(null)
      setLoading(false)
    }

    // Subscribe before fetching so no score lands between the initial load and
    // the live stream. Unfiltered is safe: realtime respects RLS.
    const channel = supabase
      .channel('reports')
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'message_scores' }, load)
      .on(
        'postgres_changes',
        { event: 'INSERT', schema: 'public', table: 'conversation_scores' },
        load,
      )
      .on(
        'postgres_changes',
        { event: 'UPDATE', schema: 'public', table: 'conversation_scores' },
        load,
      )
      .subscribe()
    load()

    return () => {
      cancelled = true
      supabase.removeChannel(channel)
    }
  }, [])

  return { messageReports, conversationReports, loading, error }
}
