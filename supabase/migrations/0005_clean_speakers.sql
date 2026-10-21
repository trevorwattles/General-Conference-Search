-- ============================================
-- 0005: Clean scraped speaker names
-- ============================================
-- The scraper stored "By President Russell M. Nelson": a "By " prefix
-- (the UI adds its own "by", so it showed "by By ...") and non-breaking
-- spaces, which make exact matches and speaker filters miss.
-- scripts/02_scrape_data.py now cleans new scrapes; this fixes existing rows.
--
-- Apply with: python scripts/run_sql.py supabase/migrations/0005_clean_speakers.sql
--
-- Slow on this table: MVCC writes a new row version per UPDATE, and
-- these rows are too big for HOT updates, so every row also gets a new HNSW
-- graph entry. It timed out at the default 2 min, hence the longer limit.

SET statement_timeout = '20min';

UPDATE sentence_embeddings
SET speaker = regexp_replace(replace(speaker, chr(160), ' '), '^By\s+', '')
WHERE speaker ~ '^By\s' OR position(chr(160) in speaker) > 0;
