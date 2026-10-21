-- ============================================
-- 0003: Trigram index for keyword search
-- ============================================
-- Keyword search runs: text ILIKE '%term%' LIMIT 20
-- A leading % defeats a btree, so without this every rare or missing term
-- scans the whole table. pg_trgm indexes 3-character substrings, which
-- lets GIN answer ILIKE '%term%' without reading every row.
--
-- Apply with: python scripts/run_sql.py supabase/migrations/0003_keyword_index.sql

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA extensions;

CREATE INDEX IF NOT EXISTS sentence_embeddings_text_trgm_idx
ON sentence_embeddings USING gin (text extensions.gin_trgm_ops);

ANALYZE sentence_embeddings;
