import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { Session, User } from '@supabase/supabase-js'
import { supabase } from '../lib/supabase'
import type { Profile } from '../types/db'

interface AuthContextValue {
  session: Session | null
  user: User | null
  /** True until the initial getSession() resolves — guards use it to avoid redirect flicker. */
  loading: boolean
  /** Own profiles row; null until fetched (UI falls back to email / '?'). */
  profile: Profile | null
  /** Lets ProfilePage push a saved row into context so the header updates live. */
  setProfile: (profile: Profile | null) => void
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)
  const [profile, setProfile] = useState<Profile | null>(null)

  useEffect(() => {
    // Restore any persisted session on first load. On error the session is
    // null and ProtectedRoute sends the user to /login — the right fallback.
    supabase.auth.getSession().then(({ data, error }) => {
      if (error) console.warn('getSession failed:', error.message)
      setSession(data.session)
      setLoading(false)
    })

    // Keep state in sync on login / logout / token refresh.
    const { data: sub } = supabase.auth.onAuthStateChange((_event, newSession) => {
      setSession(newSession)
    })

    return () => sub.subscription.unsubscribe()
  }, [])

  const userId = session?.user?.id ?? null

  useEffect(() => {
    if (!userId) {
      setProfile(null)
      return
    }
    let cancelled = false
    supabase
      .from('profiles')
      .select('*')
      .eq('id', userId)
      .single()
      .then(({ data, error }) => {
        // On error leave profile null — the header falls back to the email.
        if (error) console.warn('profile load failed:', error.message)
        if (!cancelled && data) setProfile(data)
      })
    return () => {
      cancelled = true
    }
  }, [userId])

  return (
    <AuthContext.Provider
      value={{ session, user: session?.user ?? null, loading, profile, setProfile }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider')
  return ctx
}
