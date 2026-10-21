"""
Show how Postgres executes the app's search queries (EXPLAIN ANALYZE)
=====================================================================
Run before and after adding an index to see the plan change.

Usage:
    python scripts/explain_search.py keyword faith Kirtland xylophone
    python scripts/explain_search.py vector peace prayer temple
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


def vector_sql(vec_literal):
    # Same body as match_sentences(), with the default match_count of 20.
    return (f"SELECT id, 1 - (embedding <=> '{vec_literal}') AS similarity "
            f"FROM sentence_embeddings WHERE embedding IS NOT NULL "
            f"ORDER BY embedding <=> '{vec_literal}' LIMIT 20")


def sample_vector(term):
    """Use a stored sentence's embedding as the query (no OpenAI call needed)."""
    term = term.replace("'", "''")
    rows = run_sql(f"SELECT embedding::text AS v FROM sentence_embeddings "
                   f"WHERE text ILIKE '%{term}%' AND embedding IS NOT NULL LIMIT 1")
    if not rows:
        sys.exit(f"No embedded sentence contains '{term}'")
    return rows[0]['v']


def recall_vs_exact(vec_literal):
    """Fraction of the exact top-20 that match_sentences() (HNSW if present) also returns."""
    # "+ 0" makes the sort key an expression the index can't serve → exact scan.
    exact = run_sql(f"SELECT id FROM sentence_embeddings WHERE embedding IS NOT NULL "
                    f"ORDER BY (embedding <=> '{vec_literal}') + 0 LIMIT 20")
    app = run_sql(f"SELECT id FROM match_sentences('{vec_literal}', 20)")
    exact_ids = {r['id'] for r in exact}
    return len(exact_ids & {r['id'] for r in app}) / max(len(exact_ids), 1)


if __name__ == '__main__':
    if len(sys.argv) < 3 or sys.argv[1] not in ('keyword', 'vector'):
        print(__doc__)
        sys.exit(1)
    mode = sys.argv[1]
    for term in sys.argv[2:]:
        if mode == 'keyword':
            ms, nodes = explain(keyword_sql(term))
            print(f"\n🔍 ILIKE '%{term}%'  →  {ms:.2f} ms")
        else:
            vec = sample_vector(term)
            cold_ms, _ = explain(vector_sql(vec))
            ms, nodes = explain(vector_sql(vec))
            # Recall runs last: its exact scan pulls the whole table through the
            # cache and evicts the index, which would skew the next timing.
            print(f"\n🧠 nearest 20 to a sentence about '{term}'  →  {ms:.2f} ms warm "
                  f"({cold_ms:.0f} ms cold)  (recall vs exact: {recall_vs_exact(vec):.0%})")
        for line in nodes:
            print(f"     {line}")
