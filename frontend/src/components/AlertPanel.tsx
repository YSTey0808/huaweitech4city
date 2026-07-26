import type { ChatMessage } from '../hooks/useMessages'
import type { ConversationScore, MessageScore } from '../types/db'

interface AlertPanelProps {
  conversationScores: ConversationScore[]
  messageScores: Map<string, MessageScore[]>
  messages: ChatMessage[]
  loading?: boolean
  error?: string | null
}

function percent(confidence: number | null): string | null {
  return confidence == null ? null : `${Math.round(confidence * 100)}%`
}

// Alert detail for the open conversation — desktop right column and phone
// pull-up sheet render this same component. Shows contract fields
// (label, confidence, evidence_msg_ids) plus the real model's severity +
// reasoning (see supabase/migrations/007_add_llm_reasoning_fields.sql).
export default function AlertPanel({
  conversationScores,
  messageScores,
  messages,
  loading,
  error,
}: AlertPanelProps) {
  const flaggedEntries = [...messageScores.entries()]
  const empty = conversationScores.length === 0 && flaggedEntries.length === 0

  // A fetch failure must not fall through to the reassuring "No alerts" text.
  if (error) {
    return (
      <div className="flex flex-col gap-4 p-4">
        <h2 className="text-sm font-semibold text-slate-900">Safety alerts</h2>
        <p className="text-sm text-red-600">Couldn't load safety alerts. Refresh to try again.</p>
      </div>
    )
  }
  if (loading) {
    return (
      <div className="flex flex-col gap-4 p-4">
        <h2 className="text-sm font-semibold text-slate-900">Safety alerts</h2>
        <p className="text-sm text-slate-500">Checking for alerts…</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <h2 className="text-sm font-semibold text-slate-900">Safety alerts</h2>

      {empty && <p className="text-sm text-slate-500">No alerts for this chat.</p>}

      {conversationScores.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-xs font-medium tracking-wide text-slate-500 uppercase">Conversation</h3>
          {conversationScores.map((s) => (
            <div key={s.id} className="rounded-md border border-red-200 bg-red-50 p-3">
              <p className="text-sm text-red-800">
                <span className="font-medium capitalize">{s.label}</span>
                {s.confidence != null && <> — {percent(s.confidence)}</>}
                {s.severity && (
                  <span className="ml-2 rounded bg-red-200 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-red-900">
                    {s.severity}
                  </span>
                )}
              </p>
              {s.reasoning && <p className="mt-1 text-xs text-red-800">{s.reasoning}</p>}
              <p className="mt-1 text-xs text-red-700">
                {s.evidence_msg_ids?.length ?? 0} evidence message(s)
              </p>
            </div>
          ))}
        </section>
      )}

      {flaggedEntries.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-xs font-medium tracking-wide text-slate-500 uppercase">
            Flagged messages
          </h3>
          {flaggedEntries.map(([msgId, scores]) => {
            const content = messages.find((m) => m.id === msgId)?.content
            return (
              <div key={msgId} className="rounded-md border border-slate-200 bg-white p-3">
                <div className="flex flex-wrap gap-1">
                  {scores.map((s) => (
                    <span
                      key={s.id}
                      className="rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-medium text-red-700 capitalize"
                    >
                      {s.label}
                      {s.confidence != null && <> · {percent(s.confidence)}</>}
                    </span>
                  ))}
                </div>
                <p className="mt-1 truncate text-xs text-slate-600">
                  {content ?? '(message not loaded)'}
                </p>
              </div>
            )
          })}
        </section>
      )}
    </div>
  )
}
