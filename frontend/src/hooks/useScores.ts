import { useEffect, useMemo, useState } from 'react'
import { supabase } from '../lib/supabase'
import type { ConversationScore, MessageScore } from '../types/db'

export interface ConversationScores {
  messageScores: Map<string, MessageScore[]> // keyed by msg_id
  conversationScores: ConversationScore[]
  evidenceIds: Set<string> // union of evidence_msg_ids across conversation scores
  loading: boolean
  error: string | null
}

// Live harm-score state for one conversation. Same subscribe-before-fetch
// pattern as useMessages; overlap between the initial fetch and the realtime
// stream is deduped by score row id.
export function useScores(conversationId: string | undefined): ConversationScores {
  const [messageScores, setMessageScores] = useState<Map<string, MessageScore[]>>(new Map())
  const [conversationScores, setConversationScores] = useState<ConversationScore[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!conversationId) return
    let cancelled = false
    setMessageScores(new Map())
    setConversationScores([])
    setLoading(true)
    setError(null)

    const addMessageScore = (score: MessageScore) => {
      setMessageScores((prev) => {
        const bucket = prev.get(score.msg_id) ?? []
        if (bucket.some((s) => s.id === score.id)) return prev
        const next = new Map(prev)
        next.set(score.msg_id, [...bucket, score])
        return next
      })
    }

    const upsertConversationScore = (score: ConversationScore) => {
      setConversationScores((prev) =>
        prev.some((s) => s.id === score.id)
          ? prev.map((s) => (s.id === score.id ? score : s))
          : [...prev, score],
      )
    }

    // message_scores has no conversation_id column, so its INSERT stream cannot
    // be filtered server-side. Unfiltered is safe: realtime respects RLS (we only
    // receive rows for our own conversations), and rows for other conversations
    // are inert because the UI looks scores up by the loaded messages' ids.
    const channel = supabase
      .channel(`scores:${conversationId}`)
      .on(
        'postgres_changes',
        { event: 'INSERT', schema: 'public', table: 'message_scores' },
        (payload) => {
          if (!cancelled) addMessageScore(payload.new as MessageScore)
        },
      )
      .on(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'conversation_scores',
          filter: `conversation_id=eq.${conversationId}`,
        },
        (payload) => {
          if (!cancelled) upsertConversationScore(payload.new as ConversationScore)
        },
      )
      .on(
        'postgres_changes',
        {
          event: 'UPDATE',
          schema: 'public',
          table: 'conversation_scores',
          filter: `conversation_id=eq.${conversationId}`,
        },
        (payload) => {
          if (!cancelled) upsertConversationScore(payload.new as ConversationScore)
        },
      )
      .subscribe()

    async function loadScores() {
      // Initial message_scores fetch filtered through the messages FK join.
      const [msgRes, convRes] = await Promise.all([
        supabase
          .from('message_scores')
          .select('*, messages!inner(conversation_id)')
          .eq('messages.conversation_id', conversationId),
        supabase.from('conversation_scores').select('*').eq('conversation_id', conversationId),
      ])
      if (cancelled) return
      if (msgRes.error || convRes.error) {
        console.warn('score fetch failed:', msgRes.error?.message, convRes.error?.message)
        setError("Couldn't load safety alerts for this chat.")
      } else {
        for (const row of msgRes.data) {
          const { messages: _joined, ...score } = row as MessageScore & { messages: unknown }
          addMessageScore(score)
        }
        for (const row of convRes.data) upsertConversationScore(row as ConversationScore)
      }
      setLoading(false)
    }
    loadScores()

    return () => {
      cancelled = true
      supabase.removeChannel(channel)
    }
  }, [conversationId])

  const evidenceIds = useMemo(() => {
    const ids = new Set<string>()
    for (const s of conversationScores) for (const id of s.evidence_msg_ids ?? []) ids.add(id)
    return ids
  }, [conversationScores])

  return { messageScores, conversationScores, evidenceIds, loading, error }
}
