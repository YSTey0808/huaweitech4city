import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'

interface FeedbackDialogProps {
  open: boolean
  onClose: () => void
  /** Called with the required explanation of what NUWA got wrong. */
  onSubmit: (reason: string) => void
}

// "Tell NUWA what was wrong" -- corrects a WRONG detection. Deliberately
// separate from ReportConversationDialog: reporting is a safety action about
// the other person, feedback is a correction about the model. Reached only
// from the safety alert (see ChatPane), never as a top-level chat action.
//
// UI ONLY: no network call yet. The existing per-message dispute endpoint
// (claim='safe' in useMessageReport) is the natural backend for this, but it
// is keyed on msg_id and this feedback is conversation-level.
export default function FeedbackDialog({ open, onClose, onSubmit }: FeedbackDialogProps) {
  const [reason, setReason] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (!open) return
    setReason('')
    const t = setTimeout(() => textareaRef.current?.focus(), 0)
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

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const trimmed = reason.trim()
    if (!trimmed) return
    onSubmit(trimmed)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="feedback-dialog-title"
    >
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-slate-900/20 backdrop-blur-[2px]"
      />

      {/* max-w-xs, not max-w-sm: this is the lighter of the two dialogs. */}
      <form
        onSubmit={handleSubmit}
        className="relative w-full max-w-xs rounded-2xl border border-field-border bg-field p-5 shadow-panel"
      >
        <h2
          id="feedback-dialog-title"
          className="text-[15px] font-semibold tracking-tight text-slate-900"
        >
          Tell NUWA what was wrong
        </h2>

        <label htmlFor="feedback-reason" className="mt-3 block text-[13px] font-medium text-slate-700">
          Why was this wrong?
        </label>
        <textarea
          id="feedback-reason"
          ref={textareaRef}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={3}
          maxLength={500}
          required
          placeholder="This conversation is normal because…"
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
          {/* Neutral dark, not brand red -- correcting the model is not a
              safety action and shouldn't carry the same visual weight. */}
          <button
            type="submit"
            disabled={!reason.trim()}
            className="rounded-xl bg-slate-800 px-4 py-2 text-sm font-bold text-white transition-all hover:bg-slate-900 disabled:opacity-40"
          >
            Send feedback
          </button>
        </div>
      </form>
    </div>
  )
}
