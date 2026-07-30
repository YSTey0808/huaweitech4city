import { NavLink } from 'react-router-dom'

// Far-left icon rail: the app's existing routes, nothing more. Each entry maps
// 1:1 to a route already registered in App.tsx -- no new destinations, no
// invented sections. Labels are shown on hover/focus via title + sr-only text
// so the rail stays narrow without losing accessibility.
const ITEMS = [
  {
    to: '/chat',
    label: 'Chats',
    // Speech bubble
    path: 'M3.5 5.75A2.25 2.25 0 0 1 5.75 3.5h8.5a2.25 2.25 0 0 1 2.25 2.25v5.5a2.25 2.25 0 0 1-2.25 2.25H8.6l-3.24 2.6a.75.75 0 0 1-1.22-.59v-2.06A2.25 2.25 0 0 1 3.5 11.25v-5.5Z',
  },
  {
    to: '/friends',
    label: 'Friends',
    // Two people
    path: 'M7.5 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM1.6 16.2a6 6 0 0 1 11.8 0 .75.75 0 0 1-.74.88H2.34a.75.75 0 0 1-.74-.88ZM14 10.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Zm4.4 6.58a.75.75 0 0 1-.74.88h-2.3a7.5 7.5 0 0 0-1.3-4.2 4.5 4.5 0 0 1 4.34 3.32Z',
  },
  {
    to: '/profile',
    label: 'Profile',
    // Person in circle
    path: 'M10 2a8 8 0 1 0 0 16 8 8 0 0 0 0-16Zm0 3.5a2.75 2.75 0 1 1 0 5.5 2.75 2.75 0 0 1 0-5.5Zm0 11a6.47 6.47 0 0 1-4.2-1.55c.53-1.6 2.2-2.7 4.2-2.7s3.67 1.1 4.2 2.7A6.47 6.47 0 0 1 10 16.5Z',
  },
] as const

export default function NavRail() {
  return (
    <nav
      aria-label="Main"
      className="hidden w-16 shrink-0 flex-col items-center gap-1 border-r border-slate-200/80 bg-panel py-4 md:flex"
    >
      <span
        aria-hidden
        className="mb-3 grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-brand-600 to-brand-700 text-sm font-bold text-white shadow-brand"
      >
        N
      </span>
      {ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          title={item.label}
          className={({ isActive }) =>
            `group relative grid h-10 w-10 place-items-center rounded-xl transition-colors ${
              isActive
                ? 'bg-brand-50 text-brand-700'
                : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
            }`
          }
        >
          {({ isActive }) => (
            <>
              {/* Active marker on the rail edge -- the reference's selected-nav cue. */}
              <span
                aria-hidden
                className={`absolute -left-2 h-5 w-1 rounded-r-full bg-brand-600 transition-opacity ${
                  isActive ? 'opacity-100' : 'opacity-0'
                }`}
              />
              <svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5" aria-hidden="true">
                <path fillRule="evenodd" d={item.path} clipRule="evenodd" />
              </svg>
              <span className="sr-only">{item.label}</span>
            </>
          )}
        </NavLink>
      ))}
    </nav>
  )
}
