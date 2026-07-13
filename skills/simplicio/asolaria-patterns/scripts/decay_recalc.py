#!/usr/bin/env python3
"""decay_recalc.py — Recalcula decay scores na vector_memory baseado em acessos reais.

Física: retention_score = salience·e^(-λ·Δt) + σ·ln(1+access)·e^(-μ·days_since_access)

Roda como cron job (no_agent): a cada 6h recalcula os decays.
Itens com decay < 0.20 são cold — candidatos a evaporação.
"""

import sqlite3, os, time, math, sys, hashlib
from datetime import datetime

DB = os.path.expanduser("~/.simplicio/memory/simplicio-memory.sqlite")
LAMBDA, SIGMA, MU = 0.02, 0.6, 0.04
SALIENCE_DEFAULT, COLD_THRESHOLD = 1.0, 0.20

def decay_score(age_days, access_count, days_since_access):
    time_term = SALIENCE_DEFAULT * math.exp(-LAMBDA * age_days)
    access_term = SIGMA * math.log1p(access_count) * math.exp(-MU * days_since_access)
    return time_term + access_term

def main(dry_run=False):
    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row; now = time.time()
    items = conn.execute("SELECT id, ts, access_count, last_access_at, decay_score FROM vector_memory").fetchall()
    updates = 0
    for item in items:
        age_days = max(0.0, (now - item["ts"])/86400.0) if item["ts"] > 0 else 0.0
        das = max(0.0, (now - (item["last_access_at"] or item["ts"]))/86400.0)
        new_score = decay_score(age_days, item["access_count"] or 1, das)
        if abs(new_score - item["decay_score"]) > 0.001:
            if not dry_run:
                conn.execute("UPDATE vector_memory SET decay_score = ? WHERE id = ?", (new_score, item["id"]))
            updates += 1
    if not dry_run: conn.commit()

    r = conn.execute("SELECT MIN(decay_score), AVG(decay_score), MAX(decay_score) FROM vector_memory").fetchone()
    cold = conn.execute("SELECT COUNT(*) FROM vector_memory WHERE decay_score < ?", (COLD_THRESHOLD,)).fetchone()[0]

    last = conn.execute("SELECT seq, hash FROM hbp_chain ORDER BY seq DESC LIMIT 1").fetchone()
    seq = (last[0] + 1) if last else 0; prev = last[1] if last else "genesis"
    payload = f"decay_recalc updated={updates} cold={cold} min={r[0]:.3f} avg={r[1]:.3f} max={r[2]:.3f}"
    h = hashlib.sha256()
    for field in [str(seq), prev, "decay/recalc", payload]:
        h.update(len(field).to_bytes(8, "little")); h.update(field.encode())
    if not dry_run:
        conn.execute("INSERT INTO hbp_chain (seq, topic, payload, prev_hash, hash) VALUES (?, 'decay/recalc', ?, ?, ?)",
                     (seq, payload, prev, h.hexdigest()))
        conn.commit()
    conn.close()
    print(f"✅ decay_recalc: {len(items)} scanned, {updates} updated, {cold} cold")

if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
