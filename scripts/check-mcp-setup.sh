#!/usr/bin/env bash
# Verificação da ponte MCP Simplicio Agent ↔ Simplicio Runtime
set -euo pipefail

R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'; B='\033[0;34m'; N='\033[0m'
info()  { echo -e "${G}[✓]${N} $1"; }
warn()  { echo -e "${Y}[!]${N} $1"; }
error() { echo -e "${R}[✗]${N} $1"; }

echo -e "${B}=== Verificação da ponte MCP Simplicio Agent ↔ Simplicio Runtime ===${N}\n"

# 1. Simplicio binary
echo "1. Simplicio Runtime"
if [ -x /Users/wesleysimplicio/.local/bin/simplicio ]; then
  info "Binário: /Users/wesleysimplicio/.local/bin/simplicio"
else
  error "Binário não encontrado!"
fi

# 2. MCP serve test
echo -e "\n2. MCP serve"
MCP_OUT=$(printf '%s\n%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"0.6","capabilities":{}}}' '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | /Users/wesleysimplicio/.local/bin/simplicio serve --mcp --stdio 2>/dev/null)
if echo "$MCP_OUT" | grep -q "simplicio_map"; then
  TOOL_COUNT=$(echo "$MCP_OUT" | grep -o '"name":"simplicio_[a-z]*"' | sort -u | wc -l | tr -d ' ')
  info "simplicio serve --mcp --stdio: OK ($TOOL_COUNT tools)"
else
  error "Falha no MCP serve"
  echo "$MCP_OUT" | head -5
fi

# 3. Simplicio Agent + MCP SDK
echo -e "\n3. Simplicio Agent + MCP SDK"
if /opt/homebrew/bin/python3.11 -c "import mcp" 2>/dev/null; then
  info "MCP SDK instalado (Python 3.11)"
else
  error "MCP SDK NÃO instalado"
fi

# 4. MCP server registrado no Simplicio Agent
echo -e "\n4. MCP server no Simplicio Agent"
SIMPLICIO_AGENT_BIN="${SIMPLICIO_AGENT_BIN:-$(command -v simplicio-agent 2>/dev/null || true)}"
if [ -z "$SIMPLICIO_AGENT_BIN" ]; then
  error "comando simplicio-agent não encontrado no PATH"
else
  HERMES_MCP=$(HERMES_HOME=/Users/wesleysimplicio/.simplicio_agent "$SIMPLICIO_AGENT_BIN" mcp list 2>&1)
  if echo "$HERMES_MCP" | grep -q "simplicio.*enabled"; then
    info "simplicio registrado como ✓ enabled no Simplicio Agent"
  else
    error "simplicio NÃO registrado no Simplicio Agent!"
    echo "$HERMES_MCP"
  fi
fi

# 5. Config.yaml
echo -e "\n5. Config.yaml mcp_servers"
if grep -q "mcp_servers:" /Users/wesleysimplicio/.simplicio_agent/config.yaml && \
   grep -q "simplicio:" /Users/wesleysimplicio/.simplicio_agent/config.yaml; then
  info "mcp_servers.simplicio presente no config.yaml"
else
  error "Faltando mcp_servers.simplicio no config.yaml"
fi

# 6. SOUL.md
echo -e "\n6. SOUL.md"
if grep -q "REGISTRADO E ATIVO" /Users/wesleysimplicio/.simplicio_agent/SOUL.md; then
  info "SOUL.md atualizado com status MCP"
else
  warn "SOUL.md sem status MCP"
fi

# 7. Venv simplicio-agent
echo -e "\n7. Venv simplicio-agent"
if /Users/wesleysimplicio/Projetos/ai/simplicio-agent/venv/bin/pip --version >/dev/null 2>&1; then
  info "Venv funcional (pip OK)"
else
  error "Venv quebrado"
fi

# 8. HERMES_HOME / home efetivo
echo -e "\n8. HERMES_HOME / home efetivo"
if [ -n "${HERMES_HOME:-}" ]; then
  info "HERMES_HOME=$HERMES_HOME"
else
  warn "HERMES_HOME não definido (pode estar usando ~/.simplicio_agent/)"
fi

echo -e "\n${B}=== Diagnóstico concluído ===${N}"
echo "Execute: ./scripts/check-mcp-setup.sh"
