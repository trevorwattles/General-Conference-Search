"""
RLS Proof Test
==============
Exercises the database's access controls the same way the browser does:
with the PUBLIC anon key, first anonymously, then signed in as a test user.

The service key is used ONLY to create/delete the throwaway test user
(admin API, no email sent). Every access check runs through an anon client.

Usage:
    python scripts/test_rls.py
"""

import json
import secrets as pysecrets
import sys
import warnings

warnings.filterwarnings('ignore')

from postgrest.types import ReturnMethod
from supabase import create_client

with open('config.public.json', 'r') as f:
    public_config = json.load(f)
with open('config.secret.json', 'r') as f:
    secret_config = json.load(f)

SUPABASE_URL = public_config['SUPABASE_URL']
SUPABASE_ANON_KEY = public_config['SUPABASE_ANON_KEY']
SUPABASE_SERVICE_KEY = secret_config['SUPABASE_SERVICE_KEY']

TEST_USERS = ['rls-test-a@example.com', 'rls-test-b@example.com']
PROBE_VECTOR = [1.0] + [0.0] * 1535

results = []


def check(name, expect, fn):
    """expect='allowed' → fn must succeed; expect='blocked' → fn must raise or return no rows."""
    try:
        out = fn()
        rows = getattr(out, 'data', out)
        got_rows = bool(rows) if isinstance(rows, list) else rows is not None
        if expect == 'allowed':
            passed, detail = True, f'ok ({len(rows)} rows)' if isinstance(rows, list) else f'ok ({rows})'
        else:
            passed, detail = not got_rows, '0 rows returned' if not got_rows else f'LEAKED {len(rows)} rows'
    except Exception as e:
        msg = getattr(e, 'message', None) or str(e)
        code = getattr(e, 'code', '') or ''
        passed = expect == 'blocked'
        detail = f'denied: {code} {msg}'.strip()[:90]
    results.append(passed)
    icon = ('✅' if expect == 'allowed' else '🔒') if passed else '❌ FAIL'
    print(f'  {icon}  {name}\n        → {detail}')


def anon_client():
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def reset_test_users(admin):
    """Delete and recreate test users with fresh random passwords."""
    existing = {u.email: u.id for u in admin.auth.admin.list_users() if u.email in TEST_USERS}
    for uid in existing.values():
        admin.auth.admin.delete_user(uid)
    creds = {}
    for email in TEST_USERS:
        password = pysecrets.token_urlsafe(24)
        admin.auth.admin.create_user({'email': email, 'password': password, 'email_confirm': True})
        creds[email] = password
    return creds


def signed_in_client(email, password):
    client = anon_client()
    client.auth.sign_in_with_password({'email': email, 'password': password})
    return client


