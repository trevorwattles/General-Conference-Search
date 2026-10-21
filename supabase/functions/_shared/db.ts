// Database clients for Edge Functions. Which one you use is a security decision:
//   serviceClient   service_role key, BYPASSES RLS: only for server-only tables
//                   (question_embeddings_cache, api_usage).
//   userClient(req) the caller's own JWT, so RLS still applies: use for user data
//                   (question_history), so a function bug can't touch other users' rows.

import { createClient } from 'npm:@supabase/supabase-js@2';

const supabaseUrl = Deno.env.get('SUPABASE_URL')!;
const noSession = { auth: { persistSession: false, autoRefreshToken: false } };

export const serviceClient = createClient(supabaseUrl, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!, noSession);

export function userClient(req: Request) {
  return createClient(supabaseUrl, Deno.env.get('SUPABASE_ANON_KEY')!, {
    ...noSession,
    global: { headers: { Authorization: req.headers.get('Authorization') ?? '' } },
  });
}

// Returns true if the user may proceed (and records the call). Fails closed.
export async function consumeRateLimit(userId: string, fn: string, limit: number, window: string) {
  const { data, error } = await serviceClient.rpc('consume_rate_limit', {
    p_user_id: userId, p_fn: fn, p_limit: limit, p_window: window,
  });
  if (error) {
    console.error('rate limit check failed', error.message);
    return false;
  }
  return data === true;
}
