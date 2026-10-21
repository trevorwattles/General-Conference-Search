# Architecture & Scaling

Conference Talk RAG: 426 General Conference talks (2020–2025), 26,256 sentence chunks, keyword + semantic + RAG search.
Live: https://trevorwattles.github.io/conference-rag/

All numbers below were measured on the Supabase free tier during the build (`scripts/explain_search.py`, `scripts/test_rls.py`, `scripts/test_functions.py`).

## Request flow

```
Browser (GitHub Pages: static HTML/JS, CDN-served)
 │  anon key (public) + user JWT after magic-link login
 │
 ├─► Supabase Auth ─────────── magic link → ES256-signed JWT (role=authenticated, sub=user id)
 │
 ├─► PostgREST (Data API) ──── every query runs as anon/authenticated → GRANTs + RLS decide
 │     ├─ sentence_embeddings   keyword search (ILIKE, trigram GIN index)
 │     ├─ match_sentences()     semantic search (HNSW index), authenticated only
 │     ├─ question_history      per-user RLS
 │     └─ page_views            insert-only; page_view_count() exposes just the total
 │
 └─► Edge Functions (Deno, stateless) ── "secure middle": auth check → validate → rate limit → OpenAI
       ├─ embed-question    cache (question_embeddings_cache) → text-embedding-3-small
       └─ generate-answer   GPT-4o over ≤5 retrieved talks → writes question_history with caller's JWT
```

## What protects each asset

| Asset | Lives in | Protected by |
|---|---|---|
| Talk text + vectors | `sentence_embeddings` | GRANT SELECT to `authenticated` only + RLS policy; no write grants/policies (only service_role writes) |
| Users' questions & answers | `question_history` | RLS `user_id = (select auth.uid())` for SELECT/INSERT/DELETE; no UPDATE; column-level INSERT so `user_id`/`created_at` can't be forged |
| Rate-limit log, embedding cache | `api_usage`, `question_embeddings_cache` | RLS on, **no policies, no grants**: only Edge Functions via service_role |
| Visitor analytics | `page_views` | Clients may only INSERT `page_url`/`user_agent` (length-checked); reads go through a count-only `SECURITY DEFINER` function. URLs are stored without query/fragment so magic-link tokens are never saved. |
| OpenAI key | Edge Function secret | Never sent to the browser; functions require a real user JWT (anon key alone → 401) |
| service_role key | `config.secret.json` (git-ignored) + Edge runtime env | Used only by local scripts and server-side code; bypasses RLS, so it never reaches the browser |
| anon key | `config.public.json` (public) | Safe by design: it only identifies the app; GRANTs + RLS limit the `anon` role |

