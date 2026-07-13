#!/usr/bin/env bash
# Verificação da ponte MCP Hermes ↔ Simplicio Runtime
set -euo pipefail

R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'; B='\033[0;34m'; N='\033[0m'
info()  { echo -e "${G}[✓]${N} $1"; }
warn()  { echo -e "${Y}[!]${N} $1"; }
error() { echo -e "${R}[✗]${N} $1"; }

echo -e "${B}=== Verificação da ponte MCP Simplicio Agent ↔ Simplicio Runtime ===${N}\n"

# 1. Simplicio binary (canonical shim, issue #96)
#
# Previously this hardcoded /Users/wesleysimplicio/.local/bin/simplicio --
# a single developer's macOS home -- so the check was structurally broken
# on any other machine (always "não encontrado", regardless of the real
# state). Resolve dynamically via $HOME instead, and explicitly FAIL (not
# just warn) when the PATH/canonical shim points at a target that no
# longer exists, per issue #96's acceptance criteria.
echo "1. Simplicio Runtime"
CANONICAL_SIMPLICIO="${HOME}/.local/bin/simplicio"
RESOLVED_SIMPLICIO="$(command -v simplicio 2>/dev/null || true)"

if [ -n "$RESOLVED_SIMPLICIO" ]; then
  if [ -x "$RESOLVED_SIMPLICIO" ] && "$RESOLVED_SIMPLICIO" version >/dev/null 2>&1; then
    info "command -v simplicio -> $RESOLVED_SIMPLICIO (executa)"
  else
    error "PATH resolve simplicio para um alvo ausente/quebrado: $RESOLVED_SIMPLICIO"
    exit 1
  fi
else
  warn "simplicio não está no PATH"
fi

if [ -L "$CANONICAL_SIMPLICIO" ] && [ ! -e "$CANONICAL_SIMPLICIO" ]; then
  error "Shim canônico é um symlink quebrado: $CANONICAL_SIMPLICIO -> $(readlink "$CANONICAL_SIMPLICIO") (alvo ausente)"
  exit 1
elif [ -x "$CANONICAL_SIMPLICIO" ]; then
  if "$CANONICAL_SIMPLICIO" version >/dev/null 2>&1; then
    info "Binário canônico executa: $CANONICAL_SIMPLICIO"
  else
    error "Binário canônico existe, mas falha ao executar: $CANONICAL_SIMPLICIO"
    exit 1
  fi
else
  warn "Binário canônico ainda não instalado: $CANONICAL_SIMPLICIO (rode ./setup-hermes.sh ou simplicio-agent doctor --fix)"
fi

if [ -n "$RESOLVED_SIMPLICIO" ] && [ "$RESOLVED_SIMPLICIO" != "$CANONICAL_SIMPLICIO" ]; then
  warn "PATH está preferindo $RESOLVED_SIMPLICIO em vez do binário canônico ($CANONICAL_SIMPLICIO)"
fi

# 2. MCP serve test — exercise whatever binary actually resolved above (the
# installed binary), not a hardcoded path assumed to be a source checkout.
echo -e "\n2. MCP serve"
MCP_BIN="${RESOLVED_SIMPLICIO:-$CANONICAL_SIMPLICIO}"
if [ ! -x "$MCP_BIN" ]; then
  warn "Pulando teste MCP serve — nenhum binário simplicio executável encontrado ($MCP_BIN)"
else
  MCP_OUT=$(printf '%s\n%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"0.6","capabilities":{}}}' '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | "$MCP_BIN" serve --mcp --stdio 2>/dev/null)
  if echo "$MCP_OUT" | grep -q "simplicio_map"; then
    TOOL_COUNT=$(echo "$MCP_OUT" | grep -o '"name":"simplicio_[a-z]*"' | sort -u | wc -l | tr -d ' ')
    info "simplicio serve --mcp --stdio: OK ($TOOL_COUNT tools)"
  else
    error "Falha no MCP serve"
    echo "$MCP_OUT" | head -5
  fi
fi

# 3. Simplicio Agent + MCP SDK
echo -e "\n3. Simplicio Agent + MCP SDK"
if /opt/homebrew/bin/python3.11 -c "import mcp" 2>/dev/null; then
  info "MCP SDK instalado (Python 3.11)"
else
  error "MCP SDK NÃO instalado"
fi

# 4. MCP server registrado no Hermes
echo -e "\n4. MCP server no Simplicio Agent"
HERMES_MCP=$(HERMES_HOME=/Users/wesleysimplicio/.simplicio_agent /opt/homebrew/bin/simplicio-agent mcp list 2>&1)
if echo "$HERMES_MCP" | grep -q "simplicio.*enabled"; then
  info "simplicio registrado como ✓ enabled no Simplicio Agent"
else
  error "simplicio NÃO registrado no Simplicio Agent!"
  echo "$HERMES_MCP"
fi

# 5. Config.yaml
echo -e "\n5. config.yaml do Simplicio Agent (mcp_servers)"
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

# 8. HERMES_HOME
echo -e "\n8. HERMES_HOME"
if [ -n "${HERMES_HOME:-}" ]; then
  info "HERMES_HOME=$HERMES_HOME"
else
  warn "HERMES_HOME não definido (pode estar usando ~/.hermes/)"
fi

echo -e "\n${B}=== Diagnóstico concluído ===${N}"
echo "Execute: ./scripts/check-mcp-setup.sh"
