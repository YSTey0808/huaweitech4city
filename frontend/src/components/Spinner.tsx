// Minimal full-screen loading indicator shown while the initial session resolves.
export default function Spinner() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <div
        className="h-8 w-8 animate-spin rounded-full border-2 border-slate-300 border-t-emerald-600"
        role="status"
        aria-label="Loading"
      />
    </div>
  )
}
