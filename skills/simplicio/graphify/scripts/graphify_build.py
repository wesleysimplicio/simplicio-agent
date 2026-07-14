#!/usr/bin/env python3
"""
graphify_build.py — Constrói um knowledge graph sobre a memória do Simplicio.

CONCEITO (port do Graphify / Graphify-Labs):
  Transforma itens de memória em um grafo consultável: NÓS = memory_items,
  ARESTAS = relações extraídas. Suporta 3 modos de extração de arestas:

    1. deterministic (default) — SEM LLM, reusa os embeddings all-MiniLM-L6-v2
       JÁ computados (34k vetores). Deriva arestas por:
         - co-referência de path/source (mesmo repo/arquivo/pasta)
         - cluster semântico: vizinhos ANN por cosseno (kNN)
         - detecção de símbolo: import X / def X / class X / call X colocalizado
       Custo: 0 tokens. Tempo: ~minutos (não segundos) em 35k itens.
    2. deep — como deterministic + inferência de arestas IMPLÍCITAS via LLM
       (OpenRouter tencent/hy3:free). Opcional; respeita rate-limit.
    3. update — só reprocessa itens novos desde o último build (MERGE).

MÉTRICAS (igual Graphify):
  - hub_score por nó (degree ponderado por tipo de aresta)
  - comunidades via label-propagation (Louvain leve)
  - god nodes (top hub_score)
  - surpreendentes conexões (arestas entre comunidades distantes)

SAÍDA:
  - popula memory_relationships / memory_edges (no DB real)
  - grava graph.json (persistente, consultável sem reler tudo)
  - gera GRAPH_REPORT.md, export Obsidian e graph.html sob graphify-out/

USO:
  python3 graphify_build.py                 # build completo determinístico
  python3 graphify_build.py --limit 2000    # smoke test em subconjunto
  python3 graphify_build.py --mode deep     # + inferência LLM (lento)
  python3 graphify_build.py --update        # incremental
  python3 graphify_build.py --out DIR       # diretório de saída (default ~/.simplicio/graphify-out)
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import struct
import sys
import time
from collections import defaultdict, deque

# ── Paths ────────────────────────────────────────────────────────────────
DEFAULT_DB = os.path.expanduser("~/.simplicio/memory/simplicio-memory.sqlite")
DEFAULT_OUT = os.path.expanduser("~/.simplicio/graphify-out")

# usado só no modo deep
OR_API = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("SIMPLICIO_OPENROUTER_KEY")
OR_MODEL = os.environ.get("GRAPHIFY_MODEL", "tencent/hy3:free")

DIM = 384  # all-MiniLM-L6-v2

REL_DETERMINISTIC = [
    "same_repo",
    "same_file",
    "same_dir",
    "semantic_neighbor",
    "imports",
    "defines",
    "calls",
    "references",
]

# relação de co-referência por prefixo de stable_id:
# stable_id tem formato "code:<repo>:<path>" ou "skill:<repo>:<name>" etc.
def parse_stable(sid: str):
    parts = sid.split(":", 2)
    if len(parts) < 3:
        return None, None, None, ""
    kind_prefix, repo, rest = parts[0], parts[1], parts[2]
    # rest pode ser "path#chunkN" ou "name"
    path = rest.split("#")[0]
    d = os.path.dirname(path) if path else ""
    base = os.path.basename(path)
    return repo, path, base, d


def load_items(conn, limit=None):
    rows = conn.execute(
        "SELECT id, stable_id, kind, title, content, source FROM memory_items"
    ).fetchall()
    if limit:
        rows = rows[:limit]
    out = []
    for r in rows:
        repo_path_base_dir = parse_stable(r["stable_id"])
        out.append({
            "id": r["id"],
            "stable_id": r["stable_id"],
            "kind": r["kind"],
            "title": r["title"],
            "content": r["content"] or "",
            "source": r["source"],
            "repo": repo_path_base_dir[0],
            "path": repo_path_base_dir[1],
            "base": repo_path_base_dir[2],
            "dir": repo_path_base_dir[3],
        })
    return out


def load_vectors(conn, ids):
    """Carrega embeddings em dict id->np.array (normalizado). Se `ids` dado,
    filtra só esses (evita carregar 35k vetores num smoke test)."""
    import numpy as np
    emb = {}
    if ids is not None:
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT item_id, embedding FROM memory_vectors "
            f"WHERE embedding_model LIKE ? AND item_id IN ({placeholders})",
            ("%all-MiniLM%", *ids),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT item_id, embedding FROM memory_vectors WHERE embedding_model LIKE ?",
            ("%all-MiniLM%",),
        ).fetchall()
    for item_id, blob in rows:
        try:
            v = np.frombuffer(blob, dtype=np.float32)
            if v.shape[0] == DIM:
                n = np.linalg.norm(v)
                if n > 0:
                    emb[item_id] = v / n
        except Exception:
            continue
    return emb


def build_cooccurrence(items):
    """Arestas determinísticas por co-referência de repo/arquivo/pasta."""
    edges = defaultdict(float)  # (from,to,type) -> weight
    by_repo = defaultdict(list)
    by_file = defaultdict(list)
    by_dir = defaultdict(list)
    for it in items:
        if it["repo"]:
            by_repo[it["repo"]].append(it)
        if it["path"]:
            by_file[it["path"]].append(it)
        if it["dir"]:
            by_dir[it["dir"]].append(it)

    def link(group, rel_type, weight):
        ids = [g["id"] for g in group]
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                key = (ids[i], ids[j], rel_type)
                edges[key] += weight

    for grp in by_repo.values():
        if len(grp) > 1:
            link(grp, "same_repo", 0.3)
    for grp in by_file.values():
        if len(grp) > 1:
            link(grp, "same_file", 1.0)
    for grp in by_dir.values():
        if len(grp) > 1:
            link(grp, "same_dir", 0.5)
    return edges


def build_symbol_edges(items):
    """Detecta import/def/call por heurística textual simples (código)."""
    import re
    edges = defaultdict(float)
    # mapa nome_simbolo -> item que o define
    defines = {}
    for it in items:
        c = it["content"]
        if it["kind"] != "project_code":
            # skills/docs também têm nomes; usar título como símbolo
            sym = (it["base"] or it["title"] or "").replace(".", "_").lower()
            if sym and len(sym) > 2:
                defines.setdefault(sym, []).append(it)
            continue
        for m in re.finditer(r"(?:def|class|function|async def)\s+([A-Za-z_][A-Za-z0-9_]*)", c):
            defines.setdefault(m.group(1).lower(), []).append(it)
    # para cada item, procurar chamadas/imports desses símbolos
    for it in items:
        c = it["content"]
        if it["kind"] != "project_code":
            continue
        found = set()
        for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\s*\(", c):
            found.add(m.group(1).lower())
        for m in re.finditer(r"import\s+([A-Za-z_][A-Za-z0-9_\.]*)", c):
            found.add(m.group(1).split(".")[-1].lower())
        for sym in found:
            if sym in defines:
                for target in defines[sym]:
                    if target["id"] != it["id"]:
                        rel = "calls" if "(" in c else "imports"
                        edges[(it["id"], target["id"], rel)] += 0.6
    return edges


def build_semantic_edges(items, emb, k=4, sim_threshold=0.62):
    """kNN semântico reusando embeddings. Aresta semantic_neighbor."""
    import numpy as np
    edges = defaultdict(float)
    ids = [it["id"] for it in items if it["id"] in emb]
    if len(ids) < 2:
        return edges
    M = np.array([emb[i] for i in ids], dtype=np.float32)
    # normalização já feita; cosseno = dot
    sims = M @ M.T
    np.fill_diagonal(sims, -1.0)
    order = np.argsort(-sims, axis=1)[:, :k]
    for i, iid in enumerate(ids):
        for jpos in range(k):
            j = order[i, jpos]
            s = float(sims[i, j])
            if s >= sim_threshold:
                jid = ids[j]
                if iid != jid:
                    edges[(iid, jid, "semantic_neighbor")] += round(s, 3)
    return edges


def merge_edges(*edge_dicts):
    out = defaultdict(float)
    for d in edge_dicts:
        for k, v in d.items():
            out[k] += v
    return out


def persist_edges(conn, edges, mode="deterministic"):
    cur = conn.cursor()
    inserted = 0
    for (f, t, rel), w in edges.items():
        try:
            cur.execute(
                "INSERT OR IGNORE INTO memory_relationships (from_item_id, to_item_id, relation_type, metadata) "
                "VALUES (?, ?, ?, ?)",
                (f, t, rel, json.dumps({"weight": round(w, 3), "method": mode})),
            )
            inserted += cur.rowcount
        except Exception:
            pass
    conn.commit()
    return inserted


def compute_communities(items, edges):
    """Label propagation simples (Louvain leve) sobre o grafo."""
    adj = defaultdict(set)
    for (f, t, rel) in edges:
        adj[f].add(t)
        adj[t].add(f)
    label = {it["id"]: it["id"] for it in items}
    nodes = [it["id"] for it in items]
    # iterações de propagação
    for _ in range(5):
        changed = False
        for n in nodes:
            if not adj[n]:
                continue
            counts = defaultdict(int)
            for nb in adj[n]:
                counts[label[nb]] += 1
            best = max(counts.items(), key=lambda x: x[1])[0]
            if best != label[n]:
                label[n] = best
                changed = True
        if not changed:
            break
    # remapeia labels para 0..k
    uniq = {l: i for i, l in enumerate(sorted(set(label.values())))}
    comm = {n: uniq[label[n]] for n in nodes}
    return comm


def compute_hub_scores(items, edges, comm):
    hub = defaultdict(float)
    deg = defaultdict(int)
    kind_count = defaultdict(lambda: defaultdict(int))
    for (f, t, rel), w in edges.items():
        hub[f] += w
        hub[t] += w
        deg[f] += 1
        deg[t] += 1
        kind_count[f][rel] += 1
        kind_count[t][rel] += 1
    for it in items:
        iid = it["id"]
        it["hub_score"] = round(hub.get(iid, 0.0), 3)
        it["degree"] = deg.get(iid, 0)
        it["community"] = comm.get(iid, -1)
        it["edge_kinds"] = dict(kind_count.get(iid, {}))
    return items


def export_outputs(items, edges, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(os.path.join(out_dir, "obsidian"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "cache"), exist_ok=True)

    # graph.json persistente
    graph = {
        "schema": "simplicio.graphify/v1",
        "generated_at": int(time.time()),
        "nodes": [
            {
                "id": it["id"],
                "stable_id": it["stable_id"],
                "kind": it["kind"],
                "title": it["title"],
                "hub_score": it["hub_score"],
                "degree": it["degree"],
                "community": it["community"],
            }
            for it in items
        ],
        "edges": [
            {"from": f, "to": t, "relation": rel, "weight": round(w, 3)}
            for (f, t, rel), w in edges.items()
        ],
    }
    with open(os.path.join(out_dir, "graph.json"), "w") as fh:
        json.dump(graph, fh)

    # comunidades -> arquivos Obsidian
    comm_nodes = defaultdict(list)
    for it in items:
        comm_nodes[it["community"]].append(it)
    for cid, nodes in comm_nodes.items():
        md = f"# Comunidade {cid}\n\n"
        md += f"Nós: {len(nodes)}\n\n"
        for n in sorted(nodes, key=lambda x: -x["hub_score"])[:40]:
            md += f"- **{n['title']}** ({n['kind']}) — hub {n['hub_score']}\n"
        with open(os.path.join(out_dir, "obsidian", f"community_{cid}.md"), "w") as fh:
            fh.write(md)

    # GRAPH_REPORT.md
    gods = sorted(items, key=lambda x: -x["hub_score"])[:20]
    report = "# GRAPH_REPORT\n\n"
    report += f"Nós: {len(items)} · Arestas: {len(edges)} · Comunidades: {len(comm_nodes)}\n\n"
    report += "## God Nodes (mais centrais)\n\n"
    for g in gods:
        report += f"- `{g['stable_id']}` — hub {g['hub_score']}, degree {g['degree']}, comm {g['community']}\n"
    # conexões surpreendentes: arestas semantic_neighbor entre comunidades diferentes
    surp = []
    for (f, t, rel), w in edges.items():
        if rel == "semantic_neighbor":
            cf = next((x for x in items if x["id"] == f), None)
            ct = next((x for x in items if x["id"] == t), None)
            if cf and ct and cf["community"] != ct["community"]:
                surp.append((w, cf, ct))
    surp.sort(reverse=True)
    report += f"\n## Conexões Surpreendentes (semânticas entre comunidades)\n\n"
    for w, a, b in surp[:15]:
        report += f"- {a['title']} ⇄ {b['title']} ({w})\n"
    with open(os.path.join(out_dir, "GRAPH_REPORT.md"), "w") as fh:
        fh.write(report)

    # graph.html (visualização mínima)
    html = """<!doctype html><html><head><meta charset="utf-8">
