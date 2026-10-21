"""
Edge Function Security Test
===========================
Calls the deployed functions the way different callers would:
no token, the public anon key, a signed-in user, bad input, and a foreign
website's CORS preflight. Prints status codes only, never tokens.

Usage:
    python scripts/test_functions.py
"""

import json
import secrets as pysecrets
import sys
import warnings

warnings.filterwarnings('ignore')

import requests
from supabase import create_client

with open('config.public.json', 'r') as f:
    public_config = json.load(f)
with open('config.secret.json', 'r') as f:
    secret_config = json.load(f)

SUPABASE_URL = public_config['SUPABASE_URL']
SUPABASE_ANON_KEY = public_config['SUPABASE_ANON_KEY']
SUPABASE_SERVICE_KEY = secret_config['SUPABASE_SERVICE_KEY']
FUNCTIONS_URL = f'{SUPABASE_URL}/functions/v1'
SITE_ORIGIN = 'https://trevorwattles.github.io'
TEST_EMAIL = 'rls-test-a@example.com'

results = []


def check(name, expected_status, resp, extra=None):
    detail = extra(resp) if extra and resp.status_code == expected_status else resp.text[:80]
    passed = resp.status_code == expected_status
    results.append(passed)
    print(f"  {'✅' if passed else '❌ FAIL'}  {name}\n        → HTTP {resp.status_code} {detail}")


def user_token():
    """Sign in as the throwaway test user (reset password via admin API)."""
    admin = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    user = next((u for u in admin.auth.admin.list_users() if u.email == TEST_EMAIL), None)
    password = pysecrets.token_urlsafe(24)
    if user:
        admin.auth.admin.update_user_by_id(user.id, {'password': password})
    else:
        admin.auth.admin.create_user({'email': TEST_EMAIL, 'password': password, 'email_confirm': True})
    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    return client.auth.sign_in_with_password({'email': TEST_EMAIL, 'password': password}).session.access_token


def post(fn, body, token=None):
    headers = {'Content-Type': 'application/json', 'apikey': SUPABASE_ANON_KEY, 'Origin': SITE_ORIGIN}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return requests.post(f'{FUNCTIONS_URL}/{fn}', headers=headers, json=body, timeout=60)


def test_embed_question(token):
    fn = 'embed-question'
    print(f'\n🧠 {fn}')
    check('no token → 401', 401, post(fn, {'question': 'peace'}))
    check('anon key as token (no user) → 401', 401, post(fn, {'question': 'peace'}, SUPABASE_ANON_KEY))
    check('signed-in user → 200 with 1536-dim embedding', 200, post(fn, {'question': 'peace'}, token),
          lambda r: f"(dims={len(r.json()['embedding'])})")
    check('empty question → 400', 400, post(fn, {'question': '   '}, token))
    check('question > 1000 chars → 400', 400, post(fn, {'question': 'x' * 1001}, token))
    check('non-string question → 400', 400, post(fn, {'question': {'$ne': 1}}, token))

    evil = requests.options(f'{FUNCTIONS_URL}/{fn}', timeout=30, headers={
        'Origin': 'https://evil.example.com', 'Access-Control-Request-Method': 'POST'})
    allowed = evil.headers.get('Access-Control-Allow-Origin')
    passed = allowed != 'https://evil.example.com' and allowed != '*'
    results.append(passed)
    print(f"  {'✅' if passed else '❌ FAIL'}  CORS preflight from evil.example.com is not allowed\n"
          f"        → Access-Control-Allow-Origin: {allowed}")


def test_generate_answer(token):
    fn = 'generate-answer'
    talk = {'title': 'Test Talk on Prayer', 'speaker': 'Elder Tester',
            'text': 'Prayer is how we speak with our Heavenly Father. Pray morning and night, '
                    'and listen for answers that come as peace.'}
    snippet = lambda r: f"\n          \"{r.json()['answer'][:160]}…\""
    print(f'\n🤖 {fn}')
    check('no token → 401', 401, post(fn, {'question': 'prayer', 'context_talks': [talk]}))
    check('empty context_talks → 400 (readiness probe, no GPT call)', 400,
          post(fn, {'question': 'test', 'context_talks': []}, token))
    check('6 talks (> 5) → 400', 400, post(fn, {'question': 'prayer', 'context_talks': [talk] * 6}, token))
    check('context over 60k chars → 400', 400, post(fn, {'question': 'prayer', 'context_talks': [
        {**talk, 'text': 'x' * 31_000}, {**talk, 'text': 'x' * 31_000}]}, token))
    check('talk missing text → 400', 400, post(fn, {'question': 'prayer', 'context_talks': [{'title': 'x'}]}, token))
    check('grounded question → 200, cites the talk', 200,
          post(fn, {'question': 'What does the talk teach about prayer?', 'context_talks': [talk]}, token), snippet)
    check('off-topic question → 200, should decline (read it!)', 200,
          post(fn, {'question': 'What is the capital of France?', 'context_talks': [talk]}, token), snippet)


def main():
    print('=' * 60)
    print('Edge Function Security Test')
    print('=' * 60)
    token = user_token()
    test_embed_question(token)
    test_generate_answer(token)

    passed = sum(results)
    print('\n' + '=' * 60)
    print(f'{passed}/{len(results)} checks passed')
    print('=' * 60)
    sys.exit(0 if passed == len(results) else 1)


if __name__ == '__main__':
    main()
