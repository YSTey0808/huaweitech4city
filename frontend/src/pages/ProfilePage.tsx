import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { supabase } from '../lib/supabase'
import { useAuth } from '../context/AuthContext'
import Avatar from '../components/Avatar'
import { USERNAME_RE, SG_PHONE_RE } from '../lib/validators'

// All dark enough for white initials; first entry is the DB signup default.
const SWATCHES = [
  { hex: '#64748b', label: 'Slate' },
  { hex: '#dc2626', label: 'Red' },
  { hex: '#ea580c', label: 'Orange' },
  { hex: '#d97706', label: 'Amber' },
  { hex: '#65a30d', label: 'Lime' },
  { hex: '#16a34a', label: 'Green' },
  { hex: '#059669', label: 'Emerald' },
  { hex: '#0d9488', label: 'Teal' },
  { hex: '#0891b2', label: 'Cyan' },
  { hex: '#0284c7', label: 'Sky' },
  { hex: '#2563eb', label: 'Blue' },
  { hex: '#4f46e5', label: 'Indigo' },
  { hex: '#7c3aed', label: 'Violet' },
  { hex: '#9333ea', label: 'Purple' },
  { hex: '#c026d3', label: 'Fuchsia' },
  { hex: '#db2777', label: 'Pink' },
]

const BIO_MAX = 160

const inputCls =
  'mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-slate-900 outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500'
const labelCls = 'block text-sm font-medium text-slate-700'
const buttonCls =
  'w-full rounded-md bg-emerald-600 px-4 py-2 font-medium text-white hover:bg-emerald-700 disabled:opacity-50'

