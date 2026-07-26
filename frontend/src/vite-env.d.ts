/// <reference types="vite/client" />

interface ImportMetaEnv {
  // May be undefined at runtime if not set — lib/supabase.ts validates.
  readonly VITE_SUPABASE_URL: string | undefined
  readonly VITE_SUPABASE_ANON_KEY: string | undefined
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
