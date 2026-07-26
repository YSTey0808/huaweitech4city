import { useState } from 'react'
import { Link, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { supabase } from '../lib/supabase'
import Avatar from './Avatar'

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
    <div className="flex h-dvh flex-col bg-slate-50">
      <header className="shrink-0 border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-4xl items-center justify-between gap-3 px-4 py-3">
          <div className="flex min-w-0 items-center gap-4">
            <span className="truncate font-semibold text-slate-900">Harm-Detection Chat</span>
            <Link to="/chat" className="text-sm font-medium text-slate-700 hover:text-slate-900">
              Chats
            </Link>
            <Link to="/friends" className="text-sm font-medium text-slate-700 hover:text-slate-900">
              Friends
            </Link>
            <Link to="/reports" className="text-sm font-medium text-slate-700 hover:text-slate-900">
              Reports
            </Link>
          </div>
          <div className="flex items-center gap-3">
            <Link to="/profile" className="flex min-w-0 items-center gap-2 hover:opacity-80">
              <Avatar
                size="sm"
                name={profile?.display_name ?? profile?.username ?? user?.email}
                color={profile?.avatar_color}
              />
              <span className="hidden truncate text-sm text-slate-700 sm:inline">
                {profile?.display_name ?? user?.email}
              </span>
            </Link>
            <button
              onClick={handleLogout}
              disabled={signingOut}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50"
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
