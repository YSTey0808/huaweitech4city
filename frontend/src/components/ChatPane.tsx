import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { supabase } from '../lib/supabase'
import { useMessages } from '../hooks/useMessages'
import type { ChatMessage } from '../hooks/useMessages'
import { useScores } from '../hooks/useScores'
import AlertPanel from './AlertPanel'
import Avatar from './Avatar'
import type { MessageScore, Profile } from '../types/db'

interface ChatPaneProps {
  conversationId: string
  friend?: Profile // may still be loading in the parent
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function MessageBubble({
  msg,
  own,
  onRetry,
  scores,
  isEvidence,
  isTarget,
}: {
  msg: ChatMessage
  own: boolean
  onRetry: (id: string) => void
  scores?: MessageScore[]
  isEvidence?: boolean
  isTarget?: boolean
}) {
  // Directly flagged (red) beats evidence-of-conversation-score (amber).
  const flagged = scores !== undefined && scores.length > 0
  const highlight = flagged ? 'ring-2 ring-red-400' : isEvidence ? 'ring-2 ring-amber-400' : ''
  // Deep-link flash uses outline so it stacks with the permanent ring flags.
  const flash = isTarget ? 'outline-2 outline-offset-2 outline-emerald-500' : ''
  return (
    <div id={`msg-${msg.id}`} className={`flex ${own ? 'justify-end' : 'justify-start'}`}>
      <div className="max-w-[75%]">
        <div
          title={new Date(msg.created_at).toLocaleString()}
          className={`rounded-lg px-3 py-2 text-sm break-words whitespace-pre-wrap ${highlight} ${flash} ${
            own
              ? `bg-emerald-600 text-white ${msg.status === 'sending' ? 'opacity-60' : ''}`
              : flagged
                ? 'border border-red-200 bg-red-50 text-slate-900'
                : 'border border-slate-200 bg-white text-slate-900'
          }`}
        >
          {msg.content}
        </div>
        {flagged && (
          <div className={`mt-0.5 flex flex-wrap gap-1 ${own ? 'justify-end' : ''}`}>
            {scores.map((s) => (
              <span
                key={s.id}
                className="rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-medium text-red-700 capitalize"
              >
                {s.label}
                {s.confidence != null && <> · {Math.round(s.confidence * 100)}%</>}
              </span>
            ))}
          </div>
        )}
        <p className={`mt-0.5 text-[11px] text-slate-400 ${own ? 'text-right' : ''}`}>
          {msg.status === 'failed' ? (
            <span className="text-red-600">
              Failed —{' '}
              <button onClick={() => onRetry(msg.id)} className="font-medium underline">
                Retry
              </button>
            </span>
          ) : (
            formatTime(msg.created_at)
          )}
        </p>
      </div>
    </div>
  )
}

export default function ChatPane({ conversationId, friend }: ChatPaneProps) {
  const { user } = useAuth()
  const { messages, loading, error, send, retry } = useMessages(conversationId)
  const {
    messageScores,
    conversationScores,
    evidenceIds,
    loading: scoresLoading,
    error: scoresError,
  } = useScores(conversationId)
  const [draft, setDraft] = useState('')
  const [alertsOpen, setAlertsOpen] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  // Deep-link target from /reports (?msg=<id>). Handled once per mount; the
  // key={conversationId} remount in ChatPage resets it per conversation.
  const [searchParams] = useSearchParams()
  const targetMsgId = searchParams.get('msg')
  const targetHandled = useRef(false)
  const [flashId, setFlashId] = useState<string | null>(null)

  const alertCount = conversationScores.length + messageScores.size

  useEffect(() => {
    if (loading) return
    if (targetMsgId && !targetHandled.current) {
      const el = document.getElementById(`msg-${targetMsgId}`)
      if (el) {
        targetHandled.current = true
        el.scrollIntoView({ block: 'center' })
        setFlashId(targetMsgId)
        return
      }
      // Target older than the loaded history window — fall through to bottom.
    }
    // Once the target is shown, new arrivals must not yank the view to bottom.
    if (!targetHandled.current) bottomRef.current?.scrollIntoView()
  }, [messages.length, loading, targetMsgId])

  useEffect(() => {
    if (!flashId) return
    const t = setTimeout(() => setFlashId(null), 1600)
    return () => clearTimeout(t)
  }, [flashId])

  // Mark the conversation read on open and whenever a new message lands while
  // it's open. Fire-and-forget: the realtime echo of this UPDATE is what
  // clears the unread dot in useConversations (and in other tabs).
  const lastMessageId = messages[messages.length - 1]?.id
  useEffect(() => {
    if (!user) return
    supabase
      .from('conversation_members')
      .update({ last_read_at: new Date().toISOString() })
      .eq('conversation_id', conversationId)
      .eq('user_id', user.id)
      .then(({ error: readErr }) => {
        if (readErr) console.error('mark-read failed:', readErr.message)
      })
  }, [conversationId, user, lastMessageId])

  function handleSend(e: FormEvent) {
    e.preventDefault()
    if (!draft.trim()) return
    send(draft)
    setDraft('')
  }

  return (
    <div className="flex h-full min-h-0">
      <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col">
        <div className="flex shrink-0 items-center gap-3 border-b border-slate-200 bg-white px-4 py-2.5">
          <Link
            to="/chat"
            aria-label="Back to chats"
            className="-ml-1 rounded-md p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-900 md:hidden"
          >
            <svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5" aria-hidden="true">
              <path
                fillRule="evenodd"
                d="M12.79 5.23a.75.75 0 0 1-.02 1.06L8.83 10l3.94 3.71a.75.75 0 1 1-1.04 1.08l-4.5-4.25a.75.75 0 0 1 0-1.08l4.5-4.25a.75.75 0 0 1 1.06.02Z"
                clipRule="evenodd"
              />
            </svg>
          </Link>
          <Avatar size="sm" name={friend?.display_name ?? friend?.username} color={friend?.avatar_color} />
          <p className="min-w-0 truncate text-sm font-medium text-slate-900">
            {friend?.display_name ?? friend?.username ?? '…'}
          </p>
        </div>

        {conversationScores.length > 0 && (
          <div className="shrink-0 border-b border-red-200 bg-red-50 px-4 py-2">
            {conversationScores.map((s) => (
              <p key={s.id} className="text-sm text-red-800">
                ⚠ <span className="font-medium capitalize">{s.label}</span> risk detected
                {s.confidence != null && <> — confidence {Math.round(s.confidence * 100)}%</>}
              </p>
            ))}
          </div>
        )}

        <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-4 py-3">
          {loading ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : error ? (
            <p className="text-sm text-red-600">{error}</p>
          ) : messages.length === 0 ? (
            <p className="text-sm text-slate-500">No messages yet. Say hi!</p>
          ) : (
            messages.map((m) => (
              <MessageBubble
                key={m.id}
                msg={m}
                own={m.sender_id === user?.id}
                onRetry={retry}
                scores={messageScores.get(m.id)}
                isEvidence={evidenceIds.has(m.id)}
                isTarget={m.id === flashId}
              />
            ))
          )}
          <div ref={bottomRef} />
        </div>

        {/* Phone: in-flow pull-up sheet above the composer; md+ uses the side column. */}
        <div className="shrink-0 md:hidden">
          <button
            onClick={() => setAlertsOpen((o) => !o)}
            aria-expanded={alertsOpen}
            className={`flex w-full items-center justify-between border-t px-4 py-2 text-sm font-medium ${
              alertCount > 0
                ? 'border-amber-200 bg-amber-50 text-amber-800'
                : 'border-slate-200 bg-white text-slate-600'
            }`}
          >
            <span>
              Safety alerts
              {alertCount > 0 && ` (${alertCount})`}
            </span>
            <span aria-hidden>{alertsOpen ? '▾' : '▴'}</span>
          </button>
          {alertsOpen && (
            <div className="max-h-[45dvh] overflow-y-auto border-t border-slate-200 bg-white">
              <AlertPanel
                conversationScores={conversationScores}
                messageScores={messageScores}
                messages={messages}
                loading={scoresLoading}
                error={scoresError}
              />
            </div>
          )}
        </div>

        <form onSubmit={handleSend} className="flex shrink-0 gap-2 border-t border-slate-200 bg-white px-4 py-3">
          <input
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Type a message"
            aria-label="Message"
            className="w-full min-w-0 rounded-md border border-slate-300 px-3 py-2 text-slate-900 outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
          />
          <button
            type="submit"
            disabled={!draft.trim()}
            className="shrink-0 rounded-md bg-emerald-600 px-4 py-2 font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            Send
          </button>
        </form>
      </div>

      <aside className="hidden w-72 shrink-0 flex-col overflow-y-auto border-l border-slate-200 bg-white md:flex">
        <AlertPanel
          conversationScores={conversationScores}
          messageScores={messageScores}
          messages={messages}
          loading={scoresLoading}
          error={scoresError}
        />
      </aside>
    </div>
  )
}
