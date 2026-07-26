import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { supabase } from '../lib/supabase'
import { USERNAME_RE, SG_PHONE_RE } from '../lib/validators'

export default function SignupPage() {
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  // Set when email confirmation is enabled and signup returns no session.
  const [confirmSent, setConfirmSent] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)

    const uname = username.trim()
    if (!USERNAME_RE.test(uname)) {
      setError('Username must be 3–20 characters: lowercase letters, numbers, and underscores.')
      return
    }

    const tel = phone.replace(/[\s-]/g, '')
    if (tel !== '' && !SG_PHONE_RE.test(tel)) {
      setError('Phone must be a Singapore number like +6591234567.')
      return
    }

    if (password !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }

    setPending(true)

    // Pre-check availability so a duplicate doesn't abort signup with an
    // opaque database error from the profile trigger.
    const { data: taken, error: rpcError } = await supabase.rpc('username_exists', {
      _username: uname,
    })
    if (rpcError) {
      setError(rpcError.message)
      setPending(false)
      return
    }
    if (taken) {
      setError('That username is already taken.')
      setPending(false)
      return
    }

    // The handle_new_user() DB trigger creates the profiles row from this
    // metadata (username, optional display-only phone).
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: { data: { username: uname, ...(tel ? { phone: tel } : {}) } },
    })
    if (error) {
      setError(error.message)
      setPending(false)
      return
    }
    // If a session came back, we're logged in and PublicOnlyRoute redirects to "/".
    // Otherwise email confirmation is on — show the check-your-email message.
    if (!data.session) {
      setConfirmSent(true)
      setPending(false)
    }
  }

  if (confirmSent) {
    return (
      <main className="min-h-screen flex items-center justify-center bg-slate-50 px-4 py-10">
        <div className="w-full max-w-sm text-center">
          <h1 className="text-2xl font-bold text-slate-900">Check your email</h1>
          <p className="mt-3 text-slate-600">
            We sent a confirmation link to <span className="font-medium">{email}</span>.
            Confirm it, then log in.
          </p>
          <Link
            to="/login"
            className="mt-6 inline-block rounded-md bg-emerald-600 px-4 py-2 font-medium text-white hover:bg-emerald-700"
          >
            Go to log in
          </Link>
        </div>
      </main>
    )
  }

  return (
    <main className="min-h-screen flex items-center justify-center bg-slate-50 px-4 py-10">
      <div className="w-full max-w-sm">
        <h1 className="text-2xl font-bold text-slate-900">Sign up</h1>
        <p className="mt-1 text-sm text-slate-500">Create your Harm-Detection Chat account.</p>

        <form onSubmit={handleSubmit} className="mt-6 space-y-4">
          <div>
            <label htmlFor="username" className="block text-sm font-medium text-slate-700">
              Username
            </label>
            <input
              id="username"
              type="text"
              autoComplete="username"
              required
              maxLength={20}
              value={username}
              onChange={(e) => setUsername(e.target.value.toLowerCase())}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-slate-900 outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
            />
          </div>

          <div>
            <label htmlFor="email" className="block text-sm font-medium text-slate-700">
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-slate-900 outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
            />
          </div>

          <div>
            <label htmlFor="phone" className="block text-sm font-medium text-slate-700">
              Phone (optional)
            </label>
            <input
              id="phone"
              type="tel"
              autoComplete="tel"
              placeholder="+6591234567"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-slate-900 outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
            />
            <p className="mt-1 text-xs text-slate-500">Singapore number, display only.</p>
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium text-slate-700">
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="new-password"
              required
              minLength={6}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-slate-900 outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
            />
          </div>

          <div>
            <label htmlFor="confirmPassword" className="block text-sm font-medium text-slate-700">
              Confirm password
            </label>
            <input
              id="confirmPassword"
              type="password"
              autoComplete="new-password"
              required
              minLength={6}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-slate-900 outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
            />
          </div>

          {error && <p className="text-sm text-red-600">{error}</p>}

          <button
            type="submit"
            disabled={pending}
            className="w-full rounded-md bg-emerald-600 px-4 py-2 font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            {pending ? 'Creating account…' : 'Sign up'}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-slate-600">
          Already have an account?{' '}
          <Link to="/login" className="font-medium text-emerald-700 hover:underline">
            Log in
          </Link>
        </p>
      </div>
    </main>
  )
}
