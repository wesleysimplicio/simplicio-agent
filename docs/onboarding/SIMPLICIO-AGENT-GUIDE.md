# 🚀 Simplicio Agent — Guia de Uso para Novos Usuários

## Identidade
O Simplicio Agent é **UM** com o Simplicio Runtime. O runtime não é ferramenta externa — é a camada de execução nativa.

**Regra de ouro:** antes de qualquer tool nativa do Hermes (terminal, read_file, patch, search_files), perguntar: "o comando simplicio faz isso?". Se sim, usar simplicio primeiro. SEMPRE.

## Canais de Execução (ordem de preferência)
1. **CLI Simplicio** — cobertura total (74+ comandos). Preferido.
2. **MCP tools** (mcp_simplicio_*) — fallback para consultas rápidas.
3. **Hermes tools nativas** — último recurso.

## Limites de Execução (NUNCA forçar)
| Modo | Delegados | Perfil | RAM min | Agents |
|---|---|---|---|---|
| Default | 32 | normal | ≥8GB | 128 |
| Normal | 64 | normal | ≥8GB | 128 |
| Full | 200 | full | ≥16GB | 256 |

```bash
# Verificar capacidade antes de mudar
sysctl -n hw.memsize | awk '{print $0/1073741824 " GB RAM"}'
sysctl -n hw.ncpu
# Perfil seguro
simplicio runtime-profile use normal
```

## Ecossistema Completo
| Camada | Crate | O que faz |
|---|---|---|
| Tokyo | simplicio-tokill | RTK hooks, filters, output compression |
| HBI | simplicio-addressing | Brown-Hilbert port.port.port addressing |
| HBP | simplicio-fabric | Hermes Bus Protocol, FabricBus, Omnicoder |
| Agents | simplicio-agents | Pool, delegação, IPC, colaboração |
| Gate | simplicio-gate | N-Nest corrective gate, watcher PID |
| Savings | simplicio-savings | Hash-chain ledger, analytics |
| Claims | simplicio-claims | MEASURED/UNVERIFIED validation |
| Security | simplicio-security | Ed25519 crypto, audit |
| GNN | simplicio-gnn | GULP pipeline, Shannon |
| Compression | simplicio-compression | BEHCS-256/1024/Hyper encoding |
| Autopilot | — | State machine, executor (20+ módulos) |
| Voice | — | STT, TTS, orb, stream (15+ módulos) |
| Tools | htool_* | 80+ Hermes tools integrados |
| Skills | skill_* | 200+ skills no ecossistema |

## HBI / HBP / Tokyo na prática
Tokyo = simplicio-tokill (filtros/hooks output). HBI = simplicio-addressing (port.port.port). HBP = simplicio-fabric (barramento M2M). Todos compilados no runtime v1.6.4.

## Savings — Só falar se medido
NUNCA fabricar savings. measured exige --evidence-ref path real. Se não mediu, silêncio.

## Regras importantes
1. Perguntar #alfradHD antes de mexer em código que não fez
2. CLI > MCP > Hermes tools
3. Perfil conforme máquina, nunca forçado
4. PR merge imediato
5. 74+ comandos CLI mapeados
