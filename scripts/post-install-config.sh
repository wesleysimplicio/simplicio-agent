#!/bin/bash
# post-install-config.sh — Configura o Simplicio Agent para novo usuário
# Roda automaticamente após simplicio install --global

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SIMPLICIO_HOME="${HERMES_HOME:-$HOME/.simplicio_agent}"
CONFIG_FILE="$SIMPLICIO_HOME/config.yaml"
ONBOARDING_DIR="$SIMPLICIO_HOME/onboarding"
PROFILE_OVERRIDE="${SIMPLICIO_INSTALL_PROFILE:-auto}"
RAM_OVERRIDE="${SIMPLICIO_INSTALL_RAM_GB:-}"
CPU_OVERRIDE="${SIMPLICIO_INSTALL_CPU:-}"

usage() {
    cat <<'EOF'
Usage: scripts/post-install-config.sh [--profile auto|compact|normal|full]

Optional environment overrides (useful for tests):
  SIMPLICIO_INSTALL_PROFILE   Force profile selection
  SIMPLICIO_INSTALL_RAM_GB    Override detected RAM (GB)
  SIMPLICIO_INSTALL_CPU       Override detected CPU count
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile)
            PROFILE_OVERRIDE="${2:-}"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Argumento desconhecido: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

detect_ram_gb() {
    if [[ -n "$RAM_OVERRIDE" ]]; then
        printf "%s\n" "$RAM_OVERRIDE"
        return
    fi
    if command -v sysctl >/dev/null 2>&1; then
        local bytes
        bytes="$(sysctl -n hw.memsize 2>/dev/null || true)"
        if [[ "$bytes" =~ ^[0-9]+$ ]] && [[ "$bytes" -gt 0 ]]; then
            python3 - <<'PY_RAM' "$bytes"
import sys
print(max(1, int(int(sys.argv[1]) / 1024 / 1024 / 1024)))
PY_RAM
            return
        fi
    fi
    if [[ -r /proc/meminfo ]]; then
        local kb
        kb="$(awk '/MemTotal:/ {print $2}' /proc/meminfo 2>/dev/null || true)"
        if [[ "$kb" =~ ^[0-9]+$ ]] && [[ "$kb" -gt 0 ]]; then
            python3 - <<'PY_RAM' "$kb"
import sys
print(max(1, int(int(sys.argv[1]) / 1024 / 1024)))
PY_RAM
            return
        fi
    fi
    echo 8
}

detect_cpu_count() {
    if [[ -n "$CPU_OVERRIDE" ]]; then
        printf "%s\n" "$CPU_OVERRIDE"
        return
    fi
    if command -v sysctl >/dev/null 2>&1; then
        local cores
        cores="$(sysctl -n hw.ncpu 2>/dev/null || true)"
        if [[ "$cores" =~ ^[0-9]+$ ]] && [[ "$cores" -gt 0 ]]; then
            echo "$cores"
            return
        fi
    fi
    if command -v getconf >/dev/null 2>&1; then
        local cores
        cores="$(getconf _NPROCESSORS_ONLN 2>/dev/null || true)"
        if [[ "$cores" =~ ^[0-9]+$ ]] && [[ "$cores" -gt 0 ]]; then
            echo "$cores"
            return
        fi
    fi
    if command -v nproc >/dev/null 2>&1; then
        local cores
        cores="$(nproc 2>/dev/null || true)"
        if [[ "$cores" =~ ^[0-9]+$ ]] && [[ "$cores" -gt 0 ]]; then
            echo "$cores"
            return
        fi
    fi
    echo 4
}

select_profile() {
    local ram_gb="$1"
    local cpu_count="$2"
    case "$PROFILE_OVERRIDE" in
        compact|normal|full)
            echo "$PROFILE_OVERRIDE"
            return
            ;;
        auto|"")
            ;;
        *)
            echo "Perfil invalido: $PROFILE_OVERRIDE" >&2
            exit 1
            ;;
    esac

    if (( ram_gb >= 16 && cpu_count >= 8 )); then
        echo full
    elif (( ram_gb < 8 || cpu_count < 4 )); then
        echo compact
    else
        echo normal
    fi
}

profile_children() {
    case "$1" in
        compact) echo 16 ;;
        normal) echo 32 ;;
        full) echo 64 ;;
        *)
            echo "Perfil desconhecido: $1" >&2
            exit 1
            ;;
    esac
}

write_default_config() {
    local profile="$1"
    local children="$2"
    mkdir -p "$SIMPLICIO_HOME"
    cat > "$CONFIG_FILE" <<EOF_CONFIG
delegation:
  max_concurrent_children: $children
  max_spawn_depth: 3
  orchestrator_enabled: true
agent:
  max_turns: 200
setup_profiles:
  install_speed_profile: $profile
EOF_CONFIG
}

echo "=== Configurando Simplicio Agent ==="

mkdir -p "$SIMPLICIO_HOME/skills"
mkdir -p "$HOME/.simplicio"

if [[ -d "$REPO_ROOT/skills" ]]; then
    cp -r "$REPO_ROOT/skills"/* "$SIMPLICIO_HOME/skills/" 2>/dev/null || true
fi

ram_gb="$(detect_ram_gb)"
cpu_count="$(detect_cpu_count)"
profile="$(select_profile "$ram_gb" "$cpu_count")"
children="$(profile_children "$profile")"

echo "[simplicio] Perfil detectado: $profile (RAM=${ram_gb}GB CPU=${cpu_count})"

if [[ ! -f "$CONFIG_FILE" ]]; then
    write_default_config "$profile" "$children"
    echo "Config criada: delegation ${children} (${profile})"
else
    echo "Config existente preservada: $CONFIG_FILE"
fi

mkdir -p "$ONBOARDING_DIR"
cp "$REPO_ROOT/docs/onboarding/SIMPLICIO-AGENT-GUIDE.md" "$ONBOARDING_DIR/" 2>/dev/null || true

if command -v simplicio >/dev/null 2>&1; then
    simplicio runtime-profile use normal 2>/dev/null || true
fi

echo "=== Simplicio Agent configurado com sucesso ==="
echo "Leia $ONBOARDING_DIR/SIMPLICIO-AGENT-GUIDE.md para começar"

echo "[simplicio] Populando banco neural com skills..."
if [[ -f "$HOME/Projetos/ai/simplicio-runtime/scripts/memory_seed.py" ]]; then
    python3 "$HOME/Projetos/ai/simplicio-runtime/scripts/memory_seed.py" --sync 2>/dev/null && \
        echo "  Banco neural populado: 567+ skills, 36K+ itens"
else
    echo "  Runtime nao encontrado - seed sera feito na primeira execucao"
fi

echo "[simplicio] Indexando skills do ecossistema..."
find "$SIMPLICIO_HOME/skills" -name "SKILL.md" 2>/dev/null | wc -l | xargs -I{} echo "  {} skills locais registradas"

echo "[simplicio] Configuracao concluida."
