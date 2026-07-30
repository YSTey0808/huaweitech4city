// Shared visual treatment for the backend's risk labels, scores and severity.
// Purely presentational: every value shown is passed straight through from the
// score row (label / confidence / severity / source) -- this component never
// renames, thresholds, re-maps or supplies a value of its own. The one piece of
// formatting it owns is turning a 0-1 confidence into a percentage string,
// which is what the panel already did inline.
//
// Exists because the same badge markup had drifted into four slightly
// different variants across AlertPanel and ChatPane; a single component keeps
// them identical and makes the "calm status, not moderation output" styling a
// one-line change.

interface RiskBadgeProps {
  /** Nullable to match the score tables. Null renders no pill (the previous
      inline markup rendered an empty one) -- the score still shows. */
  label: string | null
  confidence?: number | null
  severity?: string | null
  /** Score row's `source` column -- 'user_report' renders a quiet "reported" mark. */
  source?: string | null
  /** `sm` for inline use under a chat bubble, `md` for the alerts panel. */
  size?: 'sm' | 'md'
  /**
   * Which score table the row came from -- red for message_scores, amber for
   * conversation_scores. Preserves the existing distinction on the reports
   * list; it is not a severity judgement.
   */
  tone?: 'red' | 'amber'
}

const TONE = {
  red: 'bg-harm-chip-bg text-harm-chip-text border-harm-chip-border',
  amber: 'bg-amber-50 text-amber-800 border-amber-200/80',
} as const

// Dimmed companion to TONE for the score inside the pill -- keeps it clearly
// secondary to the label. Deliberately independent of the value: the styling
// never changes with the number, so a 0% and a 100% badge look identical apart
// from the digits, and a low score can't read as louder than it is.
const SCORE_TONE = {
  red: 'text-harm-score',
  amber: 'text-amber-700/80',
} as const

function percent(confidence: number): string {
  return `${Math.round(confidence * 100)}%`
}

export default function RiskBadge({
  label,
  confidence,
  severity,
  source,
  size = 'md',
  tone = 'red',
}: RiskBadgeProps) {
  const pill = size === 'sm' ? 'px-2 py-[3px] text-[11px]' : 'px-2 py-[3px] text-[12px]'
  const meta = size === 'sm' ? 'text-[10px]' : 'text-[10.5px]'

  return (
    <span className="inline-flex items-center gap-1.5 align-middle">
      {/* Label + score share one pill. The score stays visually secondary via a
          lighter weight and a dimmed variant of the pill's own colour, rather
          than by sitting outside it. */}
      {(label || confidence != null) && (
        <span
          className={`inline-flex items-center gap-1 rounded-full border font-semibold ${TONE[tone]} ${pill}`}
        >
          {label && <span className="capitalize">{label}</span>}
          {confidence != null && (
            <span className={`font-normal tabular-nums ${SCORE_TONE[tone]}`}>
              {percent(confidence)}
            </span>
          )}
        </span>
      )}
      {severity && (
        <span className={`uppercase tracking-wide text-slate-400 ${meta}`}>{severity}</span>
      )}
      {source === 'user_report' && (
        <span className={`uppercase tracking-wide text-slate-300 ${meta}`}>reported</span>
      )}
    </span>
  )
}
