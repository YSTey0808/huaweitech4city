// Thin proxy — see docs/backend.md for the real scoring logic.
// Invoked from the client after each send with { conversation_id }. Verifies
// the caller is a member of the conversation, then forwards the request to
// the backend service (FastAPI + the preprocess -> embed -> graph -> GNN ->
// LLM pipeline in pipeline/), which does the actual scoring and writes
// message_scores / conversation_scores rows itself using its own
// service-role Supabase client. This function never touches messages or
// scores directly.
import { createClient } from 'npm:@supabase/supabase-js@2'

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders, 'Content-Type': 'application/json' },
  })
}

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: corsHeaders })

  const { conversation_id } = await req.json().catch(() => ({}))
  if (typeof conversation_id !== 'string' || !conversation_id) {
    return json({ error: 'conversation_id required' }, 400)
  }

  // Identify the caller from the forwarded JWT.
  const userClient = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_ANON_KEY')!,
    { global: { headers: { Authorization: req.headers.get('Authorization') ?? '' } } },
  )
  const { data: { user } } = await userClient.auth.getUser()
  if (!user) return json({ error: 'unauthorized' }, 401)

  // Only conversation members may trigger scoring. The service client bypasses
  // RLS, so membership is checked explicitly.
  const svc = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
  )
  const { data: member, error: memberErr } = await svc
    .from('conversation_members')
    .select('user_id')
    .eq('conversation_id', conversation_id)
    .eq('user_id', user.id)
    .maybeSingle()
  if (memberErr) return json({ error: memberErr.message }, 500)
  if (!member) return json({ error: 'forbidden' }, 403)

  // Forward to the backend. It re-fetches the message window itself with its
  // own service-role client (never trust a client-supplied window) and
  // writes message_scores / conversation_scores directly.
  const backendUrl = Deno.env.get('BACKEND_URL')
  const backendSecret = Deno.env.get('BACKEND_SHARED_SECRET')
  if (!backendUrl || !backendSecret) {
    return json({ error: 'backend not configured (BACKEND_URL / BACKEND_SHARED_SECRET missing)' }, 500)
  }

  try {
    const res = await fetch(`${backendUrl}/score`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Backend-Secret': backendSecret,
      },
      body: JSON.stringify({ conversation_id }),
    })
    const body = await res.json().catch(() => ({}))
    return json(body, res.status)
  } catch (err) {
    return json({ error: `backend unreachable: ${err instanceof Error ? err.message : String(err)}` }, 502)
  }
})
