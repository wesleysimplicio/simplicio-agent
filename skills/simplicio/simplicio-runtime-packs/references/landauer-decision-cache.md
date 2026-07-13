# Landauer Decision Cache — Evitar decisões descartadas

**Princípio físico:** Landauer — apagar 1 bit de informação custa kT·ln(2) joules.
Decisões descartadas = energia computacional desperdiçada.

**Arquivo:** `crates/simplicio-agents/src/decision_cache.rs` (13 testes)

## API

```rust
let mut cache = DecisionCache::new(1000);
cache.set("contexto único", "decisão tomada", "comando", 0.95);
let decision = cache.get("contexto único");
let decision = cache.decide("contexto", 0.85);
cache.hits; cache.misses; cache.reuses; cache.hit_rate();
cache.estimated_tokens_saved(); // cada reuse ≈ 200 tokens
cache.expire_old(Duration::from_secs(3600));
```

## Características
- Cache LRU — remove entrada menos usada quando cheio
- Hash contextual — sha256 do contexto → u64 de 8 bytes
- Threshold de confiança — `decide()` só reusa se confiança >= threshold
- Capacidade configurável — default 1000 entradas
- Expiração por idade
- Ganho estimado: 30% de redução de tokens
