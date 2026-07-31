import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useConversations } from '../hooks/useConversations'
import { useFriends } from '../hooks/useFriends'
import { useFlaggedConversations } from '../hooks/useFlaggedConversations'
import { openOrCreateDm } from '../lib/conversations'
import ConversationList from '../components/ConversationList'
import ChatPane from '../components/ChatPane'
import InboxFilters from '../components/InboxFilters'
import type { InboxFilter } from '../components/InboxFilters'
import NavRail from '../components/NavRail'
import type { Profile } from '../types/db'

// Serves both /chat (no param) and /chat/:conversationId.
// md+: four columns — nav rail | inbox filters | conversation list | chat
// (+ ChatPane's own safety column on the right). Phone: one pane at a time —
// /chat shows the list, /chat/:id shows the chat with a back arrow; alerts
// live in ChatPane's pull-up sheet. The rail and filter column are md+ only,
// so the phone flow is unchanged.
export default function ChatPage() {
  const { conversationId } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const { conversations, loading, error } = useConversations()
  const { friends } = useFriends()
  const { flaggedIds, error: flaggedError } = useFlaggedConversations()
  const [startingId, setStartingId] = useState<string | null>(null)
  const [startError, setStartError] = useState<string | null>(null)
  const [filter, setFilter] = useState<InboxFilter>('all')
  const friend = conversations.find((c) => c.conversationId === conversationId)?.friend

  // Same visibility rule ConversationList applies (a conversation with no
  // messages is hidden), so the counts match what the list actually shows.
  const withMessages = useMemo(
    () => conversations.filter((c) => c.lastMessageAt !== null),
    [conversations],
  )
  // Unread mirrors the row's own derivation exactly -- see ConversationList.
  const isUnread = useMemo(
    () => (c: (typeof conversations)[number]) =>
      c.lastMessageAt !== null &&
      c.lastSenderId !== null &&
      c.lastSenderId !== user?.id &&
      c.lastMessageAt > c.lastReadAt &&
      c.conversationId !== conversationId,
    [user?.id, conversationId],
  )
  const counts = useMemo(
    () => ({
      all: withMessages.length,
      unread: withMessages.filter(isUnread).length,
      flagged: withMessages.filter((c) => flaggedIds.has(c.conversationId)).length,
    }),
    [withMessages, isUnread, flaggedIds],
  )
  // Filtering narrows what the list receives; it never changes how a row
  // renders or how switching works.
  const visibleConversations = useMemo(() => {
    if (filter === 'flagged') return conversations.filter((c) => flaggedIds.has(c.conversationId))
    if (filter === 'unread') return conversations.filter(isUnread)
    return conversations
  }, [conversations, filter, flaggedIds, isUnread])

  async function handleStartChat(target: Profile) {
    setStartError(null)
    setStartingId(target.id)
    try {
      const id = await openOrCreateDm(target.id)
      navigate(`/chat/${id}`)
    } catch (e) {
      setStartError(e instanceof Error ? e.message : 'Could not open the chat.')
    } finally {
      setStartingId(null)
    }
  }

  return (
    // md+: panes sit as one rounded card on the tinted canvas. Phone keeps the
    // original edge-to-edge full-bleed (no margin/radius) so nothing shifts.
    // One bordered, rounded shell containing all four columns (md+); the
    // columns divide it with their own right borders. Phone keeps the original
    // edge-to-edge full-bleed so nothing shifts there.
    <div className="mx-auto flex h-full w-full max-w-[min(94vw,1920px)] overflow-hidden md:my-3 md:h-[calc(100%-1.5rem)] md:rounded-2xl md:border md:border-slate-200/80 md:shadow-panel">
      <NavRail />

      {/* Inbox filter column -- md+ only, so the phone list/chat flow is
          untouched. Sits between the rail and the conversation list, matching
          the reference's four-column shell. */}
      <aside className="hidden w-44 shrink-0 flex-col overflow-y-auto border-r border-slate-200/80 bg-panel lg:flex">
        <InboxFilters active={filter} onChange={setFilter} counts={counts} />
      </aside>

      <aside
        className={`${conversationId ? 'hidden md:flex' : 'flex'} w-full flex-col overflow-y-auto bg-panel md:w-72 md:shrink-0 md:border-r md:border-slate-200/80 md:shadow-panel lg:w-80`}
      >
        <ConversationList
          items={visibleConversations}
          loading={loading}
          error={error}
          myId={user?.id}
          friends={friends}
          onStartChat={handleStartChat}
          startingId={startingId}
          startError={startError}
          activeId={conversationId}
          flaggedIds={flaggedIds}
          flaggedError={flaggedError}
        />
      </aside>

      <section
        className={`${conversationId ? 'flex' : 'hidden md:flex'} min-w-0 flex-1 flex-col bg-panel`}
      >
        {conversationId ? (
          <ChatPane key={conversationId} conversationId={conversationId} friend={friend} />
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
            <span
              aria-hidden
              className="grid h-12 w-12 place-items-center rounded-2xl bg-brand-50 text-xl text-brand-500"
            >
              ✦
            </span>
            <p className="text-sm font-medium text-slate-700">Select a chat to start messaging.</p>
            <p className="text-xs text-slate-400">Your conversations are monitored for safety.</p>
          </div>
        )}
      </section>
    </div>
  )
}
