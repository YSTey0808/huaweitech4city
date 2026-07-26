import { createClient } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL as string | undefined
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined

/** False when env vars are missing — main.tsx shows a config-error screen instead of the app. */
export const supabaseConfigured = Boolean(supabaseUrl && supabaseAnonKey)

// Placeholders keep createClient from throwing at module load; the client is
// never used when supabaseConfigured is false (main.tsx guards).
export const supabase = createClient(
  supabaseUrl ?? 'https://placeholder.supabase.co',
  supabaseAnonKey ?? 'placeholder-anon-key',
)
