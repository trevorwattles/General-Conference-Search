-- ============================================
-- 0006: Question history, embedding cache, rate limit
-- ============================================
-- question_history       per-user rows; RLS: you see/insert/delete only your own
-- question_embeddings_cache  server-only (Edge Functions via service_role)
-- api_usage              server-only rate-limit log; users can't read, forge, or delete it
--
-- Apply with: python scripts/run_sql.py supabase/migrations/0006_history_cache_ratelimit.sql
-- Safe to re-run.

BEGIN;

-- ============================================
-- question_history: real per-user RLS
-- ============================================

CREATE TABLE IF NOT EXISTS question_history (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL DEFAULT auth.uid() REFERENCES auth.users (id) ON DELETE CASCADE,
    question text NOT NULL CHECK (length(question) BETWEEN 1 AND 1000),
    answer text NOT NULL CHECK (length(answer) < 20000),
    sources jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(sources) = 'array' AND pg_column_size(sources) < 20000),
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Serves "my latest questions" without scanning anyone else's rows.
CREATE INDEX IF NOT EXISTS question_history_user_created_idx
ON question_history (user_id, created_at DESC);

ALTER TABLE question_history ENABLE ROW LEVEL SECURITY;

-- (select auth.uid()) is evaluated once per query instead of once per row.
DROP POLICY IF EXISTS "Users read own history" ON question_history;
CREATE POLICY "Users read own history" ON question_history
FOR SELECT TO authenticated USING (user_id = (select auth.uid()));

DROP POLICY IF EXISTS "Users insert own history" ON question_history;
CREATE POLICY "Users insert own history" ON question_history
FOR INSERT TO authenticated WITH CHECK (user_id = (select auth.uid()));

DROP POLICY IF EXISTS "Users delete own history" ON question_history;
CREATE POLICY "Users delete own history" ON question_history
FOR DELETE TO authenticated USING (user_id = (select auth.uid()));

-- No UPDATE policy or grant: history is append/delete only.
-- Column-level INSERT: user_id and created_at always come from defaults.
REVOKE ALL ON question_history FROM anon, authenticated;
GRANT SELECT, DELETE ON question_history TO authenticated;
GRANT INSERT (question, answer, sources) ON question_history TO authenticated;

-- ============================================
-- question_embeddings_cache: server-only
-- ============================================
-- Keyed by sha256 of the normalized question; no user_id, so it's shared
-- across users without linking anyone to what they asked.

CREATE TABLE IF NOT EXISTS question_embeddings_cache (
    question_hash text PRIMARY KEY,
    embedding vector(1536) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE question_embeddings_cache ENABLE ROW LEVEL SECURITY;
-- RLS on + no policies = only service_role (BYPASSRLS) can touch it.
REVOKE ALL ON question_embeddings_cache FROM anon, authenticated;

-- ============================================
-- api_usage + consume_rate_limit(): server-only
-- ============================================
-- Not question_history: users can delete their own history, which would
-- reset the limit, and a script calling the function directly never writes history.

CREATE TABLE IF NOT EXISTS api_usage (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id uuid NOT NULL,
    fn text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS api_usage_user_fn_created_idx
ON api_usage (user_id, fn, created_at DESC);

ALTER TABLE api_usage ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON api_usage FROM anon, authenticated;

-- Records a call and returns true if the user is still under the limit.
-- The advisory lock serializes one user's concurrent calls, so parallel
-- requests can't all pass the count before any of them inserts.
CREATE OR REPLACE FUNCTION consume_rate_limit(
    p_user_id uuid,
    p_fn text,
    p_limit int,
    p_window interval
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $$
DECLARE
    recent int;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(p_user_id::text || ':' || p_fn, 0));

    SELECT count(*) INTO recent
    FROM public.api_usage
    WHERE user_id = p_user_id AND fn = p_fn AND created_at > now() - p_window;

    IF recent >= p_limit THEN
        RETURN false;
    END IF;

    INSERT INTO public.api_usage (user_id, fn) VALUES (p_user_id, p_fn);
    RETURN true;
END;
$$;

-- Only Edge Functions (service_role) may call it; otherwise a user could
-- burn someone else's quota by passing their user_id.
REVOKE EXECUTE ON FUNCTION consume_rate_limit(uuid, text, int, interval) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION consume_rate_limit(uuid, text, int, interval) TO service_role;

COMMIT;