def main():
    print('=' * 60)
    print('RLS Proof Test (all checks use the public anon key)')
    print('=' * 60)

    # ---------- Anonymous visitor ----------
    anon = anon_client()
    print('\n👤 Anonymous visitor (anon key, no login)')
    check('can insert a page view', 'allowed', lambda: anon.table('page_views').insert(
        {'page_url': 'https://test/rls', 'user_agent': 'test_rls.py'},
        returning=ReturnMethod.minimal).execute() and 'inserted')
    check('can call page_view_count()', 'allowed', lambda: anon.rpc('page_view_count').execute().data)
    check('cannot read page_views rows (visitor user agents)', 'blocked',
          lambda: anon.table('page_views').select('*').limit(5).execute())
    check('cannot forge visited_at on a page view', 'blocked', lambda: anon.table('page_views').insert(
        {'page_url': 'https://test/rls', 'user_agent': 'x', 'visited_at': '2000-01-01T00:00:00Z'},
        returning=ReturnMethod.minimal).execute() and 'inserted')
    check('cannot insert an oversized page_url (CHECK constraint)', 'blocked', lambda: anon.table('page_views').insert(
        {'page_url': 'x' * 600, 'user_agent': 'x'}, returning=ReturnMethod.minimal).execute() and 'inserted')
    check('cannot read sentence_embeddings', 'blocked',
          lambda: anon.table('sentence_embeddings').select('*').limit(5).execute())
    check('cannot call match_sentences()', 'blocked',
          lambda: anon.rpc('match_sentences', {'query_embedding': PROBE_VECTOR, 'match_count': 5}).execute())
    check('cannot insert into sentence_embeddings', 'blocked', lambda: anon.table('sentence_embeddings').insert(
        {'talk_id': '00000000-0000-0000-0000-000000000000', 'title': 'hacked', 'text': 'hacked'},
        returning=ReturnMethod.minimal).execute() and 'inserted')

    # ---------- Logged-in user ----------
    admin = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    creds = reset_test_users(admin)
    email_a = TEST_USERS[0]
    user_a = signed_in_client(email_a, creds[email_a])

    print(f'\n🔑 Logged-in user ({email_a}, anon key + user JWT)')
    check('can read sentence_embeddings', 'allowed',
          lambda: user_a.table('sentence_embeddings').select('id, title').limit(5).execute())
    check('can call match_sentences()', 'allowed',
          lambda: user_a.rpc('match_sentences', {'query_embedding': PROBE_VECTOR, 'match_count': 5}).execute())
    check('match_sentences() caps match_count at 50', 'allowed',
          lambda: (lambda n: n if n <= 50 else (_ for _ in ()).throw(AssertionError(f'{n} rows > 50')))(
              len(user_a.rpc('match_sentences', {'query_embedding': PROBE_VECTOR, 'match_count': 5000}).execute().data)))
    check('cannot insert into sentence_embeddings', 'blocked', lambda: user_a.table('sentence_embeddings').insert(
        {'talk_id': '00000000-0000-0000-0000-000000000000', 'title': 'hacked', 'text': 'hacked'},
        returning=ReturnMethod.minimal).execute() and 'inserted')
    check('cannot delete from sentence_embeddings', 'blocked',
          lambda: user_a.table('sentence_embeddings').delete().neq('title', '').execute())
    check('cannot read page_views rows', 'blocked',
          lambda: user_a.table('page_views').select('*').limit(5).execute())

    # ---------- Per-user history: user A vs user B ----------
    email_b = TEST_USERS[1]
    user_b = signed_in_client(email_b, creds[email_b])
    user_b_id = user_b.auth.get_user().user.id
    row = user_a.table('question_history').insert(
        {'question': 'RLS test question', 'answer': 'secret answer for A only', 'sources': []}).execute().data[0]
    a_row_id = row['id']

    def expect_rows(result):
        if not result.data:
            raise AssertionError('expected rows, got none')
        return result

    print(f'\n📜 question_history: {email_a} (A) vs {email_b} (B)')
    check("A can read A's own row", 'allowed',
          lambda: expect_rows(user_a.table('question_history').select('id, question').eq('id', a_row_id).execute()))
    check("B cannot read A's row (even by exact id)", 'blocked',
          lambda: user_b.table('question_history').select('*').eq('id', a_row_id).execute())
    check("B listing all history sees none of A's rows", 'blocked',
          lambda: user_b.table('question_history').select('*').execute())
    check("B cannot delete A's row (0 rows affected)", 'blocked',
          lambda: user_b.table('question_history').delete().eq('id', a_row_id).execute())
    check("…and A's row still exists afterwards", 'allowed',
          lambda: expect_rows(user_a.table('question_history').select('id').eq('id', a_row_id).execute()))
    check("B cannot update A's row (no UPDATE grant/policy)", 'blocked',
          lambda: user_b.table('question_history').update({'answer': 'hacked'}).eq('id', a_row_id).execute())
    check('A cannot insert a row owned by B (user_id not insertable)', 'blocked',
          lambda: user_a.table('question_history').insert(
              {'question': 'x', 'answer': 'x', 'sources': [], 'user_id': user_b_id}).execute())
    check('A cannot backdate created_at', 'blocked',
          lambda: user_a.table('question_history').insert(
              {'question': 'x', 'answer': 'x', 'sources': [], 'created_at': '2000-01-01T00:00:00Z'}).execute())
    check('anonymous visitor cannot read any history', 'blocked',
          lambda: anon.table('question_history').select('*').execute())
    check('A can delete own row', 'allowed',
          lambda: expect_rows(user_a.table('question_history').delete().eq('id', a_row_id).execute()))

    # ---------- Server-only tables ----------
    print('\n🗄️  Server-only tables (Edge Functions via service_role only)')
    check('user cannot read question_embeddings_cache', 'blocked',
          lambda: user_a.table('question_embeddings_cache').select('question_hash').limit(1).execute())
    check('user cannot poison question_embeddings_cache', 'blocked',
          lambda: user_a.table('question_embeddings_cache').insert(
              {'question_hash': 'x', 'embedding': PROBE_VECTOR}, returning=ReturnMethod.minimal).execute() and 'inserted')
    check('user cannot read api_usage (rate-limit log)', 'blocked',
          lambda: user_a.table('api_usage').select('*').limit(1).execute())
    check('user cannot delete api_usage rows to reset their limit', 'blocked',
          lambda: user_a.table('api_usage').delete().neq('fn', '').execute())
    check("user cannot call consume_rate_limit() (would burn others' quota)", 'blocked',
          lambda: user_a.rpc('consume_rate_limit', {'p_user_id': user_b_id, 'p_fn': 'generate-answer',
                                                    'p_limit': 30, 'p_window': '1 hour'}).execute())

    # ---------- Summary ----------
    passed = sum(results)
    print('\n' + '=' * 60)
    print(f'{passed}/{len(results)} checks passed')
    print('=' * 60)
    sys.exit(0 if passed == len(results) else 1)


if __name__ == '__main__':
    main()
