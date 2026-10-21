// embed-question: { question } → { embedding: number[1536], cached: boolean }
// The "secure middle": the browser never sees the OpenAI key.
// Checks run cheapest-first so bad requests never cost an OpenAI call.
// Repeat questions come from question_embeddings_cache and cost $0.

import { handlePreflight, jsonResponse } from '../_shared/cors.ts';
import { requireAuth } from '../_shared/auth.ts';
import { consumeRateLimit, serviceClient } from '../_shared/db.ts';

const OPENAI_API_KEY = Deno.env.get('OPENAI_API_KEY')!;
const MAX_QUESTION_CHARS = 1000;
const CACHE_MISSES_PER_HOUR = 100;   // only OpenAI calls count; cache hits are free

// "  What is FAITH? " and "what is faith?" share one cache entry.
async function questionHash(question: string): Promise<string> {
  const normalized = question.toLowerCase().replace(/\s+/g, ' ').trim();
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(normalized));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('');
}

Deno.serve(async (req) => {
  const preflight = handlePreflight(req);
  if (preflight) return preflight;
  if (req.method !== 'POST') return jsonResponse(req, { error: 'Use POST' }, 405);

  const user = await requireAuth(req);
  if (user instanceof Response) return user;

  let body: { question?: unknown };
  try {
    body = await req.json();
  } catch {
    return jsonResponse(req, { error: 'Body must be JSON' }, 400);
  }

  const question = typeof body.question === 'string' ? body.question.trim() : '';
  if (question.length < 1 || question.length > MAX_QUESTION_CHARS) {
    return jsonResponse(req, { error: `question must be a string of 1-${MAX_QUESTION_CHARS} characters` }, 400);
  }

  const hash = await questionHash(question);
  const { data: hit } = await serviceClient
    .from('question_embeddings_cache')
    .select('embedding')
    .eq('question_hash', hash)
    .maybeSingle();
  if (hit) {
    // pgvector comes back from PostgREST as the text "[0.1,0.2,...]"
    return jsonResponse(req, { embedding: JSON.parse(hit.embedding), cached: true });
  }

  if (!(await consumeRateLimit(user.id, 'embed-question', CACHE_MISSES_PER_HOUR, '1 hour'))) {
    return jsonResponse(req, { error: 'Too many new questions this hour. Try again later.' }, 429);
  }

  const openaiRes = await fetch('https://api.openai.com/v1/embeddings', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${OPENAI_API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ model: 'text-embedding-3-small', input: question }),
  });

  if (!openaiRes.ok) {
    // Log details server-side; don't leak upstream errors to the client.
    console.error('OpenAI embeddings error', openaiRes.status, await openaiRes.text());
    return jsonResponse(req, { error: 'Embedding service failed' }, 502);
  }

  const { data } = await openaiRes.json();
  const embedding = data[0].embedding;

  // Best-effort: a failed cache write shouldn't fail the request.
  const { error: cacheError } = await serviceClient
    .from('question_embeddings_cache')
    .upsert({ question_hash: hash, embedding }, { onConflict: 'question_hash', ignoreDuplicates: true });
  if (cacheError) console.error('cache write failed', cacheError.message);

  return jsonResponse(req, { embedding, cached: false });
});
