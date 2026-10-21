// Auth: these functions are deployed with --no-verify-jwt, so we verify here.
// Supabase Auth checks the caller's JWT; the anon key alone has no user and fails.

import { createClient, type User } from 'npm:@supabase/supabase-js@2';
import { jsonResponse } from './cors.ts';

const supabaseUrl = Deno.env.get('SUPABASE_URL')!;
const supabaseAnonKey = Deno.env.get('SUPABASE_ANON_KEY')!;
const authClient = createClient(supabaseUrl, supabaseAnonKey, {
  auth: { persistSession: false },
});

// Returns the signed-in user, or a 401 Response to send back.
export async function requireAuth(req: Request): Promise<User | Response> {
  const token = req.headers.get('Authorization')?.replace(/^Bearer\s+/i, '');
  if (!token) {
    return jsonResponse(req, { error: 'Missing Authorization header' }, 401);
  }

  const { data, error } = await authClient.auth.getUser(token);
  if (error || !data.user) {
    return jsonResponse(req, { error: 'Not signed in' }, 401);
  }
  return data.user;
}
