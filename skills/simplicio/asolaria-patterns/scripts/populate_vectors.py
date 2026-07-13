#!/usr/bin/env python3
"""Populate vector_memory with deterministic embeddings + physics-based decay + HBP chain.

Replicates embed_text() from src/vector_memory.rs (FNV-1a, 256d, L2-normalized).
Applies Asolaria physics:
  - Decay: salience·e^(-λ·Δt) + σ·ln(1+access)·e^(-μ·days_since_access)
  - Tier classification: Working→Episodic→Semantic→Procedural
  - HBP chain: SHA-256 content-addressed receipts per batch
  - Embedding as field vector in phase space (256D)
"""

import sqlite3
import os, sys, struct, time, re, hashlib
from datetime import datetime, timezone

DB = os.path.expanduser("~/.simplicio/memory/simplicio-memory.sqlite")
BATCH = 500

# ── Physical constants (from Asolaria decay.rs) ──────────────────────────────
LAMBDA = 0.02       # decay rate → 35-day half-life
SIGMA  = 0.6        # access reinforcement magnitude
MU     = 0.04       # access decay rate
SALIENCE_DEFAULT = 1.0

def fnv1a(data: bytes) -> int:
    h = 0xcbf29ce484222325
    for b in data:
        h ^= b
        h = (h * 0x100000001b3) & 0xffffffffffffffff
    return h

def embed_text(text: str, dim: int = 256) -> list[float]:
    v = [0.0] * dim
    lower = text.lower()
    for word in re.split(r'[^a-z0-9]', lower):
        if not word: continue
        h = fnv1a(word.encode('utf-8'))
        idx = h % dim
        sign = 1.0 if (h >> 17) & 1 == 0 else -1.0
        v[idx] += sign
        if len(word) >= 3:
            for i in range(len(word)-2):
                tri = word[i:i+3]; h = fnv1a(tri.encode('utf-8'))
                idx = h % dim; sign = 1.0 if (h >> 17) & 1 == 0 else -1.0
                v[idx] += sign
    norm = sum(x*x for x in v)**0.5
    return [x/norm for x in v] if norm > 0 else v

def encode_embedding(emb: list[float]) -> bytes:
    return struct.pack(f'<{len(emb)}f', *emb)

def decay_score(age_days: float, access_count: int, days_since_access: float | None) -> float:
    import math
    time_term = SALIENCE_DEFAULT * math.exp(-LAMBDA * age_days)
    if days_since_access is not None and days_since_access >= 0:
        access_term = SIGMA * math.log1p(access_count) * math.exp(-MU * days_since_access)
    else:
        access_term = 0.0
    return time_term + access_term

def classify_tier(kind: str, content_len: int, decay: float) -> str:
    if kind in ('agent_state', 'conversation', 'chat-note'):
        return 'working' if decay > 0.5 else 'episodic'
    if kind in ('skill', 'skill_catalog', 'project_skill'):
        return 'procedural'
    if kind in ('decision', 'fact', 'pattern', 'rule'):
        return 'semantic'
    if kind in ('project_code', 'code', 'git_commit'):
        return 'episodic' if content_len < 500 else 'semantic'
    return 'episodic'

def hbp_hash(seq: int, prev_hash: str, topic: str, payload: str) -> str:
    h = hashlib.sha256()
    for field in [str(seq), prev_hash, topic, payload]:
        h.update(len(field).to_bytes(8, 'little'))
        h.update(field.encode())
    return h.hexdigest()