Two layers in Postgres, on purpose: **GRANTs** decide which operations a role may attempt (failures are `42501 permission denied`); **RLS** decides which rows (filtered rows just aren't there: 0 rows, no error). Supabase grants `ALL` to `anon`/`authenticated` by default, so `0002_hardening.sql` revokes them; without that, RLS would be the only wall, and `TRUNCATE` isn't covered by RLS at all.

## What scales on its own

- **Static frontend.** GitHub Pages is a CDN. A million visitors cost the same as ten. The bottlenecks are the database and OpenAI.
- **Edge Functions are stateless.** No sessions in memory, so the platform can run as many copies as traffic needs. All state is in Postgres.
- **Connection pooling.** Browsers never open Postgres connections. PostgREST and the Edge Functions' supabase-js clients go through Supabase's pooled HTTP APIs.

## Indexes (measured)

| Query | Without index | With index | Index |
|---|---|---|---|
| Keyword `ILIKE '%xylophone%'` (no match) | 91 ms, read all 26,256 rows | 0.35 ms | trigram GIN (`0003`) |
| Keyword `ILIKE '%Kirtland%'` (rare) | 49 ms | 0.8 ms | trigram GIN |
| Keyword `ILIKE '%faith%'` (common) | 1.4 ms (lucky early stop) | 3.8 ms | trigram GIN: slower here, but no query scans the whole table anymore |
| Semantic top-20 | **17–23 s** exact scan: over the 8 s `authenticated` statement timeout, so it would have *failed* | **3–8 ms** warm, ~0.3–1.3 s cold; 90–100% recall vs exact on samples | HNSW cosine (`0004`) |
| Readiness check on every page load | 2,967 ms `count: 'exact'` | 2.4 ms `limit(1)` | (query change) |

Notes:
- `ILIKE '%x%'` can't use a btree because of the leading `%`; trigrams can.
- HNSW returns at most `hnsw.ef_search` rows (default 40). `match_sentences` allows 50, so the function sets `ef_search = 100`.
- **HNSW is fast only when it fits in RAM.** Table plus indexes are 435 MB, but `shared_buffers` is 224 MB, so cold queries pay roughly 750 disk reads. On the free tier the build itself failed with a parallel 128 MB memory segment; a serial build with 64 MB worked.
- **Vector indexes make writes expensive.** Rows this big can't be HOT-updated, so updating a non-vector column (cleaning speaker names) re-inserts every row into the HNSW graph. That took more than 15 minutes for 25k rows.

## Cost controls

At GPT-4o list prices ($2.50/M input, $10/M output tokens), one RAG answer with three full talks (~11k input tokens) costs about **$0.03**. One question per day from a million users would be about $30,000 a day, so OpenAI cost is the real scaling limit, and these controls matter more than CPU:

| Control | Where | Effect |
|---|---|---|
| Input caps | both functions | Question 1–1000 chars; ≤5 talks, ≤60k chars of context; `max_tokens` 1024. Bounds the cost of any single request. |
| Validate before paying | both functions | Bad input, no auth, and the app's readiness probe (`context_talks: []`) return 401/400 **before** any OpenAI call |
| Embedding cache | `embed-question` | sha256 of the normalized question. Repeats cost $0. Has no user_id, so it's shared without linking users to questions. |
| Per-user rate limit | `api_usage` + `consume_rate_limit()` | 30 answers/hour and 100 *new* embeddings/hour (cache hits are free). Atomic (advisory lock), server-only, and it can't be reset by deleting your history. Caps one account at ~$0.90/hour. |

## RLS performance

- `(select auth.uid())` instead of `auth.uid()` in policies: Postgres evaluates it once per query instead of once per row.
- `question_history (user_id, created_at DESC)` index: the policy's `user_id = …` filter plus "newest first" is a single index range scan, no matter how many users there are.
- `match_sentences` is `SECURITY INVOKER`, so RLS still applies inside it, with a pinned `search_path`.

## What I'd change for millions of users

1. **Answer cache for popular questions** (keyed like the embedding cache, with a TTL). Most traffic is repeat questions, and that's where the $0.03s go.
2. **Size the database to hold the vector index in RAM**, or shrink it with `halfvec` (16-bit floats, about half the size). Add **read replicas** for search traffic. Tune `ef_search` (recall vs. latency) and `ef_construction`/`m` when building.
3. **Housekeeping jobs (pg_cron):** `api_usage` and `question_embeddings_cache` grow forever, so delete usage rows older than a day and expire cache entries.
4. **`page_views`:** `page_view_count()` is a `count(*)` per visit, and anonymous inserts are unbounded (spam). Use a counter table or the planner's estimate, and rate-limit anonymous inserts at the edge.
5. **Don't let the browser supply RAG context.** `generate-answer` trusts `context_talks` (capped and rate-limited). Passing talk IDs and fetching text server-side would stop the function being used as a general GPT-4o proxy.
6. **Route aggregate questions to SQL.** "Which talk mentions Christ the most?" needs all 426 talks; RAG only sees the top 3 and confidently picked the #5 talk.
7. **Signup is open**, so `authenticated` means "anyone with an email". At scale, add CAPTCHA on sign-in and per-IP limits on Auth.
8. **Paid tier:** higher statement timeouts, more RAM and connections, and Auth email limits above 3/hour.
