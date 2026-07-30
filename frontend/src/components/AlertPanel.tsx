import RiskBadge from './RiskBadge'
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

// One definition for all three render states (error / loading / loaded) --
// previously the loaded state's heading had drifted out of sync with the
// other two.
//
// The Nuwa mark is a small red node: a solid dot inside a soft ring, drawn
// with plain divs (no icon dependency). `status` swaps only the sub-line and
// the dot's pulse, so the identity block stays identical across states.
function PanelHeading({ status }: { status?: string }) {
  return (
    <div>
      <div className="flex items-center gap-1.5">
        <span
          aria-hidden
          className="relative grid h-3.5 w-3.5 shrink-0 place-items-center rounded-full bg-harm-bg ring-1 ring-harm-border/40"
        >
          <span className="nuwa-pulse h-1.5 w-1.5 rounded-full bg-harm-border" />
        </span>
        <span className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
          Nuwa
        </span>
      </div>
      <h2 className="mt-2 text-base font-semibold tracking-tight text-slate-900">
        Safety alerts
      </h2>
      {status && <p className="mt-1 text-[11px] leading-snug text-slate-500">{status}</p>}
    </div>
  )
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
      <div className="flex flex-col gap-4 p-5">
        <PanelHeading />
        <p className="text-sm text-red-600">Couldn't load safety alerts. Refresh to try again.</p>
      </div>
    )
  }
  if (loading) {
    return (
      <div className="flex flex-col gap-4 p-5">
        <PanelHeading status="Checking this conversation…" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-5 p-5">
      <PanelHeading status="Monitoring conversation patterns in real time" />

      {empty && (
        <div className="rounded-xl border border-slate-200/70 bg-ivory px-4 py-6 text-center">
          <p className="text-[13px] font-medium text-slate-600">No alerts for this chat.</p>
        </div>
      )}

      {conversationScores.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-[11px] font-semibold tracking-wider text-slate-500 uppercase">
            Conversation
          </h3>
          {conversationScores.map((s) => (
            // White card with a red left stripe rather than a red-wash box:
            // the severity still reads instantly, but the panel stays calm.
            <div
              key={s.id}
              className="overflow-hidden rounded-xl border border-slate-200/70 bg-ivory shadow-card"
            >
              <div className="border-l-[3px] border-harm-border px-3.5 py-3">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
                  <span className="text-sm font-semibold capitalize text-harm-text">
                    {s.label}
                  </span>
                  {s.confidence != null && (
                    <span className="text-[11px] font-medium tabular-nums text-slate-400">
                      {percent(s.confidence)}
                    </span>
                  )}
                  {/* Severity/source read as quiet metadata beside the title --
                      the red left stripe already carries the alert weight, so
                      repeating it in a filled chip just doubles the shouting. */}
                  {s.severity && (
                    <span className="text-[11px] uppercase tracking-wide text-slate-400">
                      {s.severity}
                    </span>
                  )}
                  {s.source === 'user_report' && (
                    <span className="text-[11px] uppercase tracking-wide text-slate-300">
                      reported
                    </span>
                  )}
                </div>
                {s.reasoning && (
                  <p className="mt-3 rounded-lg border border-slate-200/60 bg-safety/60 px-2.5 py-2 text-xs leading-[1.65] text-slate-700">
                    {s.reasoning}
                  </p>
                )}
                <p className="mt-2.5 text-[11px] text-slate-500">
                  {s.evidence_msg_ids?.length ?? 0} evidence message(s)
                </p>
              </div>
            </div>
          ))}
        </section>
      )}

      {flaggedEntries.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-[11px] font-semibold tracking-wider text-slate-500 uppercase">
            Flagged messages
          </h3>
          {flaggedEntries.map(([msgId, scores]) => {
            const content = messages.find((m) => m.id === msgId)?.content
            return (
              <div
                key={msgId}
                className="overflow-hidden rounded-xl border border-slate-200/70 bg-ivory shadow-card"
              >
                <div className="border-l-[3px] border-harm-border/50 px-3.5 py-3">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    {scores.map((s) => (
                      <RiskBadge
                        key={s.id}
                        label={s.label}
                        confidence={s.confidence}
                        source={s.source}
                      />
                    ))}
                  </div>
                  {/* line-clamp-2 rather than truncate: the same backend text,
                      just readable over two lines instead of clipped at one. */}
                  <p className="mt-2.5 line-clamp-2 text-xs leading-[1.65] text-slate-600">
                    {content ?? '(message not loaded)'}
                  </p>
                </div>
              </div>
            )
          })}
        </section>
      )}
    </div>
  )
}