def hbp_init(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hbp_chain (
            seq INTEGER PRIMARY KEY, topic TEXT NOT NULL,
            payload TEXT NOT NULL, prev_hash TEXT NOT NULL,
            hash TEXT NOT NULL UNIQUE,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    if conn.execute("SELECT COUNT(*) FROM hbp_chain").fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO hbp_chain (seq, topic, payload, prev_hash, hash) VALUES (0, 'genesis', 'vector_memory_populate', 'genesis', ?)",
            (hbp_hash(0, 'genesis', 'genesis', 'vector_memory_populate'),)
        )
        conn.commit()

def hbp_append(conn, topic, payload):
    last = conn.execute("SELECT seq, hash FROM hbp_chain ORDER BY seq DESC LIMIT 1").fetchone()
    seq = (last[0] + 1) if last else 0
    prev = last[1] if last else 'genesis'
    h = hbp_hash(seq, prev, topic, payload)
    conn.execute("INSERT INTO hbp_chain (seq, topic, payload, prev_hash, hash) VALUES (?, ?, ?, ?, ?)",
                 (seq, topic, payload, prev, h))
    conn.commit()
    return seq, h

def parse_ts(raw_ts) -> int:
    if raw_ts is None: return 0
    try:
        if isinstance(raw_ts, (int, float)): return int(raw_ts)
        s = str(raw_ts).replace("unix:", "")
        if s.isdigit(): return int(s)
        return int(datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").timestamp())
    except: return int(time.time())

def main():
    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row; now = time.time()
    hbp_init(conn)

    items = conn.execute(
        "SELECT id, kind, title, content, created_at, COALESCE(weight,1.0) as weight, tags FROM memory_items ORDER BY id"
    ).fetchall()
    total = len(items)
    print(f"📦 {total} memory items to embed")

    conn.execute("DROP TABLE IF EXISTS vector_memory")
    conn.execute("""
        CREATE TABLE vector_memory (
            id TEXT PRIMARY KEY, text TEXT NOT NULL, embedding BLOB NOT NULL,
            ts INTEGER NOT NULL, decay_score REAL DEFAULT 1.0,
            tier TEXT DEFAULT 'episodic', weight REAL DEFAULT 1.0
        )
    """)
    conn.commit()

    done = 0; start = time.time(); hbp_topic = "vector_memory/populate"
    for offset in range(0, total, BATCH):
        batch = items[offset:offset+BATCH]; rows = []; cold_count = 0
        for item in batch:
            item_id = str(item["id"])
            text = f"{item['kind']}: {item['title']}\n{item['content'][:2000]}"
            ts = parse_ts(item["created_at"])
            age_days = max(0.0, (now - ts)/86400.0) if ts > 0 else 0.0
            decay = decay_score(age_days, 0, age_days)
            tier = classify_tier(item["kind"], len(item["content"] or ""), decay)
            emb = embed_text(text); blob = encode_embedding(emb)
            weight = decay if decay > 0.20 else decay * 0.1
            if decay < 0.20: cold_count += 1
            rows.append((item_id, text[:500], blob, ts, decay, tier, weight))

        conn.executemany(
            "INSERT INTO vector_memory VALUES (?, ?, ?, ?, ?, ?, ?)", rows
        )
        conn.commit(); done += len(rows)
        payload = f"offset={offset} rows={len(rows)} cold={cold_count} decay_min={min(r[4] for r in rows):.3f} decay_max={max(r[4] for r in rows):.3f}"
        seq, h = hbp_append(conn, hbp_topic, payload)
        elapsed = time.time()-start
        print(f"  ✅ {done}/{total} ({done*100//total}%) — {done/elapsed:.0f}/s — HBP#{seq}:{h[:12]}")

    # Populate vec0
    vec_path = os.path.expanduser("~/.simplicio/ext/vec0.dylib")
    if os.path.exists(vec_path):
        try:
            conn.enable_load_extension(True); conn.load_extension(vec_path)
            conn.execute("DROP TABLE IF EXISTS vec_memory")
            conn.execute("""
                CREATE VIRTUAL TABLE vec_memory USING vec0(
                    embedding float[256] distance_metric=cosine,
                    id text, text text, ts integer, tier text
                )
            """)
            vec_items = conn.execute(
                "SELECT id, text, embedding, ts, tier FROM vector_memory WHERE decay_score > 0.05"
            ).fetchall()
            for vi in vec_items:
                conn.execute("INSERT INTO vec_memory VALUES (?, ?, ?, ?, ?)",
                             (vi[0], vi[1][:500], vi[3], vi[4], vi[2]))
            conn.commit()
            print(f"🧠 vec0 ANN: {len(vec_items)} items")
        except Exception as e:
            print(f"⚠️  vec0 skip: {e}")

    tiers = conn.execute(
        "SELECT tier, COUNT(*) FROM vector_memory GROUP BY tier ORDER BY tier"
    ).fetchall()
    tier_summary = " ".join(f"{r[0]}:{r[1]}" for r in tiers)
    hbp_append(conn, "vector_memory/done", f"total={done} tiers={tier_summary}")
    conn.close()
    elapsed = time.time()-start
    print(f"\n✅ Done: {done} items in {elapsed:.1f}s ({done/elapsed:.0f}/s)")
    print(f"📊 Tiers: {tier_summary}")

if __name__ == "__main__":
    main()
