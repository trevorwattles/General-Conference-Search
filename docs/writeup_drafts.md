# Write-up drafts

> **Agent-drafted (Claude Code).** Trevor asked the agent to draft these; edit into your own voice before they go in submission.md.

## Why the public anon key can't read the talks (Checkpoint 2)

The anon key is published in `config.public.json` on purpose. It isn't a password; it only tells Supabase "this request comes from my app, as the `anon` role." Everything that role can do is decided inside the database, so knowing the key gives someone nothing beyond what I've allowed `anon` to do.

Two separate layers stop an anonymous request for `sentence_embeddings`:

1. **Grants (which operations a role may attempt).** Supabase grants ALL privileges to `anon` by default. My migration (`0002_hardening.sql`) revokes them, so `anon` has no privileges at all on `sentence_embeddings` and can't EXECUTE `match_sentences()`. The request fails right away with `42501 permission denied` and never reaches row filtering.
2. **Row Level Security (which rows a role can see).** The table's only policy is `FOR SELECT TO authenticated USING (true)`. Even if the grant came back by mistake, an `anon` request matches no policy, so RLS would return zero rows. There are no INSERT/UPDATE/DELETE policies for anyone, so only the service_role key (which bypasses RLS and is used only by my local scripts) can write.

To read the talks you need a JWT whose `role` claim is `authenticated`, and you only get one of those by logging in with a magic link. Supabase signs that JWT, so it can't be forged by editing the anon key. `scripts/test_rls.py` proves it: 14/14 checks, with anon denied on reads, writes, and the search function while a signed-in test user can still read.

**Caveat I learned:** "authenticated" means "anyone with an email address," because signup is open. Login stops scrapers and bots, but it isn't the same as "trusted." Per-user rules (Phase 6) and rate limits matter for that reason.

### Bonus: what if `match_sentences` were SECURITY DEFINER?

It would run as the table owner and skip RLS. If the EXECUTE grant to `anon` ever came back (Postgres grants EXECUTE to PUBLIC by default on new functions), an anonymous user could pass in any vector and walk the whole table 50 rows at a time. The authenticated-only rule would be gone, because the function itself would be the hole. INVOKER keeps the function exactly as powerful as its caller.
