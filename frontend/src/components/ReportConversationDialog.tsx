import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'

export type ReportCategory = 'scam' | 'grooming' | 'cyberbullying'

interface ReportConversationDialogProps {
  open: boolean
  onClose: () => void
  /** Called with the chosen category and the required details text. */
  onSubmit: (category: ReportCategory, details: string) => void
}

const CATEGORIES: { id: ReportCategory; label: string }[] = [
  { id: 'scam', label: 'Scam' },
  { id: 'grooming', label: 'Grooming' },
  { id: 'cyberbullying', label: 'Cyberbullying' },
]

// "Report this conversation as unsafe" -- the user-facing safety action.
// Distinct from FeedbackDialog, which corrects a wrong NUWA detection.
//
// UI ONLY: collects the report and hands it to onSubmit. No network call --
// conversation-level reporting has no backend contract yet (message_reports
// .msg_id is NOT NULL and /report requires a msg_id, so a conversation report
// has nothing to send). Wiring this up is a follow-up.
export default function ReportConversationDialog({
  open,
  onClose,
  onSubmit,
}: ReportConversationDialogProps) {
  const [category, setCategory] = useState<ReportCategory | null>(null)
  const [details, setDetails] = useState('')
  const firstFieldRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    setCategory(null)
    setDetails('')
    const t = setTimeout(() => firstFieldRef.current?.focus(), 0)
    return () => clearTimeout(t)
  }, [open])

  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  // Both the category and the details are required -- a bare category gives a
  // reviewer (and later the model) almost nothing to work with.
  const canSubmit = category !== null && details.trim().length > 0

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!canSubmit) return
    onSubmit(category, details.trim())
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="report-dialog-title"
    >
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-slate-900/20 backdrop-blur-[2px]"
      />

      <form
        onSubmit={handleSubmit}
        className="relative w-full max-w-sm rounded-2xl border border-field-border bg-field p-5 shadow-panel"
      >
        <h2 id="report-dialog-title" className="text-base font-semibold tracking-tight text-slate-900">
          Report conversation
        </h2>
        <p className="mt-1 text-[13px] leading-snug text-slate-600">
          Tell NUWA why this conversation feels unsafe.
        </p>

        <fieldset className="mt-4">
          <legend className="text-[13px] font-medium text-slate-700">What's happening?</legend>
          <div className="mt-2 flex flex-wrap gap-2">
            {CATEGORIES.map((c, i) => {
              const active = category === c.id
              return (
                <button
                  key={c.id}
                  ref={i === 0 ? firstFieldRef : undefined}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setCategory(c.id)}
                  className={`rounded-full border px-3.5 py-1.5 text-[13px] font-semibold transition-colors outline-none focus-visible:ring-2 focus-visible:ring-outgoing-border ${
                    active
                      ? 'border-brand-200 bg-brand-50 text-brand-700'
                      : 'border-field-border bg-ivory text-slate-600 hover:bg-slate-50'
                  }`}
                >
                  {c.label}
                </button>
              )
            })}
          </div>
        </fieldset>

        <label htmlFor="report-details" className="mt-4 block text-[13px] font-medium text-slate-700">
          Add more details
        </label>
        <textarea
          id="report-details"
          value={details}
          onChange={(e) => setDetails(e.target.value)}
          rows={3}
          maxLength={500}
          required
          placeholder="What happened in this conversation?"
          className="mt-1.5 w-full resize-none rounded-xl border border-field-border bg-ivory px-3.5 py-2.5 text-sm text-slate-900 outline-none transition-colors placeholder:text-slate-400 focus:border-field-focus focus:shadow-field"
        />

        <div className="mt-4 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-field-border bg-field px-4 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={!canSubmit}
            className="rounded-xl bg-brand-600 px-4 py-2 text-sm font-bold text-white shadow-brand transition-all hover:brightness-110 disabled:opacity-40 disabled:shadow-none"
          >
            Send report
          </button>
        </div>
      </form>
    </div>
  )
}
