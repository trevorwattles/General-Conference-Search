-- ============================================
-- 0004: HNSW index for semantic search
-- ============================================
-- Run AFTER embeddings are loaded (scripts/05_update_embeddings.py):
-- building on a full table gives a better graph than inserting into it row by row.
--
-- Without this, match_sentences() computes the distance to every vector
-- (exact scan, O(n)). HNSW walks a layered neighbor graph instead
-- (approximate nearest neighbors, ~O(log n)), trading a little recall for speed.
--
-- Apply with: python scripts/run_sql.py supabase/migrations/0004_vector_index.sql

-- Session-only settings for the build (free tier: small RAM, 2 min default timeout).
-- A parallel build allocates a shared memory segment of maintenance_work_mem;
-- at 128MB the free tier failed with "could not resize shared memory segment".
-- Serial build + smaller budget fits; it spills to disk and just takes longer.
SET max_parallel_maintenance_workers = 0;
SET maintenance_work_mem = '64MB';
SET statement_timeout = '15min';

CREATE INDEX IF NOT EXISTS sentence_embeddings_embedding_hnsw_idx
ON sentence_embeddings USING hnsw (embedding vector_cosine_ops);

-- HNSW returns at most ef_search rows (default 40), but match_sentences allows 50.
-- Raise it on the function so callers get full results and better recall.
-- (Re-running 0002 recreates the function; re-run this file after it.)
ALTER FUNCTION match_sentences(vector, integer) SET hnsw.ef_search = 100;

ANALYZE sentence_embeddings;
