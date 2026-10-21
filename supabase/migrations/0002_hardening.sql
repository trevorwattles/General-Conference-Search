-- ============================================
-- 0002: Hardening grants, RLS, and functions
-- ============================================
-- 0001 is scripts/01_create_schema.py (provided by the course).
-- Apply with: python scripts/run_sql.py supabase/migrations/0002_hardening.sql
-- Safe to re-run.
--
-- Two layers, defense in depth:
--   GRANTs decide which operations a role may attempt at all.
--   RLS policies decide which rows those operations can touch.
-- Supabase grants ALL to anon/authenticated by default, so without this file
-- RLS is the only thing between the public anon key and the data.

BEGIN;

-- ============================================
-- a) sentence_embeddings: read-only for logged-in users
-- ============================================
-- The existing "Allow authenticated users to read" policy stays.
-- No INSERT/UPDATE/DELETE policies exist, so only service_role
-- (which has BYPASSRLS) can write. The grants make that explicit.

REVOKE ALL ON sentence_embeddings FROM anon, authenticated;
GRANT SELECT ON sentence_embeddings TO authenticated;

-- ============================================
-- b) match_sentences(): auth-only, bounded, returns url
-- ============================================
-- DROP is required because the return type changes (adds url).

DROP FUNCTION IF EXISTS match_sentences(vector, integer);

CREATE FUNCTION match_sentences(
  query_embedding vector(1536),
  match_count int DEFAULT 20
)
RETURNS TABLE (
  id uuid,
  talk_id uuid,
  title text,
  speaker text,
  url text,
  text text,
  similarity float
)
LANGUAGE sql STABLE
SECURITY INVOKER                        -- runs as the caller, so RLS still applies
SET search_path = public, extensions    -- no search_path hijacking
AS $$
  SELECT
    s.id,
    s.talk_id,
    s.title,
    s.speaker,
    s.url,
    s.text,
    1 - (s.embedding <=> query_embedding) AS similarity
  FROM sentence_embeddings s
  WHERE s.embedding IS NOT NULL
  ORDER BY s.embedding <=> query_embedding
  LIMIT LEAST(GREATEST(match_count, 1), 50);   -- caller can't ask for 80k rows
$$;

-- Postgres grants EXECUTE to PUBLIC by default; Supabase also grants anon directly.
REVOKE EXECUTE ON FUNCTION match_sentences(vector, integer) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION match_sentences(vector, integer) TO authenticated;

-- ============================================
-- c) page_views: write-only for the public, count via function
-- ============================================
-- Before: anyone could read every row, including every visitor's user agent.
-- After: anyone can insert a bounded row; the only thing anyone can read is the total.

ALTER TABLE page_views DROP CONSTRAINT IF EXISTS page_views_page_url_len;
ALTER TABLE page_views ADD CONSTRAINT page_views_page_url_len
  CHECK (length(page_url) < 500);
ALTER TABLE page_views DROP CONSTRAINT IF EXISTS page_views_user_agent_len;
ALTER TABLE page_views ADD CONSTRAINT page_views_user_agent_len
  CHECK (length(user_agent) < 500);

DROP POLICY IF EXISTS "Allow public reads" ON page_views;

-- Column-level INSERT: clients can set page_url and user_agent only,
-- so id and visited_at always come from the DB defaults (no forged timestamps).
REVOKE ALL ON page_views FROM anon, authenticated;
GRANT INSERT (page_url, user_agent) ON page_views TO anon, authenticated;

-- SECURITY DEFINER runs as the owner (bypassing RLS) but exposes only a count.
-- Empty search_path + fully qualified names so a caller can't shadow page_views.
CREATE OR REPLACE FUNCTION page_view_count()
RETURNS bigint
LANGUAGE sql STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
  SELECT count(*) FROM public.page_views;
$$;

REVOKE EXECUTE ON FUNCTION page_view_count() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION page_view_count() TO anon, authenticated;

COMMIT;
