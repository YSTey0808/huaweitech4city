export type InboxFilter = 'all' | 'flagged' | 'unread'

interface InboxFiltersProps {
  active: InboxFilter
  onChange: (f: InboxFilter) => void
  /** Counts are computed by the caller from the conversations it already has --
      never fetched, never invented. */
  counts: Record<InboxFilter, number>
}

// Second column: inbox categories. Deliberately limited to the three filters
// that can be derived from data the app already loads --
//   all      every visible conversation
//   flagged  useFlaggedConversations().flaggedIds
//   unread   the same lastMessageAt/lastReadAt comparison the list row uses
// The reference's other categories (assignment, teams, lifecycle stages) have
// no backing table here, so they are intentionally absent rather than mocked.
const FILTERS: { id: InboxFilter; label: string; dot?: string }[] = [
  { id: 'all', label: 'All chats' },
  { id: 'unread', label: 'Unread', dot: 'bg-brand-600' },
  { id: 'flagged', label: 'Flagged', dot: 'bg-harm-border' },
]

export default function InboxFilters({ active, onChange, counts }: InboxFiltersProps) {
  return (
    <div className="flex h-full flex-col gap-1 p-3">
      <p className="px-2 pb-1 pt-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
        Inbox
      </p>
      {FILTERS.map((f) => {
        const isActive = active === f.id
        return (
          <button
            key={f.id}
            type="button"
            onClick={() => onChange(f.id)}
            aria-pressed={isActive}
            className={`flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] transition-colors ${
              isActive
                ? 'bg-brand-50 font-semibold text-brand-800'
                : 'font-medium text-slate-600 hover:bg-slate-100'
            }`}
          >
            {f.dot ? (
              <span aria-hidden className={`h-1.5 w-1.5 shrink-0 rounded-full ${f.dot}`} />
            ) : (
              <span aria-hidden className="h-1.5 w-1.5 shrink-0" />
            )}
            <span className="min-w-0 flex-1 truncate">{f.label}</span>
            <span
              className={`shrink-0 text-[11px] tabular-nums ${
                isActive ? 'text-brand-700' : 'text-slate-400'
              }`}
            >
              {counts[f.id]}
            </span>
          </button>
        )
      })}
    </div>
  )
}
