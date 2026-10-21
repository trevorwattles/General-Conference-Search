"""
Run SQL against your Supabase database via the Management API
==============================================================
Same endpoint 01_create_schema.py uses. Reads the access token from
config.secret.json and never prints it.

Usage:
    python scripts/run_sql.py supabase/migrations/0002_hardening.sql
    python scripts/run_sql.py -c "select count(*) from sentence_embeddings"
"""

import json
import sys

import requests

with open('config.secret.json', 'r') as f:
    secrets = json.load(f)

SUPABASE_ACCESS_TOKEN = secrets['SUPABASE_ACCESS_TOKEN']
SUPABASE_PROJECT_REF = secrets['SUPABASE_PROJECT_REF']


def run_sql(sql):
    url = f"https://api.supabase.com/v1/projects/{SUPABASE_PROJECT_REF}/database/query"
    headers = {
        "Authorization": f"Bearer {SUPABASE_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    resp = requests.post(url, headers=headers, json={"query": sql}, timeout=600)
    if resp.status_code not in (200, 201):
        print(f"❌ SQL failed: {resp.status_code}")
        print(resp.text[:2000])
        sys.exit(1)
    return resp.json()


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '-c':
        sql = sys.argv[2]
    elif len(sys.argv) == 2:
        with open(sys.argv[1], 'r') as f:
            sql = f.read()
    else:
        print(__doc__)
        sys.exit(1)

    rows = run_sql(sql)
    if rows:
        for row in rows:
            print(json.dumps(row, default=str))
    else:
        print("✅ OK (no rows returned)")
