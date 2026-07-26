import { useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { supabase } from '../lib/supabase'
import { useAuth } from '../context/AuthContext'
import { useFriends } from '../hooks/useFriends'
import { openOrCreateDm } from '../lib/conversations'
import Avatar from '../components/Avatar'
import type { Profile } from '../types/db'

export default function FriendsPage() {
  const { user } = useAuth()
  const navigate = useNavigate()

  const { friends, loading: friendsLoading, error: friendsError } = useFriends()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Profile[] | null>(null) // null = not searched yet
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [addingId, setAddingId] = useState<string | null>(null)
  const [openingId, setOpeningId] = useState<string | null>(null)
  // Friends added in this session — bridges the gap until the realtime echo
  // updates useFriends, and switches the row's button to "Say hi".
  const [addedIds, setAddedIds] = useState<Set<string>>(new Set())

  async function handleSearch(e: FormEvent) {
    e.preventDefault()
    setError(null)

    const term = query.trim()
    if (!term) {
      setError('Enter a username or email to search.')
      return
    }

    setSearching(true)
    const { data, error: searchErr } = await supabase.rpc('search_profiles', {
      search_term: term,
    })
    if (searchErr) setError(searchErr.message)
    else setResults((data as Profile[]).filter((p) => p.id !== user?.id))
    setSearching(false)
  }

  async function handleAdd(target: Profile) {
    if (!user) return
    setError(null)

    if (target.id === user.id) {
      setError("You can't add yourself as a friend.")
      return
    }
    if (friends.some((f) => f.id === target.id)) {
      setError('You are already friends with this user.')
      return
    }

    setAddingId(target.id)
    // Two-row friendship model: both directions in one atomic insert.
    const { error: insertErr } = await supabase.from('friendships').insert([
      { user_id: user.id, friend_id: target.id },
      { user_id: target.id, friend_id: user.id },
    ])
    if (insertErr) {
      setError(
        insertErr.code === '23505'
          ? 'You are already friends with this user.'
          : insertErr.message,
      )
    } else {
      setAddedIds((prev) => new Set(prev).add(target.id))
    }
    // On success the realtime echo of our own friendships INSERT adds the
    // friend to the list (useFriends), same as useMessages relies on its echo.
    setAddingId(null)
  }

  async function handleOpenChat(friend: Profile) {
    if (!user) return
    setError(null)
    setOpeningId(friend.id)
    try {
      const conversationId = await openOrCreateDm(friend.id)
      navigate(`/chat/${conversationId}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not open the chat.')
      setOpeningId(null)
    }
  }

  return (
    <div className="mx-auto w-full max-w-sm px-4 py-10">
      <h1 className="text-2xl font-bold text-slate-900">Friends</h1>
      <p className="mt-1 text-sm text-slate-500">Add friends by username or email.</p>

      <form onSubmit={handleSearch} className="mt-6 flex gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Username or email"
          aria-label="Search by username or email"
          className="w-full min-w-0 rounded-md border border-slate-300 px-3 py-2 text-slate-900 outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
        />
        <button
          type="submit"
          disabled={searching}
          className="shrink-0 rounded-md bg-emerald-600 px-4 py-2 font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
        >
          {searching ? 'Searching…' : 'Search'}
        </button>
      </form>

      {(error ?? friendsError) && (
        <p className="mt-2 text-sm text-red-600">{error ?? friendsError}</p>
      )}

      {results !== null &&
        (results.length === 0 ? (
          <p className="mt-4 text-sm text-slate-500">No users found.</p>
        ) : (
          <ul className="mt-4 divide-y divide-slate-200 rounded-md border border-slate-200 bg-white">
            {results.map((r) => {
              const isFriend = friends.some((f) => f.id === r.id) || addedIds.has(r.id)
              return (
                <li key={r.id} className="flex items-center gap-3 px-3 py-2">
                  <Avatar size="sm" name={r.display_name ?? r.username} color={r.avatar_color} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-slate-900">
                      {r.display_name ?? r.username ?? '—'}
                    </p>
                    {r.username && (
                      <p className="truncate text-xs text-slate-500">@{r.username}</p>
                    )}
                  </div>
                  {isFriend ? (
                    <button
                      onClick={() => handleOpenChat(r)}
                      disabled={openingId !== null}
                      className="shrink-0 rounded-md border border-emerald-600 px-3 py-1 text-sm font-medium text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
                    >
                      {openingId === r.id ? 'Opening…' : addedIds.has(r.id) ? 'Say hi' : 'Chat'}
                    </button>
                  ) : (
                    <button
                      onClick={() => handleAdd(r)}
                      disabled={addingId !== null}
                      className="shrink-0 rounded-md border border-emerald-600 px-3 py-1 text-sm font-medium text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
                    >
                      {addingId === r.id ? 'Adding…' : 'Add'}
                    </button>
                  )}
                </li>
              )
            })}
          </ul>
        ))}

      <h2 className="mt-8 text-sm font-medium text-slate-700">Your friends</h2>
      {friendsLoading ? (
        <p className="mt-2 text-sm text-slate-500">Loading…</p>
      ) : friends.length === 0 ? (
        <p className="mt-2 text-sm text-slate-500">
          No friends yet. Search above to add someone.
        </p>
      ) : (
        <ul className="mt-2 divide-y divide-slate-200 rounded-md border border-slate-200 bg-white">
          {friends.map((f) => (
            <li key={f.id}>
              <button
                onClick={() => handleOpenChat(f)}
                disabled={openingId !== null}
                className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-slate-50 disabled:opacity-50"
              >
                <Avatar size="md" name={f.display_name ?? f.username} color={f.avatar_color} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-slate-900">
                    {f.display_name ?? f.username ?? '—'}
                  </p>
                  {f.username && (
                    <p className="truncate text-xs text-slate-500">@{f.username}</p>
                  )}
                </div>
                <span className="shrink-0 text-xs text-slate-400">
                  {openingId === f.id ? 'Opening…' : 'Chat'}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
