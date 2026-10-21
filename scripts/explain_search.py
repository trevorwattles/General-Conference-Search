"""
Show how Postgres executes the app's search queries (EXPLAIN ANALYZE)
=====================================================================
Run before and after adding an index to see the plan change.

Usage:
    python scripts/explain_search.py keyword faith Kirtland xylophone
"""

import json
import sys

from run_sql import run_sql


def explain(sql):
    plan = run_sql(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}")[0]['QUERY PLAN'][0]
    nodes = []

    def walk(node, depth=0):
        name = node['Node Type']
        if node.get('Index Name'):
            name += f" using {node['Index Name']}"
        nodes.append(f"{'  ' * depth}{name} (rows={node.get('Actual Rows')}, "
                     f"removed_by_filter={node.get('Rows Removed by Filter', 0)})")
        for child in node.get('Plans', []):
            walk(child, depth + 1)

    walk(plan['Plan'])
    return plan['Execution Time'], nodes


def keyword_sql(term):
    term = term.replace("'", "''")
    return (f"SELECT text, talk_id, title, speaker, url FROM sentence_embeddings "
            f"WHERE text ILIKE '%{term}%' LIMIT 20")


if __name__ == '__main__':
    if len(sys.argv) < 3 or sys.argv[1] != 'keyword':
        print(__doc__)
        sys.exit(1)
    for term in sys.argv[2:]:
        ms, nodes = explain(keyword_sql(term))
        print(f"\n🔍 ILIKE '%{term}%'  →  {ms:.2f} ms")
        for line in nodes:
            print(f"     {line}")
