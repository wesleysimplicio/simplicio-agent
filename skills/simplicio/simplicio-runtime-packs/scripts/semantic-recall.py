#!/usr/bin/env python3
"""semantic_recall.py — Busca semântica ANN com tracking de acesso e decay.

Uso: python3 semantic_recall.py <query> [k=10]

Retorna top-k itens da vec0 ANN index, registra acessos para reforço de decay.
Física: cada recall aquece os itens (access_count++), o decay recalc periódico
traduz esse aquecimento em decay_score mais alto.
"""

import sqlite3, os, sys, struct, time, re

DB = os.path.expanduser("~/.simplicio/memory/simplicio-memory.sqlite")
DIM = 256

def fnv1a(data: bytes) -> int:
    h = 0xcbf29ce484222325
    for b in data:
        h ^= b
        h = (h * 0x100000001b3) & 0xffffffffffffffff
    return h

def embed_text(text: str) -> list[float]:
    """Deterministic embedding: FNV-1a over unigrams + trigrams → 256D L2-normalized."""
    v = [0.0] * DIM
    lower = text.lower()
    for word in re.split(r'[^a-z0-9]', lower):
        if not word: continue
        h = fnv1a(word.encode('utf-8'))
        idx = h % DIM
        sign = 1.0 if (h >> 17) & 1 == 0 else -1.0
        v[idx] += sign
        if len(word) >= 3:
            for i in range(len(word) - 2):
                tri = word[i:i+3]
                h = fnv1a(tri.encode('utf-8'))
                idx = h % DIM
                sign = 1.0 if (h >> 17) & 1 == 0 else -1.0
                v[idx] += sign
    norm = sum(x*x for x in v) ** 0.5
    if norm > 0:
        v = [x / norm for x in v]
    return v

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 semantic_recall.py <query> [k=10]")
        sys.exit(1)
    query = sys.argv[1]
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    conn = sqlite3.connect(DB)
    conn.enable_load_extension(True)
    conn.load_extension(os.path.expanduser("~/.simplicio/ext/vec0.dylib"))

    emb = embed_text(query)
    qblob = struct.pack(f'<{DIM}f', *emb)

    rows = conn.execute(
        "SELECT id, text, distance, tier FROM vec_memory WHERE embedding MATCH ? AND k = ?",
        (qblob, k)
    ).fetchall()

    now = int(time.time())
    print(f"🔍 \"{query[:60]}\" — {len(rows)} hits")
    print(f"{'score':>8} {'tier':<12} {'text'}")
    print("-" * 80)
    for r in rows:
        item_id, text, distance, tier = r
        score = 1.0 - distance
        # Log access
        conn.execute("INSERT INTO access_log (item_id, query, score, tier, accessed_at) VALUES (?,?,?,?,?)",
            (item_id, query[:100], score, tier, now))
        conn.execute("UPDATE vector_memory SET access_count=access_count+1, last_access_at=? WHERE id=?",
            (now, item_id))
        print(f"{score:.4f}  {tier:<12} {text[:70]}")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    main()
