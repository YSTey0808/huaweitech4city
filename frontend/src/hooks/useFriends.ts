import { useEffect, useState } from 'react'
import { supabase } from '../lib/supabase'
import { useAuth } from '../context/AuthContext'
import type { Profile } from '../types/db'

function sortByName(profiles: Profile[]): Profile[] {
  return [...profiles].sort((a, b) =>
    (a.display_name ?? a.username ?? '').localeCompare(b.display_name ?? b.username ?? ''),
  )
}

// Live friends list. Any friendships change for me triggers a refetch
// (a DELETE payload carries only key columns, and an INSERT would need a
// profile fetch anyway); profile UPDATEs are patched in place so
// display-name/avatar edits appear live. friendships references auth.users
// (not profiles), so PostgREST can't embed the join — fetch friend ids,
// then their profiles.
export function useFriends() {
  const { user } = useAuth()
  const [friends, setFriends] = useState<Profile[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const userId = user?.id
    if (!userId) return
    let cancelled = false

    async function load() {
      const { data: rows, error: friendshipsErr } = await supabase
        .from('friendships')
        .select('friend_id')
        .eq('user_id', userId)
      if (cancelled) return
      if (friendshipsErr) {
        setError(friendshipsErr.message)
        setLoading(false)
        return
      }

      const ids = rows.map((r) => r.friend_id)
      if (ids.length === 0) {
        setFriends([])
        setError(null)
        setLoading(false)
        return
      }

      const { data: profiles, error: profilesErr } = await supabase
        .from('profiles')
        .select('*')
        .in('id', ids)
      if (cancelled) return
      if (profilesErr) setError(profilesErr.message)
      else {
        setFriends(sortByName(profiles))
        // Realtime-triggered reloads retry naturally, so a transient failure self-heals.
        setError(null)
      }
      setLoading(false)
    }

    // Subscribe BEFORE fetching so no change lands between the initial
    // fetch and the live stream; load() replaces the whole list, so the
    // overlap is harmless.
    const channel = supabase
      .channel(`friends:${userId}`)
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'friendships', filter: `user_id=eq.${userId}` },
        load,
      )
      .on('postgres_changes', { event: 'UPDATE', schema: 'public', table: 'profiles' }, (payload) => {
        if (cancelled) return
        const updated = payload.new as Profile
        setFriends((prev) =>
          prev.some((f) => f.id === updated.id)
            ? sortByName(prev.map((f) => (f.id === updated.id ? updated : f)))
            : prev,
        )
      })
      .subscribe()
    load()

    return () => {
      cancelled = true
      supabase.removeChannel(channel)
    }
  }, [user?.id])

  return { friends, loading, error }
}