export default function ProfilePage() {
  const { user, profile, setProfile } = useAuth()

  // Profile details form
  const [displayName, setDisplayName] = useState('')
  const [username, setUsername] = useState('')
  const [phone, setPhone] = useState('')
  const [bio, setBio] = useState('')
  const [color, setColor] = useState('#64748b')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const [saved, setSaved] = useState(false)

  // Change password form (independent state so one form's errors never
  // bleed into the other)
  const [currentPw, setCurrentPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [pwError, setPwError] = useState<string | null>(null)
  const [pwPending, setPwPending] = useState(false)
  const [pwSaved, setPwSaved] = useState(false)

  // Profile may arrive after mount (context fetches it async).
  useEffect(() => {
    if (profile) {
      setDisplayName(profile.display_name ?? '')
      setUsername(profile.username ?? '')
      setPhone(profile.phone ?? '')
      setBio(profile.bio ?? '')
      setColor(profile.avatar_color ?? '#64748b')
    }
  }, [profile])

  function touch() {
    setSaved(false)
    setError(null)
  }

  const isCustomColor = !SWATCHES.some((s) => s.hex === color)

  // Hide password change for SSO-only accounts (none exist today, but this
  // keeps the section correct if OAuth providers are added later).
  const hasPasswordLogin = user?.identities?.some((i) => i.provider === 'email') ?? false

  const memberSince = profile?.created_at
    ? new Date(profile.created_at).toLocaleDateString(undefined, {
        month: 'long',
        year: 'numeric',
      })
    : null

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!user) return
    setError(null)
    setSaved(false)

    const trimmedName = displayName.trim()
    if (!trimmedName) {
      setError('Display name cannot be empty.')
      return
    }

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

    const trimmedBio = bio.trim()

    setPending(true)

    // Pre-check availability when the username changed, for a friendly
    // error before hitting the unique index.
    if (uname !== profile?.username) {
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
    }

    const { data, error } = await supabase
      .from('profiles')
      .update({
        display_name: trimmedName,
        username: uname,
        phone: tel || null,
        bio: trimmedBio || null,
        avatar_color: color,
      })
      .eq('id', user.id)
      .select()
      .single()
    if (error) {
      // 23505 = unique violation: someone claimed the username between the
      // pre-check and the update.
      setError(
        error.code === '23505' ? 'That username is already taken.' : error.message
      )
    } else {
      setProfile(data)
      setSaved(true)
    }
    setPending(false)
  }

  async function handlePasswordSubmit(e: FormEvent) {
    e.preventDefault()
    if (!user?.email) return
    setPwError(null)
    setPwSaved(false)

    if (newPw !== confirmPw) {
      setPwError('New passwords do not match.')
      return
    }

    setPwPending(true)

    // Verify the current password with a silent re-sign-in; updateUser alone
    // would let anyone with an unlocked device change it.
    const { error: signInError } = await supabase.auth.signInWithPassword({
      email: user.email,
      password: currentPw,
    })
    if (signInError) {
      setPwError('Current password is incorrect.')
      setPwPending(false)
      return
    }

    const { error: updateError } = await supabase.auth.updateUser({ password: newPw })
    if (updateError) {
      setPwError(updateError.message)
    } else {
      setCurrentPw('')
      setNewPw('')
      setConfirmPw('')
      setPwSaved(true)
    }
    setPwPending(false)
  }

  return (
    <div className="mx-auto w-full max-w-sm px-4 py-10">
      <h1 className="text-2xl font-bold text-slate-900">Your profile</h1>
      <p className="mt-1 text-sm text-slate-500">
        This is how you appear to others in chats.
      </p>

      <div className="mt-6 flex items-center gap-4">
        <Avatar
          size="lg"
          name={displayName || profile?.username || user?.email}
          color={color}
        />
        <div className="min-w-0">
          <p className="truncate font-medium text-slate-900">
            {displayName || profile?.username || user?.email}
          </p>
          {profile?.username && (
            <p className="truncate text-sm text-slate-500">@{profile.username}</p>
          )}
          {memberSince && (
            <p className="truncate text-sm text-slate-500">Member since {memberSince}</p>
          )}
        </div>
      </div>

      <form onSubmit={handleSubmit} className="mt-6 space-y-4">
        <div>
          <label htmlFor="displayName" className={labelCls}>
            Display name
          </label>
          <input
            id="displayName"
            type="text"
            required
            maxLength={50}
            value={displayName}
            onChange={(e) => {
              setDisplayName(e.target.value)
              touch()
            }}
            className={inputCls}
          />
        </div>

        <div>
          <label htmlFor="username" className={labelCls}>
            Username
          </label>
          <input
            id="username"
            type="text"
            autoComplete="username"
            required
            maxLength={20}
            value={username}
            onChange={(e) => {
              setUsername(e.target.value.toLowerCase())
              touch()
            }}
            className={inputCls}
          />
          <p className="mt-1 text-xs text-slate-500">
            Friends find you by this, and you can log in with it.
          </p>
        </div>

        <div>
          <label htmlFor="phone" className={labelCls}>
            Phone (optional)
          </label>
          <input
            id="phone"
            type="tel"
            autoComplete="tel"
            placeholder="+6591234567"
            value={phone}
            onChange={(e) => {
              setPhone(e.target.value)
              touch()
            }}
            className={inputCls}
          />
          <p className="mt-1 text-xs text-slate-500">Singapore number, display only.</p>
        </div>

        <div>
          <div className="flex items-baseline justify-between">
            <label htmlFor="bio" className={labelCls}>
              Bio (optional)
            </label>
            <span className="text-xs text-slate-400">
              {bio.length}/{BIO_MAX}
            </span>
          </div>
          <textarea
            id="bio"
            rows={3}
            maxLength={BIO_MAX}
            value={bio}
            onChange={(e) => {
              setBio(e.target.value)
              touch()
            }}
            className={`${inputCls} resize-none`}
            placeholder="A short line about you"
          />
        </div>

        <fieldset>
          <legend className={labelCls}>Avatar colour</legend>
          <div className="mt-2 flex flex-wrap gap-3">
            {SWATCHES.map(({ hex, label }) => (
              <button
                key={hex}
                type="button"
                aria-label={label}
                aria-pressed={color === hex}
                onClick={() => {
                  setColor(hex)
                  touch()
                }}
                className={`h-8 w-8 rounded-full ${
                  color === hex ? 'ring-2 ring-emerald-500 ring-offset-2' : ''
                }`}
                style={{ backgroundColor: hex }}
              />
            ))}
            {/* Custom colour: hidden native picker inside a swatch-shaped label */}
            <label
              aria-label="Custom colour"
              title="Custom colour"
              className={`relative h-8 w-8 cursor-pointer rounded-full ${
                isCustomColor ? 'ring-2 ring-emerald-500 ring-offset-2' : ''
              }`}
              style={
                isCustomColor
                  ? { backgroundColor: color }
                  : {
                      background:
                        'conic-gradient(#dc2626, #d97706, #16a34a, #0891b2, #2563eb, #9333ea, #dc2626)',
                    }
              }
            >
              <input
                type="color"
                value={color}
                onChange={(e) => {
                  setColor(e.target.value)
                  touch()
                }}
                className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
              />
            </label>
          </div>
        </fieldset>

        {error && <p className="text-sm text-red-600">{error}</p>}
        {saved && <p className="text-sm text-emerald-700">Profile saved.</p>}

        <button type="submit" disabled={pending} className={buttonCls}>
          {pending ? 'Saving…' : 'Save'}
        </button>
      </form>

      {hasPasswordLogin && (
        <form onSubmit={handlePasswordSubmit} className="mt-10 space-y-4 border-t border-slate-200 pt-6">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Change password</h2>
            <p className="mt-1 text-sm text-slate-500">
              You'll stay logged in after changing it.
            </p>
          </div>

          <div>
            <label htmlFor="currentPw" className={labelCls}>
              Current password
            </label>
            <input
              id="currentPw"
              type="password"
              autoComplete="current-password"
              required
              value={currentPw}
              onChange={(e) => {
                setCurrentPw(e.target.value)
                setPwSaved(false)
              }}
              className={inputCls}
            />
          </div>

          <div>
            <label htmlFor="newPw" className={labelCls}>
              New password
            </label>
            <input
              id="newPw"
              type="password"
              autoComplete="new-password"
              required
              minLength={6}
              value={newPw}
              onChange={(e) => {
                setNewPw(e.target.value)
                setPwSaved(false)
              }}
              className={inputCls}
            />
          </div>

          <div>
            <label htmlFor="confirmPw" className={labelCls}>
              Confirm new password
            </label>
            <input
              id="confirmPw"
              type="password"
              autoComplete="new-password"
              required
              minLength={6}
              value={confirmPw}
              onChange={(e) => {
                setConfirmPw(e.target.value)
                setPwSaved(false)
              }}
              className={inputCls}
            />
          </div>

          {pwError && <p className="text-sm text-red-600">{pwError}</p>}
          {pwSaved && <p className="text-sm text-emerald-700">Password updated.</p>}

          <button type="submit" disabled={pwPending} className={buttonCls}>
            {pwPending ? 'Updating…' : 'Update password'}
          </button>
        </form>
      )}
    </div>
  )
}
