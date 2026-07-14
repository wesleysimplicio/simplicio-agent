#!/usr/bin/env python3
"""
graphify_query.py — Consulta o knowledge graph construído pelo graphify_build.py.

PORT do Graphify (Graphify-Labs):
  graphify query  "o que conecta X a Y?"  -> nós/arestas relevantes + traversal
  graphify path   A B                       -> caminho mais curto entre dois nós
  graphify explain N                        -> vizinhança + comunidade do nó
  graphify report                            -> re-imprime GRAPH_REPORT.md
  graphify export --obsidian / --html       -> gera saídas

Lê memory_relationships (grafo vivo) + graph.json (cache persistente).
Combina grafo com neural-recall: ao achar nós por similaridade, expande
vizinhos do grafo (1-hop e 2-hop) para dar contexto relacional.

USO:
  python3 graphify_query.py query "retry policy" [--hops 2] [--json]
  python3 graphify_query.py path "code:repo:a.py" "code:repo:b.py"
  python3 graphify_query.py explain "skill:simplicio-runtime:graphify"
  python3 graphify_query.py report
  python3 graphify_query.py export --obsidian
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

DEFAULT_DB = os.path.expanduser("~/.simplicio/memory/simplicio-memory.sqlite")
DEFAULT_OUT = os.path.expanduser("~/.simplicio/graphify-out")


def connect(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return conn


def item_by_query(conn, text, limit=10):
    """Usa FTS5 para achar nós por texto (semantic/lexical leve)."""
    try:
        q = " OR ".join(f'"{w}"' for w in text.split() if len(w) > 1) or f'"{text}"'
        rows = conn.execute(
            "SELECT mi.id, mi.stable_id, mi.kind, mi.title FROM memory_items_fts "
            "JOIN memory_items mi ON memory_items_fts.rowid = mi.id "
            "WHERE memory_items_fts MATCH ? ORDER BY rank LIMIT ?",
            (q, limit),
        ).fetchall()
        return rows
    except Exception:
        return []


def neighbors(conn, item_id, hops=1):
    """Retorna dicionário hop -> lista de (neighbor_id, relation, weight)."""
    adj = defaultdict(list)
    rows = conn.execute(
        "SELECT from_item_id, to_item_id, relation_type, metadata FROM memory_relationships"
    ).fetchall()
    for r in rows:
        meta = json.loads(r["metadata"] or "{}")
        w = meta.get("weight", 1.0)
        adj[r["from_item_id"]].append((r["to_item_id"], r["relation_type"], w))
        adj[r["to_item_id"]].append((r["from_item_id"], r["relation_type"], w))

    result = defaultdict(list)
    visited = {item_id}
    frontier = [item_id]
    for h in range(1, hops + 1):
        nxt = []
        for nid in frontier:
            for (nb, rel, w) in adj.get(nid, []):
                result[h].append((nb, rel, w, nid))
                if nb not in visited:
                    visited.add(nb)
                    nxt.append(nb)
        frontier = nxt
    return result, adj


def title_of(conn, iid):
    r = conn.execute(
        "SELECT stable_id, kind, title FROM memory_items WHERE id=?", (iid,)
    ).fetchone()
    return r


from collections import defaultdict


def cmd_query(conn, text, hops=2, json_out=False):
    seeds = item_by_query(conn, text, limit=8)
    if not seeds:
        print("⚠️  nenhum nó encontrado para a query.")
        return
    all_hits = []
    for s in seeds:
        iid = s["id"]
        res, _ = neighbors(conn, iid, hops=hops)
        titles = {}
        flat = []
        for h, lst in res.items():
            for (nb, rel, w, src) in lst:
                if nb not in titles:
                    t = title_of(conn, nb)
                    titles[nb] = t
                flat.append({"hop": h, "neighbor": nb, "relation": rel,
                             "weight": w, "from": src})
        all_hits.append({
            "seed": {"id": iid, "stable_id": s["stable_id"], "title": s["title"], "kind": s["kind"]},
            "neighbors": len(titles),
            "edges": len(flat),
        })
        if not json_out:
            print(f"\n🔹 seed: {s['stable_id']} ({s['kind']})")
            print(f"   vizinhos ({hops}-hop): {len(titles)} · arestas: {len(flat)}")
            for h in range(1, hops + 1):
                for (nb, rel, w, src) in res[h][:6]:
                    t = titles[nb]
                    print(f"     [{h}] {rel}: {t['stable_id']} ({t['kind']}) w={w}")
    if json_out:
        print(json.dumps({"query": text, "seeds": all_hits}, indent=2))


def cmd_path(conn, a_id, b_id):
    """BFS caminho mais curto entre dois stable_ids ou ids."""
    def resolve(x):
        if x.isdigit():
            return int(x)
        r = conn.execute("SELECT id FROM memory_items WHERE stable_id=?", (x,)).fetchone()
        return r["id"] if r else None
    aid = resolve(a_id)
    bid = resolve(b_id)
    if aid is None or bid is None:
        print("⚠️  não consegui resolver um dos nós (use stable_id ou id).")
        return
    rows = conn.execute(
        "SELECT from_item_id, to_item_id, relation_type FROM memory_relationships"
    ).fetchall()
    adj = defaultdict(list)
    for r in rows:
        adj[r["from_item_id"]].append((r["to_item_id"], r["relation_type"]))
        adj[r["to_item_id"]].append((r["from_item_id"], r["relation_type"]))

    prev = {aid: None}
    q = deque([aid])
    while q:
        n = q.popleft()
        if n == bid:
            break
        for (nb, rel) in adj.get(n, []):
            if nb not in prev:
                prev[nb] = (n, rel)
                q.append(nb)
    if bid not in prev:
        print("⚠️  sem caminho entre os nós no grafo atual.")
        return
    path = []
    cur = bid
    while cur is not None:
        path.append(cur)
        p = prev[cur]
        cur = p[0] if p else None
    path.reverse()
    print(f"🔗 caminho ({len(path)-1} arestas):")
    for i, nid in enumerate(path):
        t = title_of(conn, nid)
        if i < len(path) - 1:
            _, rel = prev[path[i + 1]]
            print(f"   {t['stable_id']}  --{rel}-->")
        else:
            print(f"   {t['stable_id']}")


def cmd_explain(conn, node):
    def resolve(x):
        if x.isdigit():
            return int(x)
        r = conn.execute("SELECT id FROM memory_items WHERE stable_id=?", (x,)).fetchone()
        return r["id"] if r else None
    nid = resolve(node)
    if nid is None:
        print("⚠️  nó não encontrado.")
        return
    t = title_of(conn, nid)
    print(f"📌 {t['stable_id']} ({t['kind']})")
    print(f"   title: {t['title']}")
    res, _ = neighbors(conn, nid, hops=1)
    print(f"   grau: {len(res[1])}")
    for (nb, rel, w, src) in sorted(res[1], key=lambda x: -x[2])[:15]:
        nt = title_of(conn, nb)
        print(f"   - {rel} ({w}): {nt['stable_id']}")


def cmd_report(out_dir):
    p = os.path.join(out_dir, "GRAPH_REPORT.md")
    if os.path.exists(p):
        with open(p) as fh:
            print(fh.read())
    else:
        print("⚠️  GRAPH_REPORT.md não encontrado. Rode graphify_build.py primeiro.")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    q = sub.add_parser("query"); q.add_argument("text"); q.add_argument("--hops", type=int, default=2); q.add_argument("--json", action="store_true")
    p = sub.add_parser("path"); p.add_argument("a"); p.add_argument("b")
    e = sub.add_parser("explain"); e.add_argument("node")
    sub.add_parser("report")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    conn = connect(args.db)
    try:
        if args.cmd == "query":
            cmd_query(conn, args.text, hops=args.hops, json_out=args.json)
        elif args.cmd == "path":
            cmd_path(conn, args.a, args.b)
        elif args.cmd == "explain":
            cmd_explain(conn, args.node)
        elif args.cmd == "report":
            cmd_report(args.out)
        else:
            ap.print_help()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
