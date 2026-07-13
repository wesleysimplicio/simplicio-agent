# F1 Import Pattern — Turbo Features → Main Agent

## Quando usar

Quando um recurso de performance/capacidade existe no `hermes-turbo-agent/` (branch ou commit específico de otimização) e precisa ser importado para o `simplicio-agent/` principal.

## Gatilhos (Issues #68, #69, #70)

As F1 imports candidates são identificadas pelo label `turbo-speed` no simplicio-agent:
- **#68**: context_compressor.py — json.loads/dumps → agent._fastjson
- **#69**: tool_executor.py — timeout guard em batches concorrentes
- **#70**: tier_rate_limiter.py — token-bucket rate limiter para subagent dispatch

## Fluxo de import

### 1. Identificar o que importar

A issue descreve:
- Commit SHA do hermes-turbo-agent (ex: `485a58c9fb6c...`)
- Funções/locais específicos que mudaram
- O que cada mudança faz

### 2. Verificar se hermes-turbo-agent existe localmente

```bash
ls ~/Projetos/ai/simplicio-agent/hermes-turbo-agent/agent/
```

Se não existir, o import precisa ser implementado manualmente baseado na descrição da issue.

### 3. Implementar o import

**Tipo A — Substituição de chamadas (ex: json → _fastjson)**

```python
# ANTES:
import json
parsed = json.loads(args)
return json.dumps(shrunken, ensure_ascii=False)

# DEPOIS:
from agent._fastjson import loads as _fast_loads, dumps as _fast_dumps
parsed = _fast_loads(args)
return _fast_dumps(shrunken, ensure_ascii=False)
```

**Tipo B — Adição de funcionalidade (ex: timeout guard)**

```python
import os

# No início da função ou como default parameter:
CONCURRENT_TIMEOUT = float(os.environ.get(
    "HERMES_CONCURRENT_TOOL_TIMEOUT_S", "420.0"
))

# No loop de futures:
deadline = time.monotonic() + CONCURRENT_TIMEOUT
for batch in batches:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        for f in futures:
            f.cancel()
        break
    done, not_done = concurrent.futures.wait(futures, timeout=min(remaining, 5.0))
```

**Tipo C — Criação de módulo novo (ex: tier_rate_limiter.py)**

```python
"""Per-tier token-bucket rate limiter for subagent dispatch."""
import os
import threading
import time

class TierRateLimiter:
    def __init__(self):
        self._locks: dict[str, threading.Lock] = {}
        self._buckets: dict[str, float] = {}
        self._last_refill: dict[str, float] = {}
        self._global_lock = threading.Lock()
    
    def _get_config(self, tier: str) -> tuple[float, float]:
        env_key = f"HERMES_TIER_RATE_LIMIT_{tier.upper()}"
        rate = float(os.environ.get(env_key, "60.0"))  # tokens/min
        capacity = rate  # mesma capacidade que taxa de refill
        return rate, capacity
    
    def try_acquire(self, tier: str, tokens: float = 1.0) -> bool:
        with self._global_lock:
            if tier not in self._locks:
                self._locks[tier] = threading.Lock()
                self._buckets[tier] = 0.0
                self._last_refill[tier] = time.monotonic()
        
        with self._locks[tier]:
            rate, capacity = self._get_config(tier)
            now = time.monotonic()
            elapsed = now - self._last_refill[tier]
            self._buckets[tier] = min(capacity, self._buckets[tier] + elapsed * rate / 60.0)
            self._last_refill[tier] = now
            
            if self._buckets[tier] >= tokens:
                self._buckets[tier] -= tokens
                return True
            return False

# Singleton global
rate_limiter = TierRateLimiter()
```

### 4. Verificar sintaxe

```bash
python3 -c "import ast; ast.parse(open('agent/context_compressor.py').read()); print('OK')"
python3 -c "import ast; ast.parse(open('agent/tool_executor.py').read()); print('OK')"
```

### 5. Ferramentas de edição (simplicio-agent não tem gate)

Diferente do simplicio-runtime, o **simplicio-agent NÃO tem gate** bloqueando Hermes tools. Use `patch` diretamente:

```python
from hermes_tools import patch
patch(path="agent/context_compressor.py",
      old_string="import json",
      new_string="from agent._fastjson import loads as _fast_loads, dumps as _fast_dumps\nimport json")
```

Ou `sed` para substituições em massa:
```bash
sed -i '' 's/json.loads(args)/_fast_loads(args)/g' agent/context_compressor.py
```

### 6. Commit e push

```bash
git add -A
git commit -m "feat: F1 import — descrição (#N)"
git push origin main
```

⚠️ **simplicio-agent main NÃO é protegido** — push direto funciona.

## Padrão de Issue

Cada F1 import candidate tem:

```
Título: F1 import candidate (X): arquivo.py — descrição
Corpo: Context (commit SHA), o que mudou, linhas exatas
Labels: enhancement, turbo-speed
```
