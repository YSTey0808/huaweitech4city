import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useConversations } from '../hooks/useConversations'
import { useFriends } from '../hooks/useFriends'
import { useFlaggedConversations } from '../hooks/useFlaggedConversations'
import { openOrCreateDm } from '../lib/conversations'
import ConversationList from '../components/ConversationList'
import ChatPane from '../components/ChatPane'
import type { Profile } from '../types/db'

// Serves both /chat (no param) and /chat/:conversationId.
// md+: sidebar + chat pane + alert column side by side (max-w-6xl to fit the
// alert panel). Phone: one pane at a time — /chat shows the list, /chat/:id
// shows the chat with a back arrow; alerts live in ChatPane's pull-up sheet.
export default function ChatPage() {
  const { conversationId } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const { conversations, loading, error } = useConversations()
  const { friends } = useFriends()
  const { flaggedIds, error: flaggedError } = useFlaggedConversations()
  const [startingId, setStartingId] = useState<string | null>(null)
  const [startError, setStartError] = useState<string | null>(null)
  const friend = conversations.find((c) => c.conversationId === conversationId)?.friend

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
    <div className="mx-auto flex h-full w-full max-w-6xl">
      <aside
        className={`${conversationId ? 'hidden md:flex' : 'flex'} w-full flex-col overflow-y-auto bg-white md:w-72 md:shrink-0 md:border-r md:border-slate-200`}
      >
        <ConversationList
          items={conversations}
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

      <section className={`${conversationId ? 'flex' : 'hidden md:flex'} min-w-0 flex-1 flex-col`}>
        {conversationId ? (
          <ChatPane key={conversationId} conversationId={conversationId} friend={friend} />
        ) : (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-slate-500">Select a chat to start messaging.</p>
          </div>
        )}
      </section>
    </div>
  )
}
