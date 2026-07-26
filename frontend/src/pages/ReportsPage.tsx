import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useReports } from '../hooks/useReports'
import type { FlaggedMessage } from '../hooks/useReports'
import { useConversations } from '../hooks/useConversations'
import Avatar from '../components/Avatar'

// One display row per score row — message and conversation scores normalized
// into a common shape so filtering/grouping/sorting treat them uniformly.
interface ReportEntry {
  key: string
  conversationId: string
  label: string | null
  confidence: number | null
  createdAt: string
  kind: 'message' | 'conversation'
  texts: FlaggedMessage[]
  targetMsgId: string | null
}

function EntryRow({ entry, onOpen }: { entry: ReportEntry; onOpen: (e: ReportEntry) => void }) {
  const badge =
    entry.kind === 'message' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-800'
  return (
    <button
      onClick={() => onOpen(entry)}
      className="w-full rounded-md border border-slate-200 bg-white p-3 text-left hover:bg-slate-50 md:grid md:grid-cols-[8rem_minmax(0,1fr)_auto] md:items-center md:gap-3"
    >
      <span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium capitalize ${badge}`}>
          {entry.label ?? 'flagged'}
          {entry.confidence != null && <> · {Math.round(entry.confidence * 100)}%</>}
        </span>
      </span>
      <span className="mt-1 block min-w-0 md:mt-0">
        {entry.texts.length === 0 ? (
          <span className="block text-xs text-slate-400 italic">(messages unavailable)</span>
        ) : (
          entry.texts.map((m) => (
            <span key={m.id} className="block truncate text-xs text-slate-600">
              {m.content ?? '(message unavailable)'}
            </span>
          ))
        )}
      </span>
      <time className="mt-1 block text-[11px] text-slate-400 md:mt-0">
        {new Date(entry.createdAt).toLocaleString()}
      </time>
    </button>
  )
}

export default function ReportsPage() {
  const navigate = useNavigate()
  const { messageReports, conversationReports, loading, error } = useReports()
  const { conversations } = useConversations()
  const [filter, setFilter] = useState<string | null>(null)

  const friendByConversation = useMemo(
    () => new Map(conversations.map((c) => [c.conversationId, c.friend])),
    [conversations],
  )

  const entries = useMemo<ReportEntry[]>(
    () => [
      ...messageReports.map(({ score, message }) => ({
        key: score.id,
        conversationId: message.conversation_id,
        label: score.label,
        confidence: score.confidence,
        createdAt: score.created_at,
        kind: 'message' as const,
        texts: [message],
        targetMsgId: score.msg_id,
      })),
      ...conversationReports.map(({ score, evidence }) => ({
        key: score.id,
        conversationId: score.conversation_id,
        label: score.label,
        confidence: score.confidence,
        createdAt: score.created_at,
        kind: 'conversation' as const,
        texts: evidence,
        targetMsgId: score.evidence_msg_ids?.[0] ?? null,
      })),
    ],
    [messageReports, conversationReports],
  )

  // Labels are open-ended strings per the model contract — chips are derived
  // from the data, never hardcoded.
  const labels = useMemo(
    () => [...new Set(entries.flatMap((e) => (e.label ? [e.label] : [])))].sort(),
    [entries],
  )

  const filtered = useMemo(
    () => (filter ? entries.filter((e) => e.label === filter) : entries),
    [entries, filter],
  )

  // Group by conversation, newest entry first within a group; groups ordered
  // by their newest entry.
  const groups = useMemo(() => {
    const byConversation = new Map<string, ReportEntry[]>()
    for (const e of filtered) {
      const bucket = byConversation.get(e.conversationId) ?? []
      bucket.push(e)
      byConversation.set(e.conversationId, bucket)
    }
    for (const bucket of byConversation.values()) {
      bucket.sort((a, b) => b.createdAt.localeCompare(a.createdAt))
    }
    return [...byConversation.entries()].sort(([, a], [, b]) =>
      b[0].createdAt.localeCompare(a[0].createdAt),
    )
  }, [filtered])

  function openEntry(entry: ReportEntry) {
    navigate(
      entry.targetMsgId
        ? `/chat/${entry.conversationId}?msg=${entry.targetMsgId}`
        : `/chat/${entry.conversationId}`,
    )
  }

  const alertCount = filtered.length
  const conversationCount = groups.length

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-6">
      <h1 className="text-lg font-semibold text-slate-900">Safety reports</h1>

      {loading ? (
        <p className="mt-2 text-sm text-slate-500">Loading reports…</p>
      ) : error ? (
        <p className="mt-2 text-sm text-red-600">{error}</p>
      ) : entries.length === 0 ? (
        <p className="mt-2 text-sm text-slate-500">No alerts. Flagged activity will appear here.</p>
      ) : (
        <>
          <p className="mt-1 text-sm text-slate-500">
            {alertCount} alert{alertCount === 1 ? '' : 's'} across {conversationCount} conversation
            {conversationCount === 1 ? '' : 's'}
          </p>

          <div className="mt-3 flex flex-wrap gap-2">
            {[null, ...labels].map((label) => {
              const active = filter === label
              return (
                <button
                  key={label ?? 'all'}
                  onClick={() => setFilter(label)}
                  className={`rounded-full px-3 py-1 text-xs font-medium capitalize ${
                    active
                      ? 'bg-emerald-600 text-white'
                      : 'border border-slate-300 text-slate-700 hover:bg-slate-100'
                  }`}
                >
                  {label ?? 'All'}
                </button>
              )
            })}
          </div>

          <div className="mt-4 space-y-6">
            {groups.map(([conversationId, groupEntries]) => {
              const friend = friendByConversation.get(conversationId)
              return (
                <section key={conversationId}>
                  <div className="mb-2 flex items-center gap-2">
                    <Avatar
                      size="sm"
                      name={friend?.display_name ?? friend?.username}
                      color={friend?.avatar_color}
                    />
                    <p className="min-w-0 truncate text-sm font-medium text-slate-900">
                      {friend?.display_name ?? friend?.username ?? 'Unknown conversation'}
                    </p>
                  </div>
                  <div className="space-y-2">
                    {groupEntries.map((entry) => (
                      <EntryRow key={entry.key} entry={entry} onOpen={openEntry} />
                    ))}
                  </div>
                </section>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
