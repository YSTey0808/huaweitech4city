import { useEffect, useState } from 'react'
import { supabase } from '../lib/supabase'
import { useAuth } from '../context/AuthContext'
import type { Message, Profile } from '../types/db'

export interface ConversationListItem {
  conversationId: string
  friend: Profile
  lastMessageAt: string | null // null = conversation has no messages yet
  lastSenderId: string | null
  lastReadAt: string
}

// Shape returned by the get_dm_overview() RPC (migration 006).
interface OverviewRow {
  conversation_id: string
  other_user_id: string
  last_message_at: string | null
  last_sender_id: string | null
  last_read_at: string
}

// Recent activity first; conversations without messages go last (the list
// hides them, but ChatPage still needs them to resolve the open chat's
// friend, so the hook must keep returning them).
function sortByActivity(items: ConversationListItem[]): ConversationListItem[] {
  return [...items].sort((a, b) => {
    if (a.lastMessageAt === null) return b.lastMessageAt === null ? 0 : 1
    if (b.lastMessageAt === null) return -1
    return b.lastMessageAt.localeCompare(a.lastMessageAt)
  })
}

// Loads the current user's 1-to-1 conversations with the other member's
// profile plus last-message/last-read info. conversation_members references
// auth.users (not profiles) so PostgREST can't embed the join, and "last
// message per conversation" needs a lateral — both live in the
// get_dm_overview() RPC; only the profiles fetch stays client-side.
export function useConversations() {
  const { user } = useAuth()
  const [conversations, setConversations] = useState<ConversationListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const userId = user?.id
    if (!userId) return
    let cancelled = false
    // Conversation ids currently in state — lets the messages handler decide
    // between an in-place patch and a full reload without touching state.
    let knownIds = new Set<string>()

    function fail(message: string) {
      setError(message)
      setLoading(false)
    }
    function done(items: ConversationListItem[]) {
      knownIds = new Set(items.map((i) => i.conversationId))
      setConversations(items)
      // Realtime-triggered reloads retry naturally, so a transient failure self-heals.
      setError(null)
      setLoading(false)
    }

    async function load() {
      const { data, error: overviewErr } = await supabase.rpc('get_dm_overview')
      if (cancelled) return
      if (overviewErr) return fail(overviewErr.message)
      const rows = data as OverviewRow[]
      if (rows.length === 0) return done([])

      const otherIds = [...new Set(rows.map((r) => r.other_user_id))]
      const { data: profiles, error: profileErr } = await supabase
        .from('profiles')
        .select('*')
        .in('id', otherIds)
      if (cancelled) return
      if (profileErr) return fail(profileErr.message)

      const profileById = new Map((profiles as Profile[]).map((p) => [p.id, p]))
      done(
        sortByActivity(
          rows.flatMap((r) => {
            const friend = profileById.get(r.other_user_id)
            return friend
              ? [
                  {
                    conversationId: r.conversation_id,
                    friend,
                    lastMessageAt: r.last_message_at,
                    lastSenderId: r.last_sender_id,
                    lastReadAt: r.last_read_at,
                  },
                ]
              : []
          }),
        ),
      )
    }

    // Subscribe BEFORE fetching so no change lands between the initial fetch
    // and the live stream. A conversation_members INSERT for me means a
    // conversation was created for me — it fires for both the creator and
    // the other member, and (unlike the conversations row) it can't arrive
    // before the membership that grants RLS visibility -> refetch. Profile
    // UPDATEs are patched in place so names/avatars stay live. Message
    // INSERTs (unfiltered — RLS scopes delivery to my conversations) keep
    // last-message info live; conversation_members UPDATEs for me keep
    // last_read_at live (clears the unread dot, syncs across tabs).
    const channel = supabase
      .channel(`conversations:${userId}`)
      .on(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'conversation_members',
          filter: `user_id=eq.${userId}`,
        },
        load,
      )
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'messages' }, (payload) => {
        if (cancelled) return
        const msg = payload.new as Message
        if (!knownIds.has(msg.conversation_id)) {
          // First visible message in a conversation we haven't loaded yet.
          void load()
          return
        }
        setConversations((prev) =>
          sortByActivity(
            prev.map((c) =>
              c.conversationId === msg.conversation_id
                ? { ...c, lastMessageAt: msg.created_at, lastSenderId: msg.sender_id }
                : c,
            ),
          ),
        )
      })
      .on(
        'postgres_changes',
        {
          event: 'UPDATE',
          schema: 'public',
          table: 'conversation_members',
          filter: `user_id=eq.${userId}`,
        },
        (payload) => {
          if (cancelled) return
          const member = payload.new as { conversation_id: string; last_read_at: string }
          setConversations((prev) =>
            prev.map((c) =>
              c.conversationId === member.conversation_id
                ? { ...c, lastReadAt: member.last_read_at }
                : c,
            ),
          )
        },
      )
      .on('postgres_changes', { event: 'UPDATE', schema: 'public', table: 'profiles' }, (payload) => {
        if (cancelled) return
        const updated = payload.new as Profile
        setConversations((prev) =>
          prev.map((c) => (c.friend.id === updated.id ? { ...c, friend: updated } : c)),
        )
      })
      .subscribe()

    load()
    return () => {
      cancelled = true
      supabase.removeChannel(channel)
    }
  }, [user?.id])

  return { conversations, loading, error }
}
