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

// Compact list timestamp from the existing lastMessageAt: clock time today,
// "Yesterday", weekday within the last week, then a short date. Purely a
// display format of data the hook already returns -- no new fetch.
function listTime(iso: string): string {
  const then = new Date(iso)
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const daysAgo = Math.floor((startOfToday.getTime() - then.getTime()) / 86_400_000)

  if (then >= startOfToday) {
    return then.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }
  if (daysAgo < 1) return 'Yesterday'
  if (daysAgo < 6) return then.toLocaleDateString([], { weekday: 'short' })
  return then.toLocaleDateString([], { day: 'numeric', month: 'short' })
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
      <div className="sticky top-0 z-10 shrink-0 border-b border-slate-200/70 bg-panel/95 px-4 pb-3 pt-4 backdrop-blur">
        <h2 className="mb-3 px-0.5 text-base font-semibold tracking-tight text-slate-900">
          My Chats
        </h2>
        <div className="flex gap-2">
          <div className="relative min-w-0 flex-1">
            <span
              aria-hidden
              className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-slate-400"
            >
              <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
                <path
                  fillRule="evenodd"
                  d="M9 3.5a5.5 5.5 0 1 0 3.4 9.83l3.13 3.14a.75.75 0 1 0 1.07-1.06l-3.14-3.14A5.5 5.5 0 0 0 9 3.5ZM5 9a4 4 0 1 1 8 0 4 4 0 0 1-8 0Z"
                  clipRule="evenodd"
                />
              </svg>
            </span>
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search chats & friends"
              aria-label="Search chats and friends"
              className="w-full min-w-0 rounded-xl border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-sm text-slate-900 transition-colors outline-none placeholder:text-slate-400 focus:border-field-focus focus:bg-ivory focus:shadow-field"
            />
          </div>
          <button
            type="button"
            onClick={togglePicker}
            aria-label="New chat"
            aria-pressed={pickerOpen}
            title="New chat"
            className={`shrink-0 rounded-xl px-3.5 py-2 text-sm font-semibold text-white shadow-brand transition-all hover:brightness-110 ${
              pickerOpen
                ? 'bg-gradient-to-br from-brand-600 to-brand-800'
                : 'bg-gradient-to-br from-brand-600 to-brand-700'
            }`}
          >
            +
          </button>
        </div>
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
            <ul className="space-y-0.5 px-2 py-2">
              {visible.map(({ conversationId, friend, lastMessageAt, lastSenderId, lastReadAt }) => {
                const unread =
                  lastMessageAt !== null &&
                  lastSenderId !== null &&
                  lastSenderId !== myId &&
                  lastMessageAt > lastReadAt &&
                  conversationId !== activeId
                // Derived from data the hook already returns -- no new fields,
                // no new fetch.
                const isFlagged = flaggedIds?.has(conversationId) ?? false
                return (
                  <li key={conversationId}>
                    <Link
                      to={`/chat/${conversationId}`}
                      // Selected = warm taupe, NOT the brand/harm ramp: a
                      // selected inbox item must not read as a flagged one.
                      // Focus ring is warm too -- the browser default is bright
                      // blue, which clashed with the cream theme.
                      className={`group flex items-center gap-3 rounded-xl px-3 py-2.5 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-outgoing-border ${
                        conversationId === activeId
                          ? 'border border-outgoing-border bg-outgoing shadow-card'
                          : 'border border-transparent hover:bg-slate-50'
                      }`}
                    >
                      <Avatar
                        size="md"
                        name={friend.display_name ?? friend.username}
                        color={friend.avatar_color}
                      />

                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline gap-2">
                          <p
                            className={`min-w-0 flex-1 truncate text-sm ${
                              unread
                                ? 'font-semibold text-slate-900'
                                : conversationId === activeId
                                  ? 'font-semibold text-slate-900'
                                  : 'font-medium text-slate-800'
                            }`}
                          >
                            {friend.display_name ?? friend.username ?? '—'}
                          </p>
                          {lastMessageAt && (
                            <span
                              title={new Date(lastMessageAt).toLocaleString()}
                              className={`shrink-0 text-[11px] tabular-nums ${
                                unread ? 'font-medium text-brand-600' : 'text-slate-400'
                              }`}
                            >
                              {listTime(lastMessageAt)}
                            </span>
                          )}
                        </div>

                        <div className="mt-0.5 flex items-center gap-2">
                          <p className="min-w-0 flex-1 truncate text-xs text-slate-600">
                            {friend.username ? `@${friend.username}` : ''}
                          </p>
                          {/* Boolean-only signals (flaggedIds is a Set, and
                              unread is derived from lastMessageAt/lastReadAt --
                              neither carries a count or severity), so both stay
                              dots rather than implying a number. */}
                          {isFlagged && (
                            <span
                              aria-label="Has safety alerts"
                              title="Has safety alerts"
                              className="h-2 w-2 shrink-0 rounded-full bg-harm-border ring-2 ring-harm-bg"
                            />
                          )}
                          {unread && (
                            <span
                              aria-label="Unread messages"
                              title="Unread messages"
                              className="h-2 w-2 shrink-0 rounded-full bg-brand-600 ring-2 ring-brand-100"
                            />
                          )}
                        </div>
                      </div>
                    </Link>
                  </li>
                )
              })}
            </ul>
          )}

          {showFriends && friendResults.length > 0 && (
            <>
              <p className="px-5 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                Friends
              </p>
              <ul className="space-y-0.5 border-t border-slate-100 px-2 pt-2">
                {friendResults.map((f) => (
                  <li key={f.id}>
                    <button
                      type="button"
                      onClick={() => onStartChat(f)}
                      disabled={startingId !== null}
                      className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors outline-none hover:bg-slate-50 focus-visible:ring-2 focus-visible:ring-outgoing-border disabled:opacity-50"
                    >
                      <Avatar
                        size="md"
                        name={f.display_name ?? f.username}
                        color={f.avatar_color}
                      />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-slate-800">
                          {f.display_name ?? f.username ?? '—'}
                        </p>
                        {f.username && (
                          <p className="truncate text-xs text-slate-400">@{f.username}</p>
                        )}
                      </div>
                      <span className="shrink-0 rounded-lg bg-brand-50 px-2 py-1 text-xs font-semibold text-brand-700">
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
                  <Link to="/friends" className="font-semibold text-brand-600 hover:underline">
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