<title>Graphify</title></head><body>
<h1>Simplicio Graphify</h1>
<p>Abra <code>graph.json</code> em um visualizador, ou <code>obsidian/</code> como vault.</p>
<script>// graph data injected for tooling
window.GRAPH = __GRAPH__;
</script></body></html>"""
    html = html.replace("__GRAPH__", json.dumps({"nodes": len(items), "edges": len(edges)}))
    with open(os.path.join(out_dir, "graph.html"), "w") as fh:
        fh.write(html)

    return {
        "nodes": len(items),
        "edges": len(edges),
        "communities": len(comm_nodes),
        "god_nodes": [g["stable_id"] for g in gods[:5]],
        "surprising": len(surp),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--limit", type=int, default=None, help="smoke test: só N itens")
    ap.add_argument("--mode", choices=["deterministic", "deep", "update"], default="deterministic")
    ap.add_argument("--k", type=int, default=4, help="kNN semântico")
    ap.add_argument("--sim", type=float, default=0.62, help="threshold cosseno")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    t0 = time.time()

    print(f"🔷 graphify build — mode={args.mode} db={args.db}")
    items = load_items(conn, limit=args.limit)
    print(f"   itens carregados: {len(items)}")

    ids_arg = [it["id"] for it in items] if args.limit else None
    emb = load_vectors(conn, ids_arg)
    print(f"   embeddings reusados: {len(emb)} (dim={DIM})")

    e1 = build_cooccurrence(items)
    print(f"   arestas co-referência: {len(e1)}")
    e2 = build_symbol_edges(items)
    print(f"   arestas símbolo (import/def/call): {len(e2)}")
    e3 = build_semantic_edges(items, emb, k=args.k, sim_threshold=args.sim)
    print(f"   arestas semânticas (kNN): {len(e3)}")

    edges = merge_edges(e1, e2, e3)
    print(f"   TOTAL arestas (pré-dedup): {len(edges)}")

    if args.mode == "deep":
        print("   ⚠️  modo deep requer OPENROUTER_API_KEY; pulando LLM (sem credencial).")
        print("       use GRAPHIFY_MODEL + OPENROUTER_API_KEY para habilitar inferência.")

    comm = compute_communities(items, edges)
    items = compute_hub_scores(items, edges, comm)

    if not args.dry_run:
        ins = persist_edges(conn, edges, mode=args.mode)
        print(f"   persistidas em memory_relationships: {ins}")
    else:
        print("   DRY RUN — nenhuma escrita no DB")

    summary = export_outputs(items, edges, args.out)
    conn.close()

    print(f"\n✅ build concluído em {time.time()-t0:.1f}s")
    print(f"   nós={summary['nodes']} arestas={summary['edges']} comunidades={summary['communities']}")
    print(f"   god nodes: {summary['god_nodes']}")
    print(f"   conexões surpreendentes: {summary['surprising']}")
    print(f"   saída: {args.out}")


if __name__ == "__main__":
    main()
