import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.tsx'
import { AuthProvider } from './context/AuthContext.tsx'
import { supabaseConfigured } from './lib/supabase.ts'
import './index.css'

// Without this guard a missing env var crashes createClient at module load,
// leaving a blank page with no explanation on the deployed site.
function ConfigError() {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-slate-50 p-4">
      <div className="max-w-md rounded-lg border border-slate-200 bg-white p-6">
        <h1 className="font-semibold text-slate-900">App not configured</h1>
        <p className="mt-2 text-sm text-slate-700">
          Missing Supabase environment variables{' '}
          <code className="text-xs">VITE_SUPABASE_URL</code> and/or{' '}
          <code className="text-xs">VITE_SUPABASE_ANON_KEY</code>.
        </p>
        <p className="mt-2 text-sm text-slate-500">
          Locally: copy <code className="text-xs">.env.example</code> to{' '}
          <code className="text-xs">.env</code>, fill in your project values, and restart the dev
          server. On Vercel: add them under Project Settings → Environment Variables and redeploy.
        </p>
      </div>
    </div>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {supabaseConfigured ? (
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    ) : (
      <ConfigError />
    )}
  </StrictMode>,
)
