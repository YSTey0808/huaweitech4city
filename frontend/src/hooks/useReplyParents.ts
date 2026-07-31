import { useEffect, useRef, useState } from 'react'
import { supabase } from '../lib/supabase'
import type { ChatMessage } from './useMessages'
import type { Message } from '../types/db'

// Resolves the parent of every reply in `messages` to a full row, so a reply
// bubble can quote what it is replying to.
//
// Most parents need no work: useMessages already holds the last HISTORY_LIMIT
// (50) messages, and people usually reply to something recent. The gap this
// hook closes is the older parent -- reply to a message from 200 messages ago
// and that row simply is not in the browser, so without this the quote would
// have nothing to show.
//
// Fetched ids are remembered even when the fetch returns nothing, so a parent
// that cannot be resolved (deleted, or hidden) is attempted once and never
// retried in a loop. Together with the id-set dependency below that keeps this
// at one query per batch of newly-seen parents, not one per render.
//
// The query has no conversation filter on purpose: messages_select_member
// (migration 001) already restricts reads to conversations the user belongs
// to, so RLS is what scopes this, exactly as in useReports.
export function useReplyParents(messages: ChatMessage[]): Map<string, Message> {
  const [fetched, setFetched] = useState<Map<string, Message>>(new Map())
  const requested = useRef<Set<string>>(new Set())

  // Parents referenced by a reply but absent from the loaded window. Joined
  // into a string so the effect re-runs on membership change, not on every
  // new array identity (messages is rebuilt on each upsert).
  const loaded = new Set(messages.map((m) => m.id))
  const missing = [
    ...new Set(
      messages
        .map((m) => m.reply_to)
        .filter((id): id is string => id !== null && !loaded.has(id)),
    ),
  ]
  const missingKey = missing.join(',')

  useEffect(() => {
    const toFetch = missing.filter((id) => !requested.current.has(id))
    if (toFetch.length === 0) return
    for (const id of toFetch) requested.current.add(id)

    let cancelled = false
    supabase
      .from('messages')
      .select('*')
      .in('id', toFetch)
      .then(({ data, error }) => {
        if (cancelled) return
        if (error) {
          // Non-fatal: the bubble falls back to "(message not loaded)".
          console.warn('reply parent fetch failed:', error.message)
          return
        }
        setFetched((prev) => {
          const next = new Map(prev)
          for (const m of data as Message[]) next.set(m.id, m)
          return next
        })
      })

    return () => {
      cancelled = true
    }
    // Keyed on the id set, not on `messages`/`missing` themselves: both are
    // rebuilt on every upsert, which would re-run this on every arriving
    // message. missingKey only changes when the set of unresolved parents does.
  }, [missingKey])

  // In-window messages win: they are the same rows, already live.
  const parents = new Map<string, Message>(fetched)
  for (const m of messages) parents.set(m.id, m)
  return parents
}
