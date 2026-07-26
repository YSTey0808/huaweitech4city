import { useEffect, useState } from 'react'
import { supabase } from '../lib/supabase'

// Conversation ids that have ANY score rows — drives the conversation-list
// badge. RLS already scopes both queries to conversations I'm a member of.
// On any score INSERT we refetch: the message_scores payload lacks a
// conversation_id, so per-event resolution would need a lookup anyway.
export function useFlaggedConversations(): { flaggedIds: Set<string>; error: string | null } {
  const [flagged, setFlagged] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      const [convRes, msgRes] = await Promise.all([
        supabase.from('conversation_scores').select('conversation_id'),
        supabase.from('message_scores').select('messages!inner(conversation_id)'),
      ])
      if (cancelled) return
      if (convRes.error || msgRes.error) {
        console.warn('flagged fetch failed:', convRes.error?.message, msgRes.error?.message)
        setError("Safety alert badges couldn't be loaded.")
        return
      }
      const next = new Set<string>()
      for (const r of convRes.data) next.add(r.conversation_id)
      for (const r of msgRes.data) {
        const joined = r.messages as unknown as { conversation_id: string }
        next.add(joined.conversation_id)
      }
      setFlagged(next)
      // Realtime-triggered reloads retry naturally, so a transient failure self-heals.
      setError(null)
    }

    const channel = supabase
      .channel('flagged-conversations')
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'message_scores' }, load)
      .on(
        'postgres_changes',
        { event: 'INSERT', schema: 'public', table: 'conversation_scores' },
        load,
      )
      .subscribe()
    load()

    return () => {
      cancelled = true
      supabase.removeChannel(channel)
    }
  }, [])

  return { flaggedIds: flagged, error }
}
