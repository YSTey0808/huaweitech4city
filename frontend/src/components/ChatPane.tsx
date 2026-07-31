import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { supabase } from '../lib/supabase'
import { useMessages } from '../hooks/useMessages'
import type { ChatMessage } from '../hooks/useMessages'
import { useReplyParents } from '../hooks/useReplyParents'
import { useScores } from '../hooks/useScores'
import AlertPanel from './AlertPanel'
import Avatar from './Avatar'
import RiskBadge from './RiskBadge'
import ReportConversationDialog from './ReportConversationDialog'
import FeedbackDialog from './FeedbackDialog'
import type { Message, MessageScore, Profile } from '../types/db'

interface ChatPaneProps {
  conversationId: string
  friend?: Profile // may still be loading in the parent
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

// Visible by default, then hidden again from md up until the row is hovered
// or the button itself is focused. Phones have no hover, and they are the
// primary target here -- so touch keeps it on screen permanently, while a
// desktop thread stays visually quiet at rest.
//
// Two details that are easy to get wrong:
//   - pointer-events is dropped alongside opacity on md, so the invisible
//     resting button is not a hidden click target next to the bubble.
//     Keyboard focus is unaffected by pointer-events, so focus-visible still
//     reveals it.
//   - `disabled` (message not yet confirmed) hides it but keeps its box, so a
//     bubble does not shift sideways the instant a send is acknowledged.
function ReplyButton({ onClick, disabled }: { onClick: () => void; disabled: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label="Reply to this message"
      title="Reply"
      className="shrink-0 rounded-full p-1.5 text-slate-400 transition-all outline-none hover:bg-slate-100 hover:text-slate-600 focus-visible:opacity-100 disabled:pointer-events-none disabled:opacity-0 md:pointer-events-none md:opacity-0 md:group-hover:pointer-events-auto md:group-hover:opacity-100 md:group-focus-within:opacity-100"
    >
      <svg viewBox="0 0 20 20" fill="currentColor" className="h-3.5 w-3.5" aria-hidden="true">
        <path d="M8.5 4.5a.75.75 0 0 0-1.28-.53l-4.25 4.25a.75.75 0 0 0 0 1.06l4.25 4.25a.75.75 0 0 0 1.28-.53V11h2.25A4.25 4.25 0 0 1 15 15.25a.75.75 0 0 0 1.5 0A5.75 5.75 0 0 0 10.75 9.5H8.5v-5Z" />
      </svg>
    </button>
  )
}

// Per-message feedback (Report / "Not harmful?" / outcome text / escalation)
// was removed: reporting is now conversation-level via the chat header's
// Report button. The bubble stays presentational apart from retry and the
// reply affordance below, which is deliberately hover-only on desktop so the
// resting thread keeps that clean, non-interactive look.
function MessageBubble({
  msg,
  own,
  onRetry,
  scores,
  isEvidence,
  isTarget,
  parent,
  parentLabel,
  parentOnScreen,
  onReply,
  onJumpToParent,
}: {
  msg: ChatMessage
  own: boolean
  onRetry: (id: string) => void
  scores?: MessageScore[]
  isEvidence?: boolean
  isTarget?: boolean
  parent?: Message
  parentLabel?: string
  parentOnScreen: boolean
  onReply: () => void
  onJumpToParent: () => void
}) {
  // Directly flagged (red) beats evidence-of-conversation-score (amber).
  const flagged = scores !== undefined && scores.length > 0
  // A directly-flagged bubble carries its own border + left accent (see the
  // bubble classes below), so no extra ring -- doubling them read as a
  // highlighter. Evidence-of-a-conversation-score keeps a soft amber ring,
  // since that bubble is otherwise styled like an ordinary message.
  const highlight = flagged ? '' : isEvidence ? 'ring-1 ring-amber-300' : ''
  // Deep-link flash uses outline so it stacks with the permanent ring flags.
  const flash = isTarget ? 'outline-2 outline-offset-2 outline-brand-500' : ''
  // A parent that has not been confirmed by the server has no row to point at
  // yet, and migration 014's trigger would reject the reply. Independent HTTP
  // inserts give no ordering guarantee, so this is correctness, not polish.
  const canReply = msg.status === 'sent'
  return (
    <div
      id={`msg-${msg.id}`}
      className={`group flex items-center gap-1.5 ${own ? 'justify-end' : 'justify-start'}`}
    >
      {/* Reply sits on the bubble's inner side so it always points into the
          conversation. Always visible on touch (no hover to reveal it there);
          on md+ it fades in on hover or keyboard focus. */}
      {own && <ReplyButton onClick={onReply} disabled={!canReply} />}
      {/* 75% of the column, but never wider than ~34rem: on a wide screen an
          unbounded bubble produces uncomfortably long lines. */}
      <div className="max-w-[min(75%,34rem)]">
        {msg.reply_to && (
          // Quote sits ABOVE the bubble rather than inside it: the bubble
          // already carries a tail notch and, when flagged, a full red
          // outline -- an inner block fought both.
          <p className={`mb-0.5 flex max-w-full text-[11px] text-slate-400 ${own ? 'justify-end' : ''}`}>
            <span aria-hidden className="mr-1 shrink-0">
              ↩
            </span>
            {parentOnScreen ? (
              <button
                type="button"
                onClick={onJumpToParent}
                className="min-w-0 truncate underline decoration-slate-300 underline-offset-2 transition-colors outline-none hover:text-slate-600 focus-visible:text-slate-600"
              >
                {parentLabel}: {parent?.content}
              </button>
            ) : (
              // Parent is outside the loaded window and could not be fetched,
              // so there is nothing to scroll to -- plain text, not a button.
              <span className="min-w-0 truncate">
                {parent ? `${parentLabel}: ${parent.content}` : '(message not loaded)'}
              </span>
            )}
          </p>
        )}
        <div
          title={new Date(msg.created_at).toLocaleString()}
          className={`px-3.5 py-2 text-sm break-words whitespace-pre-wrap ${
            // A flagged bubble keeps an even 16px radius on all four corners --
            // the tail notch fought the full outline. Its halo replaces
            // shadow-bubble so the two elevations don't stack.
            flagged
              ? 'rounded-2xl'
              : own
                ? 'rounded-2xl rounded-br-md shadow-bubble'
                : 'rounded-2xl rounded-bl-md shadow-bubble'
          } ${highlight} ${flash} ${
            // Each side keeps its own fill; only the BORDER changes when
            // flagged. An outgoing harmful message stays beige (it's still
            // your own message) and simply gains the red safety outline.
            own
              ? `border-[1.5px] bg-outgoing text-slate-900 ${
                  flagged ? 'border-harm-outline shadow-harm' : 'border-outgoing-border'
                } ${msg.status === 'sending' ? 'opacity-60' : ''}`
              : flagged
                ? // Incoming flagged: near-white fill with the same 1.5px
                  // outline plus a soft halo. No left accent -- an even outline
                  // reads as Nuwa highlighting the message, where a side stripe
                  // turned the bubble into an alert card. Filled pink stays in
                  // the safety panel.
                  'border-[1.5px] border-harm-outline bg-harm-bubble text-slate-900 shadow-harm'
                : 'border border-slate-200/80 bg-white text-slate-900'
          }`}
        >
          {msg.content}
        </div>
        {flagged && (
          <div className={`mt-1 flex flex-wrap gap-1.5 ${own ? 'justify-end' : ''}`}>
            {scores.map((s) => (
              <RiskBadge
                key={s.id}
                size="sm"
                label={s.label}
                confidence={s.confidence}
                source={s.source}
              />
            ))}
          </div>
        )}
        <p className={`mt-1 text-[11px] text-slate-400 ${own ? 'text-right' : ''}`}>
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
      {!own && <ReplyButton onClick={onReply} disabled={!canReply} />}
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
  const parents = useReplyParents(messages)
  const [draft, setDraft] = useState('')
  const [alertsOpen, setAlertsOpen] = useState(false)
  // Which message the next send replies to. Only one at a time, and it needs
  // no reset effect: ChatPage's key={conversationId} remounts this component
  // on every conversation switch.
  const [replyingTo, setReplyingTo] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  // Conversation-level report -- UI only until a backend contract exists (see
  // ReportConversationDialog). Resets per conversation via ChatPage's
  // key={conversationId} remount.
  const [reportOpen, setReportOpen] = useState(false)
  const [conversationReported, setConversationReported] = useState(false)
  // Feedback ("NUWA got this wrong") is tracked separately from a report --
  // they mean different things and can both happen on one conversation.
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const [feedbackSent, setFeedbackSent] = useState(false)
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

  // Label for a quoted parent. A DM has exactly two participants, so the
  // sender is either you or the friend already loaded by the parent page --
  // no profile lookup needed.
  function labelFor(msg: Message): string {
    if (msg.sender_id === user?.id) return 'You'
    return friend?.display_name ?? friend?.username ?? '…'
  }

  // Reuses the /reports deep-link mechanism: same anchor ids, same flash.
  // Deliberately does NOT set targetHandled -- that flag permanently disables
  // autoscroll-to-bottom, which is right for a one-shot deep link but would
  // leave the thread stuck after an ordinary jump to a quoted message.
  function jumpToParent(id: string) {
    document.getElementById(`msg-${id}`)?.scrollIntoView({ block: 'center' })
    setFlashId(id)
  }

  function startReply(id: string) {
    setReplyingTo(id)
    inputRef.current?.focus()
  }

  function handleSend(e: FormEvent) {
    e.preventDefault()
    if (!draft.trim()) return
    send(draft, replyingTo)
    setDraft('')
    setReplyingTo(null)
  }

  const replyParent = replyingTo ? parents.get(replyingTo) : undefined

  return (
    <div className="flex h-full min-h-0">
      <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col">
        <div className="flex shrink-0 items-center gap-3 border-b border-slate-200/70 bg-panel/95 px-5 py-3 backdrop-blur">
          <Link
            to="/chat"
            aria-label="Back to chats"
            className="-ml-1 rounded-lg p-1 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 md:hidden"
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
          <div className="min-w-0">
            <p className="min-w-0 truncate text-sm font-semibold tracking-tight text-slate-900">
              {friend?.display_name ?? friend?.username ?? '…'}
            </p>
            {friend?.username && (
              <p className="truncate text-xs text-slate-400">@{friend.username}</p>
            )}
          </div>

          {/* Report this conversation. Secondary styling on purpose -- it must
              be reachable but must not compete with the conversation itself.
              UI only for now (see ReportConversationDialog): the reported flag
              is local component state, not persisted. */}
          <div className="ml-auto shrink-0">
            {conversationReported ? (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-100 px-3.5 py-1.5 text-[13px] font-semibold text-slate-500">
                <svg viewBox="0 0 20 20" fill="currentColor" className="h-3.5 w-3.5" aria-hidden="true">
                  <path
                    fillRule="evenodd"
                    d="M16.7 5.3a1 1 0 0 1 0 1.4l-7.5 7.5a1 1 0 0 1-1.4 0l-3.5-3.5a1 1 0 1 1 1.4-1.4l2.8 2.79 6.8-6.79a1 1 0 0 1 1.4 0Z"
                    clipRule="evenodd"
                  />
                </svg>
                Reported
              </span>
            ) : (
              <button
                type="button"
                onClick={() => setReportOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-full border border-field-border bg-field px-3.5 py-1.5 text-[13px] font-semibold text-brand-600 transition-colors outline-none hover:border-brand-200 hover:bg-brand-50 focus-visible:ring-2 focus-visible:ring-outgoing-border"
              >
                <svg viewBox="0 0 20 20" fill="currentColor" className="h-3.5 w-3.5" aria-hidden="true">
                  <path d="M4 2.75a.75.75 0 0 1 .75.75v.4l1.4-.35a5.5 5.5 0 0 1 3.6.3 4 4 0 0 0 2.94.13l1.62-.58a.75.75 0 0 1 1 .7v6.9a.75.75 0 0 1-.5.71l-1.86.66a5.5 5.5 0 0 1-4.04-.18 4 4 0 0 0-2.62-.22l-1.54.39v4.89a.75.75 0 0 1-1.5 0V3.5A.75.75 0 0 1 4 2.75Z" />
                </svg>
                Report
              </button>
            )}
          </div>
        </div>

        {conversationReported && (
          // Confirmation after a report is sent. Neutral, not red -- nothing
          // has gone wrong; the user has been heard and review is pending.
          <div className="shrink-0 bg-chat px-5 pt-4">
            <p className="flex items-start gap-2.5 rounded-xl border border-field-border bg-field px-3.5 py-2.5 text-[13px] leading-snug text-slate-700 shadow-card">
              <span aria-hidden className="mt-0.5 text-slate-400">
                <svg viewBox="0 0 20 20" fill="currentColor" className="h-3.5 w-3.5">
                  <path
                    fillRule="evenodd"
                    d="M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm3.7-9.3a1 1 0 0 0-1.4-1.4L9 10.58 7.7 9.3a1 1 0 0 0-1.4 1.4l2 2a1 1 0 0 0 1.4 0l4-4Z"
                    clipRule="evenodd"
                  />
                </svg>
              </span>
              <span>
                <span className="font-semibold text-slate-900">Report sent.</span> Thanks for
                helping keep NUWA safer.
              </span>
            </p>
          </div>
        )}

        {conversationScores.length > 0 && (
          // Inline safety notice sitting ON the chat canvas below the header,
          // not a full-bleed strip pinned under it -- it reads as a card in the
          // conversation rather than something covering it.
          <div className="shrink-0 space-y-2 bg-chat px-5 pt-4">
            {conversationScores.map((s) => (
              <div
                key={s.id}
                className="flex items-start gap-2.5 rounded-xl border border-harm-border/50 bg-harm-bg px-3.5 py-2.5 shadow-card"
              >
                <span
                  aria-hidden
                  className="mt-1 h-2 w-2 shrink-0 rounded-full bg-harm-border ring-2 ring-harm-chip"
                />
                <div className="min-w-0">
                  <p className="text-[13px] leading-snug text-slate-700">
                    <span className="font-semibold capitalize text-slate-900">{s.label}</span> risk
                    detected
                    {s.confidence != null && (
                      <span className="text-slate-500">
                        {' '}
                        — confidence {Math.round(s.confidence * 100)}%
                      </span>
                    )}
                  </p>
                  {/* Model-correction affordance, deliberately quiet and scoped
                      to the alert itself: it only makes sense when NUWA has
                      actually flagged something. Never a top-level action. */}
                  {feedbackSent ? (
                    <p className="mt-1 text-[11px] text-slate-500">
                      Feedback sent. NUWA will use this to improve future detection.
                    </p>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setFeedbackOpen(true)}
                      className="mt-1 text-[11px] font-medium text-slate-500 underline decoration-slate-300 underline-offset-2 transition-colors outline-none hover:text-slate-800 focus-visible:text-slate-800"
                    >
                      Wrong detection? Give feedback
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto bg-chat px-5 py-4">
          {loading ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : error ? (
            <p className="text-sm text-red-600">{error}</p>
          ) : messages.length === 0 ? (
            <p className="text-sm text-slate-500">No messages yet. Say hi!</p>
          ) : (
            messages.map((m) => {
              const parent = m.reply_to ? parents.get(m.reply_to) : undefined
              return (
                <MessageBubble
                  key={m.id}
                  msg={m}
                  own={m.sender_id === user?.id}
                  onRetry={retry}
                  scores={messageScores.get(m.id)}
                  isEvidence={evidenceIds.has(m.id)}
                  isTarget={m.id === flashId}
                  parent={parent}
                  parentLabel={parent && labelFor(parent)}
                  // Only rendered messages can be scrolled to; a parent that
                  // was fetched by useReplyParents is quoted but not anchored.
                  parentOnScreen={Boolean(m.reply_to && messages.some((x) => x.id === m.reply_to))}
                  onReply={() => startReply(m.id)}
                  onJumpToParent={() => m.reply_to && jumpToParent(m.reply_to)}
                />
              )
            })
          )}
          <div ref={bottomRef} />
        </div>

        {/* Phone: in-flow pull-up sheet above the composer; md+ uses the side column. */}
        <div className="shrink-0 md:hidden">
          <button
            onClick={() => setAlertsOpen((o) => !o)}
            aria-expanded={alertsOpen}
            className={`flex w-full items-center justify-between border-t px-4 py-2.5 text-[13px] font-medium ${
              alertCount > 0
                ? 'border-slate-200/70 bg-amber-50/60 text-slate-700'
                : 'border-slate-200/70 bg-panel text-slate-600'
            }`}
          >
            <span>
              Safety alerts
              {alertCount > 0 && ` (${alertCount})`}
            </span>
            <span aria-hidden>{alertsOpen ? '▾' : '▴'}</span>
          </button>
          {alertsOpen && (
            <div className="max-h-[45dvh] overflow-y-auto border-t border-slate-200 bg-safety">
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

        {/* Chip and form share one panel surface so the pending reply reads as
            part of the composer rather than a floating notice above it. */}
        <div className="shrink-0 border-t border-slate-200/70 bg-panel">
          {replyingTo && (
            <div className="flex items-center gap-2 px-4 pt-3">
              <div className="flex min-w-0 flex-1 items-center gap-2 rounded-xl border border-field-border bg-field px-3 py-2 text-[13px]">
                <span aria-hidden className="shrink-0 text-slate-400">
                  ↩
                </span>
                <p className="min-w-0 truncate text-slate-600">
                  <span className="font-semibold text-slate-900">
                    Replying to {replyParent ? labelFor(replyParent) : '…'}
                  </span>
                  {replyParent?.content && <span> · {replyParent.content}</span>}
                </p>
                <button
                  type="button"
                  onClick={() => setReplyingTo(null)}
                  aria-label="Cancel reply"
                  className="ml-auto shrink-0 rounded-full p-1 text-slate-400 transition-colors outline-none hover:bg-slate-100 hover:text-slate-700 focus-visible:text-slate-700"
                >
                  <svg viewBox="0 0 20 20" fill="currentColor" className="h-3.5 w-3.5" aria-hidden="true">
                    <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
                  </svg>
                </button>
              </div>
            </div>
          )}
          <form onSubmit={handleSend} className="flex items-center gap-2 px-4 py-3">
            <input
              ref={inputRef}
              type="text"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              // Escape abandons the pending reply without clearing the draft --
              // the text you already typed is still worth sending.
              onKeyDown={(e) => {
                if (e.key === 'Escape' && replyingTo) {
                  e.preventDefault()
                  setReplyingTo(null)
                }
              }}
              placeholder={replyingTo ? 'Type a reply' : 'Type a message'}
              aria-label="Message"
              className="w-full min-w-0 rounded-full border border-slate-200 bg-slate-50 px-4 py-2.5 text-slate-900 transition-colors outline-none placeholder:text-slate-400 focus:border-field-focus focus:bg-ivory focus:shadow-field"
            />
            <button
              type="submit"
              disabled={!draft.trim()}
              className="shrink-0 rounded-full bg-gradient-to-br from-brand-600 to-brand-700 px-5 py-2.5 font-semibold text-white shadow-brand transition-all hover:brightness-110 disabled:opacity-40 disabled:shadow-none"
            >
              Send
            </button>
          </form>
        </div>
      </div>

      <ReportConversationDialog
        open={reportOpen}
        onClose={() => setReportOpen(false)}
        onSubmit={() => {
          // No network call yet -- see ReportConversationDialog's docstring.
          setReportOpen(false)
          setConversationReported(true)
        }}
      />

      <FeedbackDialog
        open={feedbackOpen}
        onClose={() => setFeedbackOpen(false)}
        onSubmit={() => {
          // No network call yet -- see FeedbackDialog's docstring.
          setFeedbackOpen(false)
          setFeedbackSent(true)
        }}
      />

      <aside className="hidden w-72 shrink-0 flex-col overflow-y-auto border-l border-slate-200/70 bg-safety md:flex lg:w-80">
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
