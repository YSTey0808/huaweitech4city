const DEFAULT_COLOR = '#64748b' // matches the handle_new_user() DB default

const sizeClasses = {
  sm: 'h-7 w-7 text-xs',
  md: 'h-10 w-10 text-sm',
  lg: 'h-16 w-16 text-xl',
} as const

interface AvatarProps {
  /** Initials source — caller passes the best available (display_name ?? username ?? email). */
  name: string | null | undefined
  /** Hex colour from profiles.avatar_color; falls back to the DB default. */
  color: string | null | undefined
  size?: keyof typeof sizeClasses
}

function initialsOf(name: string | null | undefined): string {
  if (!name) return '?'
  const parts = name.trim().split(/\s+/).slice(0, 2)
  const initials = parts.map((p) => p[0]).join('').toUpperCase()
  return initials || '?'
}

export default function Avatar({ name, color, size = 'md' }: AvatarProps) {
  return (
    <span
      aria-hidden="true"
      className={`flex shrink-0 select-none items-center justify-center rounded-full font-medium text-white ${sizeClasses[size]}`}
      style={{ backgroundColor: color ?? DEFAULT_COLOR }}
    >
      {initialsOf(name)}
    </span>
  )
}
