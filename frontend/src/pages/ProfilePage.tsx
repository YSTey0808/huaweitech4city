import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { supabase } from '../lib/supabase'
import { useAuth } from '../context/AuthContext'
import Avatar from '../components/Avatar'
import { USERNAME_RE, SG_PHONE_RE } from '../lib/validators'

// All dark enough for white initials; first entry is the DB signup default.
const SWATCHES = [
  { hex: '#8d827b', label: 'Stone' },
  { hex: '#6f6661', label: 'Taupe' },
  { hex: '#c8102e', label: 'Nuwa red' },
  { hex: '#b3122d', label: 'Crimson' },
  { hex: '#a8562f', label: 'Clay' },
  { hex: '#b87a2c', label: 'Amber' },
  { hex: '#8a7b3f', label: 'Olive' },
  { hex: '#5c7346', label: 'Moss' },
  { hex: '#3f6b63', label: 'Pine' },
  { hex: '#3d6480', label: 'Slate blue' },
  { hex: '#4a5680', label: 'Indigo' },
  { hex: '#6b4f73', label: 'Plum' },
]

const BIO_MAX = 160

const inputCls =
  'mt-1.5 w-full rounded-xl border border-field-border bg-field px-3.5 py-2.5 text-sm text-slate-900 outline-none transition-colors placeholder:text-slate-400 focus:border-field-focus focus:shadow-field'
const labelCls = 'block text-[13px] font-medium text-slate-700'
// Primary action: flat Huawei red, not a gradient -- lighter weight than the
// old chunky button while staying the clear primary on the page.
const buttonCls =
  'w-full rounded-xl bg-brand-600 px-6 py-3 text-sm font-bold text-white shadow-brand transition-all hover:brightness-110 disabled:opacity-50'

export default function ProfilePage() {
  const { user, profile, setProfile } = useAuth()

  // Profile details form
  const [displayName, setDisplayName] = useState('')
  const [username, setUsername] = useState('')
  const [phone, setPhone] = useState('')
  const [bio, setBio] = useState('')
  const [color, setColor] = useState('#8d827b')
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
      setColor(profile.avatar_color ?? '#8d827b')
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
    <div className="mx-auto w-full max-w-md px-4 py-8">
      <h1 className="text-xl font-semibold tracking-tight text-slate-900">Your profile</h1>
      <p className="mt-1 text-sm text-slate-500">
        This is how you appear to others in chats.
      </p>

      <div className="mt-5 flex items-center gap-3.5 rounded-xl border border-field-border bg-field px-4 py-3.5 shadow-card">
        <Avatar
          size="lg"
          name={displayName || profile?.username || user?.email}
          color={color}
        />
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-slate-900">
            {displayName || profile?.username || user?.email}
          </p>
          {profile?.username && (
            <p className="truncate text-[13px] text-slate-600">@{profile.username}</p>
          )}
          {memberSince && (
            <p className="mt-0.5 truncate text-[11px] text-slate-400">
              Member since {memberSince}
            </p>
          )}
        </div>
      </div>

      {/* Section label + thin divider rather than a second floating card --
          groups the fields without stacking panels on panels. */}
      <h2 className="mt-7 border-b border-field-border pb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
        Profile information
      </h2>

      <form onSubmit={handleSubmit} className="mt-4 space-y-3.5">
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
          <div className="mt-2.5 flex flex-wrap gap-2.5">
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
                className={`h-7 w-7 rounded-full transition-transform hover:scale-105 ${
                  color === hex
                    ? 'ring-2 ring-slate-900 ring-offset-2 ring-offset-canvas'
                    : 'ring-1 ring-black/5'
                }`}
                style={{ backgroundColor: hex }}
              />
            ))}
            {/* Custom colour: hidden native picker inside a swatch-shaped label */}
            <label
              aria-label="Custom colour"
              title="Custom colour"
              className={`relative h-7 w-7 cursor-pointer rounded-full transition-transform hover:scale-105 ${
                isCustomColor
                  ? 'ring-2 ring-slate-900 ring-offset-2 ring-offset-canvas'
                  : 'ring-1 ring-black/5'
              }`}
              style={
                isCustomColor
                  ? { backgroundColor: color }
                  : {
                      background:
                        'conic-gradient(#c8102e, #b87a2c, #5c7346, #3f6b63, #4a5680, #6b4f73, #c8102e)',
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
        <form onSubmit={handlePasswordSubmit} className="mt-8 space-y-3.5">
          {/* Same label + divider treatment as the profile section above, so
              the two groups read as one page rather than two components. */}
          <div className="border-b border-field-border pb-2">
            <h2 className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
              Password
            </h2>
          </div>
          <p className="!mt-2 text-[13px] text-slate-600">
            You'll stay logged in after changing it.
          </p>

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
