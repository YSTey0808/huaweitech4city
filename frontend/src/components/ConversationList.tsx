import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import Avatar from './Avatar'
import type { ConversationListItem } from '../hooks/useConversations'
import type { Profile } from '../types/db'

interface ConversationListProps {
  items: ConversationListItem[]
  loading: boolean
  error: string | null
  myId?: string
  friends: Profile[]
  onStartChat: (friend: Profile) => void
  startingId: string | null
  startError?: string | null // open-or-create failed — list itself still fine
  activeId?: string
  flaggedIds?: Set<string> // conversations with any harm-score rows
  flaggedError?: string | null // badge fetch failed — list still usable, badges missing
}

function matchesQuery(p: Profile, query: string): boolean {
  const needle = query.trim().toLowerCase()
  if (!needle) return true
  return (
    (p.display_name?.toLowerCase().includes(needle) ?? false) ||
    (p.username?.toLowerCase().includes(needle) ?? false)
  )
}

export default function ConversationList({
  items,
  loading,
  error,
  myId,
  friends,
  onStartChat,
  startingId,
  startError,
  activeId,
  flaggedIds,
  flaggedError,
}: ConversationListProps) {
  const [query, setQuery] = useState('')
  const [pickerOpen, setPickerOpen] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const hasQuery = query.trim() !== ''
  const showFriends = hasQuery || pickerOpen

  // Conversations without messages are hidden (they exist the moment a chat
  // is opened, but shouldn't clutter the list); the friend still shows up in
  // the Friends section, and clicking there resolves to the same conversation.
  const visible = items.filter((i) => i.lastMessageAt !== null && matchesQuery(i.friend, query))
  const visibleFriendIds = new Set(visible.map((i) => i.friend.id))
  const friendResults = showFriends
    ? friends.filter((f) => matchesQuery(f, query) && !visibleFriendIds.has(f.id))
    : []

  function togglePicker() {
    setPickerOpen((open) => !open)
    inputRef.current?.focus()
  }

  return (
    <>
      <div className="sticky top-0 z-10 flex shrink-0 gap-2 border-b border-slate-200 bg-white px-4 py-2">
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search chats & friends"
          aria-label="Search chats and friends"
          className="min-w-0 flex-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-900 outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
        />
        <button
          type="button"
          onClick={togglePicker}
          aria-label="New chat"
          aria-pressed={pickerOpen}
          title="New chat"
          className={`shrink-0 rounded-md px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 ${
            pickerOpen ? 'bg-emerald-700' : 'bg-emerald-600'
          }`}
        >
          +
        </button>
      </div>

      {flaggedError && (
        <p className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-800">
          {flaggedError}
        </p>
      )}
      {startError && (
        <p className="border-b border-red-200 bg-red-50 px-4 py-2 text-xs text-red-700">
          {startError}
        </p>
      )}

      {loading ? (
        <p className="px-4 py-3 text-sm text-slate-500">Loading…</p>
      ) : error ? (
        <p className="px-4 py-3 text-sm text-red-600">{error}</p>
      ) : (
        <>
          {visible.length > 0 && (
            <ul className="divide-y divide-slate-200">
              {visible.map(({ conversationId, friend, lastMessageAt, lastSenderId, lastReadAt }) => {
                const unread =
                  lastMessageAt !== null &&
                  lastSenderId !== null &&
                  lastSenderId !== myId &&
                  lastMessageAt > lastReadAt &&
                  conversationId !== activeId
                return (
                  <li key={conversationId}>
                    <Link
                      to={`/chat/${conversationId}`}
                      className={`flex items-center gap-3 px-4 py-3 hover:bg-slate-50 ${
                        conversationId === activeId ? 'bg-emerald-50' : ''
                      }`}
                    >
                      <Avatar
                        size="md"
                        name={friend.display_name ?? friend.username}
                        color={friend.avatar_color}
                      />
                      <div className="min-w-0 flex-1">
                        <p
                          className={`truncate text-sm text-slate-900 ${
                            unread ? 'font-semibold' : 'font-medium'
                          }`}
                        >
                          {friend.display_name ?? friend.username ?? '—'}
                        </p>
                        {friend.username && (
                          <p className="truncate text-xs text-slate-500">@{friend.username}</p>
                        )}
                      </div>
                      {flaggedIds?.has(conversationId) && (
                        <span
                          aria-label="Has safety alerts"
                          title="Has safety alerts"
                          className="shrink-0 rounded-full bg-red-100 px-1.5 py-0.5 text-[10px] font-medium text-red-700"
                        >
                          ⚠
                        </span>
                      )}
                      {unread && (
                        <span
                          aria-label="Unread messages"
                          title="Unread messages"
                          className="h-2.5 w-2.5 shrink-0 rounded-full bg-emerald-500"
                        />
                      )}
                    </Link>
                  </li>
                )
              })}
            </ul>
          )}

          {showFriends && friendResults.length > 0 && (
            <>
              <p className="px-4 pb-1 pt-3 text-xs font-medium uppercase tracking-wide text-slate-500">
                Friends
              </p>
              <ul className="divide-y divide-slate-200 border-t border-slate-200">
                {friendResults.map((f) => (
                  <li key={f.id}>
                    <button
                      type="button"
                      onClick={() => onStartChat(f)}
                      disabled={startingId !== null}
                      className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-slate-50 disabled:opacity-50"
                    >
                      <Avatar
                        size="md"
                        name={f.display_name ?? f.username}
                        color={f.avatar_color}
                      />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-slate-900">
                          {f.display_name ?? f.username ?? '—'}
                        </p>
                        {f.username && (
                          <p className="truncate text-xs text-slate-500">@{f.username}</p>
                        )}
                      </div>
                      <span className="shrink-0 text-xs font-medium text-emerald-700">
                        {startingId === f.id ? 'Opening…' : 'Chat'}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}

          {visible.length === 0 && friendResults.length === 0 && (
            <p className="px-4 py-3 text-sm text-slate-500">
              {hasQuery ? (
                'No matches.'
              ) : (
                <>
                  {pickerOpen ? 'No friends yet. Go to ' : 'No chats yet. Tap + or go to '}
                  <Link to="/friends" className="font-medium text-emerald-700 hover:underline">
                    Friends
                  </Link>{' '}
                  {pickerOpen ? 'to add some.' : 'to start one.'}
                </>
              )}
            </p>
          )}
        </>
      )}
    </>
  )
}
