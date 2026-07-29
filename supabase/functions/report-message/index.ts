// Thin proxy for the human-feedback loop — mirrors score-message/index.ts.
// Invoked from the client after a user files a report with
// { conversation_id, msg_id, reason }. Verifies the caller is a member of the
// conversation, then forwards to the backend's POST /report, which re-scores
// the conversation window ending at the reported message with the report
// folded into the LLM reasoning prompt, and writes message_scores /
// conversation_scores rows tagged source='user_report' itself (service role).
// The message_reports row is inserted by the client directly (RLS-guarded) —
// this function never touches reports, messages, or scores.
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

  const { conversation_id, msg_id, reason, claim = 'harmful' } = await req.json().catch(() => ({}))
  if (typeof conversation_id !== 'string' || !conversation_id) {
    return json({ error: 'conversation_id required' }, 400)
  }
  if (typeof msg_id !== 'string' || !msg_id) {
    return json({ error: 'msg_id required' }, 400)
  }
  if (typeof reason !== 'string' || !reason.trim()) {
    return json({ error: 'reason required' }, 400)
  }
  // claim direction (migration 010): 'harmful' = model missed this;
  // 'safe' = false-positive dispute.
  if (claim !== 'harmful' && claim !== 'safe') {
    return json({ error: "claim must be 'harmful' or 'safe'" }, 400)
  }

  // Identify the caller from the forwarded JWT.
  const userClient = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_ANON_KEY')!,
    { global: { headers: { Authorization: req.headers.get('Authorization') ?? '' } } },
  )
  const { data: { user } } = await userClient.auth.getUser()
  if (!user) return json({ error: 'unauthorized' }, 401)

  // Only conversation members may trigger report re-scoring. The service
  // client bypasses RLS, so membership is checked explicitly.
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

  // Forward to the backend. It re-fetches the window itself (anchored at the
  // reported message, never trusting a client-supplied window) and validates
  // that msg_id actually belongs to conversation_id.
  const backendUrl = Deno.env.get('BACKEND_URL')
  const backendSecret = Deno.env.get('BACKEND_SHARED_SECRET')
  if (!backendUrl || !backendSecret) {
    return json({ error: 'backend not configured (BACKEND_URL / BACKEND_SHARED_SECRET missing)' }, 500)
  }

  try {
    const res = await fetch(`${backendUrl}/report`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Backend-Secret': backendSecret,
      },
      body: JSON.stringify({ conversation_id, msg_id, reason: reason.trim(), claim }),
    })
    const body = await res.json().catch(() => ({}))
    return json(body, res.status)
  } catch (err) {
    return json({ error: `backend unreachable: ${err instanceof Error ? err.message : String(err)}` }, 502)
  }
})
