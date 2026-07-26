import { useCallback, useEffect, useState } from 'react'
import { supabase } from '../lib/supabase'
import { useAuth } from '../context/AuthContext'
import type { Message } from '../types/db'

export type ChatMessage = Message & { status: 'sending' | 'sent' | 'failed' }

const HISTORY_LIMIT = 50 // prototype: last 50 messages, no pagination

// Fire-and-forget mock harm scoring — must never block or fail the send UX.
// (functions.invoke resolves with { error } on non-2xx; .catch covers network faults.)
function requestScoring(conversationId: string) {
  void supabase.functions
    .invoke('score-message', { body: { conversation_id: conversationId } })
    .then(({ error }) => {
      if (error) console.warn('score-message failed:', error.message)
    })
    .catch((e) => console.warn('score-message failed:', e))
}

// Live message state for one conversation: initial history, realtime INSERTs,
// and optimistic sends. The client generates the row id (RLS allows it), so
// the optimistic row, the insert response, and the realtime echo all share
// one id and converge through a single idempotent upsert — no temp-id
// reconciliation, and duplicates are impossible.
export function useMessages(conversationId: string | undefined) {
  const { user } = useAuth()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const upsert = useCallback((msg: ChatMessage) => {
    setMessages((prev) => {
      const existing = prev.find((m) => m.id === msg.id)
      // A server-confirmed row never regresses to 'sending'.
      if (existing && existing.status === 'sent' && msg.status === 'sending') return prev
      const next = existing ? prev.map((m) => (m.id === msg.id ? msg : m)) : [...prev, msg]
      return next.sort((a, b) => a.created_at.localeCompare(b.created_at))
    })
  }, [])

  useEffect(() => {
    if (!conversationId) return
    let cancelled = false
    setMessages([])
    setLoading(true)
    setError(null)

    // Subscribe BEFORE fetching so no message can fall between history and
    // the live stream; the overlap is deduped by upsert.
    const channel = supabase
      .channel(`messages:${conversationId}`)
      .on(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'messages',
          filter: `conversation_id=eq.${conversationId}`,
        },
        (payload) => {
          if (!cancelled) upsert({ ...(payload.new as Message), status: 'sent' })
        },
      )
      .subscribe()

    async function loadHistory() {
      const { data, error: fetchErr } = await supabase
        .from('messages')
        .select('*')
        .eq('conversation_id', conversationId)
        .order('created_at', { ascending: false })
        .limit(HISTORY_LIMIT)
      if (cancelled) return
      if (fetchErr) setError(fetchErr.message)
      else for (const m of data as Message[]) upsert({ ...m, status: 'sent' })
      setLoading(false)
    }
    loadHistory()

    return () => {
      cancelled = true
      supabase.removeChannel(channel)
    }
  }, [conversationId, upsert])

  const insertMessage = useCallback(
    async (msg: ChatMessage) => {
      upsert(msg)
      const { data, error: insertErr } = await supabase
        .from('messages')
        .insert({
          id: msg.id,
          conversation_id: msg.conversation_id,
          sender_id: msg.sender_id,
          content: msg.content,
        })
        .select()
        .single()
      if (insertErr) {
        // 23505 = the row already landed (e.g. retry after a timed-out
        // insert that actually succeeded) — that is a success.
        if (insertErr.code === '23505') {
          upsert({ ...msg, status: 'sent' })
          requestScoring(msg.conversation_id)
        } else {
          upsert({ ...msg, status: 'failed' })
        }
      } else {
        upsert({ ...(data as Message), status: 'sent' })
        requestScoring(msg.conversation_id)
      }
    },
    [upsert],
  )

  const send = useCallback(
    (content: string) => {
      if (!conversationId || !user) return
      const trimmed = content.trim()
      if (!trimmed) return
      insertMessage({
        id: crypto.randomUUID(),
        conversation_id: conversationId,
        sender_id: user.id,
        content: trimmed,
        msg_type: 'text',
        reply_to: null,
        created_at: new Date().toISOString(), // corrected by the server row
        status: 'sending',
      })
    },
    [conversationId, user, insertMessage],
  )

  const retry = useCallback(
    (id: string) => {
      const failed = messages.find((m) => m.id === id && m.status === 'failed')
      if (failed) insertMessage({ ...failed, status: 'sending' })
    },
    [messages, insertMessage],
  )

  return { messages, loading, error, send, retry }
}
