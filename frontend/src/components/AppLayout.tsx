import { useState } from 'react'
import { Link, NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { supabase } from '../lib/supabase'
import Avatar from './Avatar'

// Nav pill styling lives here so the three links stay identical; NavLink gives
// us the active state the old plain Links couldn't express.
function navClass({ isActive }: { isActive: boolean }): string {
  return `rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
    isActive
      ? 'bg-brand-50 text-brand-700'
      : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
  }`
}

// App shell for authenticated routes: header with the signed-in email + logout.
// On sign-out the auth listener clears the session and ProtectedRoute redirects.
export default function AppLayout() {
  const { user, profile } = useAuth()
  const [signingOut, setSigningOut] = useState(false)
  const [logoutError, setLogoutError] = useState<string | null>(null)

  async function handleLogout() {
    setSigningOut(true)
    setLogoutError(null)
    const { error } = await supabase.auth.signOut()
    if (error) {
      // Recover the button — otherwise it sticks on "Logging out…" forever.
      setSigningOut(false)
      setLogoutError("Couldn't log out. Check your connection and try again.")
    }
    // On success no manual navigation is needed — the auth state change triggers the redirect.
  }

  return (
    // h-dvh + overflow-y-auto on <main>: pages scroll inside the shell, so
    // full-height views (chat) can size panes with h-full instead of calc().
    <div className="flex h-dvh flex-col bg-canvas">
      <header className="shrink-0 border-b border-slate-200/80 bg-ivory/90 backdrop-blur">
        <div className="mx-auto flex w-full max-w-[min(94vw,1920px)] items-center justify-between gap-3 px-4 py-3">
          <div className="flex min-w-0 items-center gap-2 sm:gap-4">
            {/* Wordmark links home to the messaging page. The md+ nav rail
                (see NavRail) carries the same destinations, so the small mark
                is hidden there to avoid showing the brand twice; below md the
                rail isn't rendered and the header is the only navigation. */}
            <Link
              to="/chat"
              aria-label="Nuwa home"
              className="flex min-w-0 items-center gap-2 rounded-lg px-1 py-0.5 transition-opacity hover:opacity-80"
            >
              <span
                aria-hidden
                className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-brand-600 to-brand-700 text-[13px] font-bold text-white shadow-brand md:hidden"
              >
                N
              </span>
              <span className="hidden truncate font-bold tracking-[0.18em] text-brand-600 sm:inline">
                NUWA
              </span>
            </Link>
            <nav className="flex items-center gap-1 md:hidden">
              <NavLink to="/chat" className={navClass}>
                Chats
              </NavLink>
              <NavLink to="/friends" className={navClass}>
                Friends
              </NavLink>
            </nav>
          </div>
          <div className="flex items-center gap-2 sm:gap-3">
            <Link
              to="/profile"
              className="flex min-w-0 items-center gap-2 rounded-lg px-1.5 py-1 transition-colors hover:bg-slate-100"
            >
              <Avatar
                size="sm"
                name={profile?.display_name ?? profile?.username ?? user?.email}
                color={profile?.avatar_color}
              />
              <span className="hidden truncate text-sm font-medium text-slate-700 sm:inline">
                {profile?.display_name ?? user?.email}
              </span>
            </Link>
            <button
              onClick={handleLogout}
              disabled={signingOut}
              className="rounded-lg border border-slate-200 bg-panel px-3 py-1.5 text-sm font-medium text-slate-600 shadow-card transition-colors hover:bg-slate-50 hover:text-slate-900 disabled:opacity-50"
            >
              {signingOut ? 'Logging out…' : 'Logout'}
            </button>
          </div>
        </div>
        {logoutError && (
          <p className="border-t border-red-200 bg-red-50 px-4 py-1.5 text-sm text-red-700">
            {logoutError}
          </p>
        )}
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  )
}
