#!/bin/bash
# post-install-config.sh — Configura o Simplicio Agent para novo usuário
# Roda automaticamente após simplicio install --global

set -e

echo "=== Configurando Simplicio Agent ==="

# Criar diretório de skills se não existir
mkdir -p ~/.simplicio_agent/skills
mkdir -p ~/.simplicio

# Copiar skills padrão
if [ -d "skills" ]; then
    cp -r skills/* ~/.simplicio_agent/skills/ 2>/dev/null || true
fi

# Configurar delegação padrão (32)
CONFIG_FILE=~/.simplicio_agent/config.yaml
if [ ! -f "$CONFIG_FILE" ]; then
    cat > "$CONFIG_FILE" << 'EOF'
delegation:
  max_concurrent_children: 32
  max_spawn_depth: 3
  orchestrator_enabled: true
EOF
    echo "Config criada: delegation 32 (default seguro)"
fi

# Copiar guia de onboarding
mkdir -p ~/.simplicio_agent/onboarding
cp docs/onboarding/SIMPLICIO-AGENT-GUIDE.md ~/.simplicio_agent/onboarding/ 2>/dev/null || true

# Verificar perfil runtime
if command -v simplicio &>/dev/null; then
    simplicio runtime-profile use normal 2>/dev/null || true
fi

echo "=== Simplicio Agent configurado com sucesso ==="
echo "Leia ~/.simplicio_agent/onboarding/SIMPLICIO-AGENT-GUIDE.md para começar"
