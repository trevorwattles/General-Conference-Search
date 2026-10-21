// embed-question: { question } → { embedding: number[1536] }
// The "secure middle": the browser never sees the OpenAI key.
// Checks run cheapest-first so bad requests never cost an OpenAI call.

import { handlePreflight, jsonResponse } from '../_shared/cors.ts';
import { requireAuth } from '../_shared/auth.ts';

const OPENAI_API_KEY = Deno.env.get('OPENAI_API_KEY')!;
const MAX_QUESTION_CHARS = 1000;

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
  return jsonResponse(req, { embedding: data[0].embedding });
});
