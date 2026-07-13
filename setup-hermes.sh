#!/bin/bash
# ============================================================================
# Simplicio Agent Setup Script
# ============================================================================
# Quick setup for developers who cloned the repo manually.
# Uses uv for desktop/server setup and Python's stdlib venv + pip on Termux.
#
# Usage:
#   ./setup-hermes.sh
#
# This script:
# 1. Detects desktop/server vs Android/Termux setup path
# 2. Creates a Python 3.11 virtual environment
# 3. Installs the appropriate dependency set for the platform
# 4. Creates .env from template (if not exists)
# 5. Symlinks the 'hermes' CLI command into a user-facing bin dir
# 6. Runs the setup wizard (optional)
# ============================================================================

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Prevent uv from discovering config files (uv.toml, pyproject.toml) from the
# wrong user's home directory when running under sudo -u <user>.  See #21269.
export UV_NO_CONFIG=1

PYTHON_VERSION="3.11"

is_termux() {
    [ -n "${TERMUX_VERSION:-}" ] || [[ "${PREFIX:-}" == *"com.termux/files/usr"* ]]
}

get_command_link_dir() {
    if is_termux && [ -n "${PREFIX:-}" ]; then
        echo "$PREFIX/bin"
    else
        echo "$HOME/.local/bin"
    fi
}

get_command_link_display_dir() {
    if is_termux && [ -n "${PREFIX:-}" ]; then
        echo '$PREFIX/bin'
    else
        echo '~/.local/bin'
    fi
}

echo ""
echo -e "${CYAN}⚕ Simplicio Agent Setup${NC}"
echo ""

# ============================================================================
# Install / locate uv
# ============================================================================

echo -e "${CYAN}→${NC} Checking for uv..."

UV_CMD=""
if is_termux; then
    echo -e "${CYAN}→${NC} Termux detected — using Python's stdlib venv + pip instead of uv"
else
    if command -v uv &> /dev/null; then
        UV_CMD="uv"
    elif [ -x "$HOME/.local/bin/uv" ]; then
        UV_CMD="$HOME/.local/bin/uv"
    elif [ -x "$HOME/.cargo/bin/uv" ]; then
        UV_CMD="$HOME/.cargo/bin/uv"
    fi

    if [ -n "$UV_CMD" ]; then
        UV_VERSION=$($UV_CMD --version 2>/dev/null)
        echo -e "${GREEN}✓${NC} uv found ($UV_VERSION)"
    else
        echo -e "${CYAN}→${NC} Installing uv..."
        # Capture installer output so a failure shows the user WHY
        # (network, glibc mismatch on old distros, missing curl, disk
        # full, etc.) instead of "✗ Failed to install uv" with zero
        # diagnostic.  Two-stage to avoid `curl | sh` masking curl
        # failures (sh exits 0 on empty stdin under no pipefail).
        _uv_log="$(mktemp 2>/dev/null || echo "/tmp/hermes-uv-install.$$.log")"
        _uv_installer="$(mktemp 2>/dev/null || echo "/tmp/hermes-uv-installer.$$.sh")"
        if ! curl -LsSf https://astral.sh/uv/install.sh -o "$_uv_installer" 2>"$_uv_log"; then
            echo -e "${RED}✗${NC} Failed to download uv installer."
            sed 's/^/    /' "$_uv_log" >&2
            echo -e "${CYAN}→${NC} Install manually: https://docs.astral.sh/uv/"
            rm -f "$_uv_log" "$_uv_installer"
            exit 1
        fi
        if sh "$_uv_installer" >>"$_uv_log" 2>&1; then
            rm -f "$_uv_installer"
            if [ -x "$HOME/.local/bin/uv" ]; then
                UV_CMD="$HOME/.local/bin/uv"
            elif [ -x "$HOME/.cargo/bin/uv" ]; then
                UV_CMD="$HOME/.cargo/bin/uv"
            fi

            if [ -n "$UV_CMD" ]; then
                rm -f "$_uv_log"
                UV_VERSION=$($UV_CMD --version 2>/dev/null)
                echo -e "${GREEN}✓${NC} uv installed ($UV_VERSION)"
            else
                echo -e "${RED}✗${NC} uv installer reported success but binary not found. Add ~/.local/bin to PATH and retry."
                echo -e "${CYAN}→${NC} Installer output:"
                sed 's/^/    /' "$_uv_log" >&2
                rm -f "$_uv_log"
                exit 1
            fi
        else
            echo -e "${RED}✗${NC} Failed to install uv."
            echo -e "${CYAN}→${NC} Installer output:"
            sed 's/^/    /' "$_uv_log" >&2
            echo -e "${CYAN}→${NC} Install manually: https://docs.astral.sh/uv/"
            rm -f "$_uv_log" "$_uv_installer"
            exit 1
        fi
    fi
fi

# ============================================================================
# Python check (uv can provision it automatically)
# ============================================================================

echo -e "${CYAN}→${NC} Checking Python $PYTHON_VERSION..."

if is_termux; then
    if command -v python >/dev/null 2>&1; then
        PYTHON_PATH="$(command -v python)"
        if "$PYTHON_PATH" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
            PYTHON_FOUND_VERSION=$($PYTHON_PATH --version 2>/dev/null)
            echo -e "${GREEN}✓${NC} $PYTHON_FOUND_VERSION found"
        else
            echo -e "${RED}✗${NC} Termux Python must be 3.11+"
            echo "    Run: pkg install python"
            exit 1
        fi
    else
        echo -e "${RED}✗${NC} Python not found in Termux"
        echo "    Run: pkg install python"
        exit 1
    fi
else
    if $UV_CMD python find "$PYTHON_VERSION" &> /dev/null; then
        PYTHON_PATH=$($UV_CMD python find "$PYTHON_VERSION")
        PYTHON_FOUND_VERSION=$($PYTHON_PATH --version 2>/dev/null)
        echo -e "${GREEN}✓${NC} $PYTHON_FOUND_VERSION found"
    else
        echo -e "${CYAN}→${NC} Python $PYTHON_VERSION not found, installing via uv..."
        $UV_CMD python install "$PYTHON_VERSION"
        PYTHON_PATH=$($UV_CMD python find "$PYTHON_VERSION")
        PYTHON_FOUND_VERSION=$($PYTHON_PATH --version 2>/dev/null)
        echo -e "${GREEN}✓${NC} $PYTHON_FOUND_VERSION installed"
    fi
fi

# ============================================================================
# Virtual environment
# ============================================================================

echo -e "${CYAN}→${NC} Setting up virtual environment..."

if [ -d "venv" ]; then
    echo -e "${CYAN}→${NC} Removing old venv..."
    rm -rf venv
fi

if is_termux; then
    "$PYTHON_PATH" -m venv venv
    echo -e "${GREEN}✓${NC} venv created with stdlib venv"
else
    $UV_CMD venv venv --python "$PYTHON_VERSION"
    echo -e "${GREEN}✓${NC} venv created (Python $PYTHON_VERSION)"
fi

export VIRTUAL_ENV="$SCRIPT_DIR/venv"
SETUP_PYTHON="$SCRIPT_DIR/venv/bin/python"

# ============================================================================
# Dependencies
# ============================================================================

echo -e "${CYAN}→${NC} Installing dependencies..."

if is_termux; then
    export ANDROID_API_LEVEL="$(getprop ro.build.version.sdk 2>/dev/null || printf '%s' "${ANDROID_API_LEVEL:-}")"
    echo -e "${CYAN}→${NC} Termux detected — installing the tested Android bundle"
    "$SETUP_PYTHON" -m pip install --upgrade pip setuptools wheel
    if [ -f "constraints-termux.txt" ]; then
        "$SETUP_PYTHON" -m pip install -e ".[termux]" -c constraints-termux.txt || {
            echo -e "${YELLOW}⚠${NC} Termux bundle install failed, falling back to base install..."
            "$SETUP_PYTHON" -m pip install -e "." -c constraints-termux.txt
        }
    else
        "$SETUP_PYTHON" -m pip install -e ".[termux]" || "$SETUP_PYTHON" -m pip install -e "."
    fi
    echo -e "${GREEN}✓${NC} Dependencies installed"
else
    # Prefer uv sync with lockfile (hash-verified installs) when available,
    # fall back to pip install for compatibility or when lockfile is stale.
    #
    # Multi-tier pip fallback. Goal: ONE compromised PyPI package
    # (mistralai 2.4.6 in May 2026 → quarantined) shouldn't silently demote
    # a fresh setup to "core only". Edit _BROKEN_EXTRAS when a transitive
    # breaks; users keep voice / honcho / google / slack / matrix etc. even
    # if mistral can't resolve.
    _BROKEN_EXTRAS=()  # populate when an extra becomes unresolvable
    _ALL_EXTRAS=(
        modal daytona messaging matrix cron cli dev tts-premium slack
        pty honcho mcp homeassistant sms acp voice dingtalk feishu google
        bedrock web youtube
    )
    _SAFE_EXTRAS=()
    for _e in "${_ALL_EXTRAS[@]}"; do
        _skip=false
        for _b in "${_BROKEN_EXTRAS[@]}"; do
            [ "$_e" = "$_b" ] && _skip=true && break
        done
        [ "$_skip" = false ] && _SAFE_EXTRAS+=("$_e")
    done
    _SAFE_SPEC=".[$(IFS=,; echo "${_SAFE_EXTRAS[*]}")]"
    _try_install() {
        $UV_CMD pip install -e ".[all]" \
            || $UV_CMD pip install -e "$_SAFE_SPEC" \
            || $UV_CMD pip install -e "."
    }

    if [ -f "uv.lock" ]; then
        # Hash-verified install (preferred). The lockfile records SHA256
        # hashes for every transitive — a compromised transitive would have
        # a different hash and be REJECTED by uv. This is the only path
        # that protects against transitive-package supply-chain attacks
        # (the direct deps in pyproject.toml are exact-pinned, but
        # `uv pip install` re-resolves transitives fresh from PyPI).
        echo -e "${CYAN}→${NC} Using uv.lock for hash-verified installation..."
        echo -e "${CYAN}→${NC} (first run on a fresh venv can take 1-5 minutes; uv prints progress below)"
        # Critical flag choice: `--extra all`, NOT `--all-extras`. The
        # latter installs every [project.optional-dependencies] key,
        # bypassing the curated [all] extra and pulling backends like
        # [matrix] (python-olm needs make on Windows) and [rl] (git+https
        # deps that fail offline). See pyproject.toml's [all] for the
        # curated set, and tools/lazy_deps.py for backends that install
        # at first use.
        # Also: stream stderr through directly so the user sees uv's
        # progress UI instead of staring at a frozen prompt.
        if UV_PROJECT_ENVIRONMENT="$SCRIPT_DIR/venv" $UV_CMD sync --extra all --locked; then
            echo -e "${GREEN}✓${NC} Dependencies installed (hash-verified via uv.lock)"
        else
            echo -e "${YELLOW}⚠${NC} Lockfile sync failed (see uv output above)."
            echo -e "${YELLOW}⚠${NC} Falling back to PyPI resolve — transitives will NOT be hash-verified."
            _try_install
            echo -e "${GREEN}✓${NC} Dependencies installed (transitives re-resolved, not hash-verified)"
        fi
    else
        echo -e "${YELLOW}⚠${NC} uv.lock not found — installing without hash verification of transitives."
        _try_install
        echo -e "${GREEN}✓${NC} Dependencies installed (transitives re-resolved, not hash-verified)"
    fi
fi

# ============================================================================
# ============================================================================
# Optional: ripgrep (for faster file search)
# ============================================================================

echo -e "${CYAN}→${NC} Checking ripgrep (optional, for faster search)..."

if command -v rg &> /dev/null; then
    echo -e "${GREEN}✓${NC} ripgrep found"
else
    echo -e "${YELLOW}⚠${NC} ripgrep not found (file search will use grep fallback)"
    read -p "Install ripgrep for faster search? [Y/n] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
        INSTALLED=false

        if is_termux; then
            pkg install -y ripgrep && INSTALLED=true
        else
            # Check if sudo is available
            if command -v sudo &> /dev/null && sudo -n true 2>/dev/null; then
                if command -v apt &> /dev/null; then
                    sudo apt install -y ripgrep && INSTALLED=true
                elif command -v dnf &> /dev/null; then
                    sudo dnf install -y ripgrep && INSTALLED=true
                fi
            fi

            # Try brew (no sudo needed)
            if [ "$INSTALLED" = false ] && command -v brew &> /dev/null; then
                brew install ripgrep && INSTALLED=true
            fi

            # Try cargo (no sudo needed)
            if [ "$INSTALLED" = false ] && command -v cargo &> /dev/null; then
                echo -e "${CYAN}→${NC} Trying cargo install (no sudo required)..."
                cargo install ripgrep && INSTALLED=true
            fi
        fi

        if [ "$INSTALLED" = true ]; then
            echo -e "${GREEN}✓${NC} ripgrep installed"
        else
            echo -e "${YELLOW}⚠${NC} Auto-install failed. Install options:"
            if is_termux; then
                echo "    pkg install ripgrep          # Termux / Android"
            else
                echo "    sudo apt install ripgrep     # Debian/Ubuntu"
                echo "    brew install ripgrep         # macOS"
                echo "    cargo install ripgrep        # With Rust (no sudo)"
            fi
            echo "    https://github.com/BurntSushi/ripgrep#installation"
        fi
    fi
fi

# ============================================================================
# Environment file
# ============================================================================

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        # .env holds API keys — restrict to owner-only access (matches
        # scripts/install.sh which already chmods 600 after creation).
        chmod 600 .env 2>/dev/null || true
        echo -e "${GREEN}✓${NC} Created .env from template"
    fi
else
    # Tighten an existing .env's perms in case it was created elsewhere
    # under a permissive umask.
    chmod 600 .env 2>/dev/null || true
    echo -e "${GREEN}✓${NC} .env exists"
fi

# ============================================================================
# PATH setup — symlink simplicio-agent (+ deprecated hermes alias) into a
# user-facing bin dir
# ============================================================================

echo -e "${CYAN}→${NC} Setting up simplicio-agent command..."

AGENT_BIN="$SCRIPT_DIR/venv/bin/simplicio-agent"
HERMES_BIN="$SCRIPT_DIR/venv/bin/hermes"
# Older venvs may predate the simplicio-agent entry point.
[ -x "$AGENT_BIN" ] || AGENT_BIN="$HERMES_BIN"
COMMAND_LINK_DIR="$(get_command_link_dir)"
COMMAND_LINK_DISPLAY_DIR="$(get_command_link_display_dir)"
mkdir -p "$COMMAND_LINK_DIR"
ln -sf "$AGENT_BIN" "$COMMAND_LINK_DIR/simplicio-agent"
ln -sf "$AGENT_BIN" "$COMMAND_LINK_DIR/hermes"
echo -e "${GREEN}✓${NC} Symlinked simplicio-agent → $COMMAND_LINK_DISPLAY_DIR/simplicio-agent (hermes kept as deprecated alias)"

if is_termux; then
    export PATH="$COMMAND_LINK_DIR:$PATH"
    echo -e "${GREEN}✓${NC} $COMMAND_LINK_DISPLAY_DIR is already on PATH in Termux"
else
    # Determine the appropriate shell config file
    SHELL_CONFIG=""
    if [[ "$SHELL" == *"zsh"* ]]; then
        SHELL_CONFIG="$HOME/.zshrc"
    elif [[ "$SHELL" == *"bash"* ]]; then
        SHELL_CONFIG="$HOME/.bashrc"
        [ ! -f "$SHELL_CONFIG" ] && SHELL_CONFIG="$HOME/.bash_profile"
    else
        # Fallback to checking existing files
        if [ -f "$HOME/.zshrc" ]; then
            SHELL_CONFIG="$HOME/.zshrc"
        elif [ -f "$HOME/.bashrc" ]; then
            SHELL_CONFIG="$HOME/.bashrc"
        elif [ -f "$HOME/.bash_profile" ]; then
            SHELL_CONFIG="$HOME/.bash_profile"
        fi
    fi

    if [ -n "$SHELL_CONFIG" ]; then
        # Touch the file just in case it doesn't exist yet but was selected
        touch "$SHELL_CONFIG" 2>/dev/null || true

        if ! echo "$PATH" | tr ':' '\n' | grep -q "^$HOME/.local/bin$"; then
            if ! grep -q '\.local/bin' "$SHELL_CONFIG" 2>/dev/null; then
                echo "" >> "$SHELL_CONFIG"
                echo "# Hermes Agent — ensure ~/.local/bin is on PATH" >> "$SHELL_CONFIG"
                echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_CONFIG"
                echo -e "${GREEN}✓${NC} Added ~/.local/bin to PATH in $SHELL_CONFIG"
            else
                echo -e "${GREEN}✓${NC} ~/.local/bin already in $SHELL_CONFIG"
            fi
        else
            echo -e "${GREEN}✓${NC} ~/.local/bin already on PATH"
        fi
    fi
fi

# ============================================================================
# SIMPLICIO RUNTIME — Instalar o corpo do Simplicio Agent
# ============================================================================

echo ""
echo -e "${CYAN}→${NC} Instalando Simplicio Runtime (corpo do Agent)..."
echo ""

# ── 1. Rust binary ──────────────────────────────────────────────────────
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"
export PATH="$BIN_DIR:$PATH"

SIMPLICIO_RUNTIME_DIR="${SIMPLICIO_RUNTIME_DIR:-$HOME/Projetos/ai/simplicio-runtime}"

repair_simplicio_binary() {
    local target="$BIN_DIR/simplicio"
    local source_bin="${SIMPLICIO_RUNTIME_DIR%/}/target/release/simplicio"

    # If the canonical binary already exists and executes, keep it.
    if [ -x "$target" ] && "$target" version &>/dev/null; then
        return 0
    fi

    echo -e "${CYAN}→${NC} Reforçando o binário canônico do Simplicio..."

    # Prefer a locally built runtime binary when available.
    if [ -x "$source_bin" ]; then
        cp "$source_bin" "$target" 2>/dev/null || true
        chmod +x "$target" 2>/dev/null || true
        xattr -d com.apple.quarantine "$target" 2>/dev/null || true
        xattr -d com.apple.provenance "$target" 2>/dev/null || true
        if "$target" version &>/dev/null; then
            echo -e "${GREEN}✓${NC} simplicio reparado a partir do runtime local ($target)"
            return 0
        fi
    fi

    # If the runtime source tree exists, try to build it deterministically.
    if [ -d "$SIMPLICIO_RUNTIME_DIR" ] && [ -f "$SIMPLICIO_RUNTIME_DIR/Cargo.toml" ] && command -v cargo &>/dev/null; then
        echo -e "${CYAN}→${NC} Compilando simplicio-runtime local..."
        if (cd "$SIMPLICIO_RUNTIME_DIR" && cargo build --release --locked); then
            if [ -x "$SIMPLICIO_RUNTIME_DIR/target/release/simplicio" ]; then
                cp "$SIMPLICIO_RUNTIME_DIR/target/release/simplicio" "$target" 2>/dev/null || true
                chmod +x "$target" 2>/dev/null || true
                xattr -d com.apple.quarantine "$target" 2>/dev/null || true
                xattr -d com.apple.provenance "$target" 2>/dev/null || true
                if "$target" version &>/dev/null; then
                    echo -e "${GREEN}✓${NC} simplicio compilado e instalado em $target"
                    return 0
                fi
            fi
        fi
    fi

    return 1
}

if command -v "$BIN_DIR/simplicio" &> /dev/null; then
    echo -e "${GREEN}✓${NC} simplicio binary já instalado ($($BIN_DIR/simplicio version 2>/dev/null || echo '?'))"
else
    echo -e "${CYAN}→${NC} Baixando simplicio binary..."
    ARCH=$(uname -m)
    OS=$(uname -s | tr '[:upper:]' '[:lower:]')
    case "$ARCH" in
        x86_64)  ARCH="x86_64"  ;;
        aarch64|arm64) ARCH="aarch64" ;;
    esac

    # Tenta instalar via npm (mais simples, cuida do PATH)
    if command -v npm &> /dev/null; then
        echo -e "${CYAN}→${NC} Via npm..."
        npm install -g simplicio 2>/dev/null && \
            echo -e "${GREEN}✓${NC} simplicio instalado via npm" || \
            echo -e "${YELLOW}⚠${NC} npm install falhou — tentando download direto"
    fi

    # Fallback: download direto do GitHub
    if ! command -v "$BIN_DIR/simplicio" &> /dev/null; then
        DOWNLOAD_URL="https://github.com/wesleysimplicio/simplicio/releases/latest/download/simplicio-${ARCH}-${OS}.tar.gz"
        echo -e "${CYAN}→${NC} Download: $DOWNLOAD_URL"
        TMP_TAR=$(mktemp)
        if curl -sL "$DOWNLOAD_URL" -o "$TMP_TAR" 2>/dev/null; then
            tar -xzf "$TMP_TAR" -C "$BIN_DIR" 2>/dev/null || cp "$TMP_TAR" "$BIN_DIR/simplicio" 2>/dev/null
            chmod +x "$BIN_DIR/simplicio" 2>/dev/null
            # Remove quarantine no macOS
            xattr -d com.apple.quarantine "$BIN_DIR/simplicio" 2>/dev/null || true
            xattr -d com.apple.provenance "$BIN_DIR/simplicio" 2>/dev/null || true
            codesign --force --sign - "$BIN_DIR/simplicio" 2>/dev/null || true
            rm -f "$TMP_TAR"

            if "$BIN_DIR/simplicio" version &> /dev/null; then
                echo -e "${GREEN}✓${NC} simplicio binary instalado ($($BIN_DIR/simplicio version))"
            else
                echo -e "${YELLOW}⚠${NC} Binary baixado mas não executa — pode precisar de compilação manual"
                echo "    Compile: cd ~/Projetos/ai/simplicio-runtime && cargo build --release && cp target/release/simplicio $BIN_DIR/simplicio"
            fi
        else
            echo -e "${YELLOW}⚠${NC} Download falhou — compile manualmente do simplicio-runtime"
            echo "    cd ~/Projetos/ai/simplicio-runtime && cargo build --release && cp target/release/simplicio $BIN_DIR/simplicio"
        fi
    fi
fi

if ! repair_simplicio_binary; then
    echo -e "${YELLOW}⚠${NC} Não foi possível reparar o binário canônico agora"
    echo "    Verifique: $BIN_DIR/simplicio e $SIMPLICIO_RUNTIME_DIR/target/release/simplicio"
fi

# ── Canonical PATH shim (issue #96) ─────────────────────────────────────
# Whatever the strategy above produced (already installed / npm / download /
# repair), verify — and idempotently re-wire — that `command -v simplicio`
# and `simplicio version` resolve deterministically to $BIN_DIR/simplicio
# instead of trusting a step above blindly. tools/runtime_manager.py owns
# this logic (shared with `simplicio-agent doctor --fix`) so there is one
# resolution algorithm, not a bash copy of the Python one.
if [ -x "$SETUP_PYTHON" ]; then
    "$SETUP_PYTHON" - <<'PYEOF'
import sys
sys.path.insert(0, ".")
try:
    from tools.runtime_manager import canonical_symlink_path, runtime_status, sync_canonical_symlink
    status = runtime_status()
    err = sync_canonical_symlink(status)
    link = canonical_symlink_path()
    if err:
        print(f"[simplicio-bootstrap] AVISO: {link} nao sincronizado ({err})")
    elif status.present:
        print(f"[simplicio-bootstrap] OK: {link} -> {status.bin_path} (v{status.version or '?'})")
    else:
        print("[simplicio-bootstrap] simplicio kernel ainda nao resolve — rode 'simplicio-agent doctor --fix'")
except Exception as exc:  # never fail setup on this best-effort step
    print(f"[simplicio-bootstrap] verificacao pulada: {exc}")
PYEOF
fi

# ── 2. Python ecosystem (PyPI) ──────────────────────────────────────────
echo -e "${CYAN}→${NC} Instalando ecossistema Python do Simplicio..."
"$SETUP_PYTHON" -m pip install simplicio-cli simplicio-mapper --quiet 2>/dev/null && \
    echo -e "${GREEN}✓${NC} simplicio-cli + simplicio-mapper instalados (PyPI)" || \
    echo -e "${YELLOW}⚠${NC} PyPI packages não disponíveis — instale manualmente com pip"

# ── 3. Config.yaml — MCP server + plugin ──────────────────────────────
# Simplicio Agent usa ~/.simplicio_agent como home de perfil por padrão.
# Mantemos o nome HERMES_HOME internamente para não quebrar o código legado.
HERMES_HOME="${HERMES_HOME:-$HOME/.simplicio_agent}"
mkdir -p "$HERMES_HOME"

if [ -f "$HERMES_HOME/config.yaml" ]; then
    # Já existe — verificar se precisa adicionar MCP e plugin
    if ! grep -q "simplicio:" "$HERMES_HOME/config.yaml" 2>/dev/null; then
        echo -e "${CYAN}→${NC} Adicionando MCP server simplicio ao config.yaml..."
        cat >> "$HERMES_HOME/config.yaml" << 'MCP_CONFIG'

# ── Simplicio Runtime (MCP) ────────────────────────────────────────────
mcp_servers:
  simplicio:
    command: ~/.local/bin/simplicio
    args:
      - serve
      - --mcp
      - --stdio
    timeout: 120
    connect_timeout: 60

plugins:
  enabled:
    - simplicio
  disabled: []
MCP_CONFIG
        echo -e "${GREEN}✓${NC} MCP server + plugin configurados no config.yaml"
    else
        echo -e "${GREEN}✓${NC} MCP server simplicio já configurado"
    fi
else
    echo -e "${CYAN}→${NC} Criando config.yaml com MCP server simplicio..."
    cat > "$HERMES_HOME/config.yaml" << 'MCP_CONFIG'
# ── Simplicio Runtime (MCP) ────────────────────────────────────────────
mcp_servers:
  simplicio:
    command: ~/.local/bin/simplicio
    args:
      - serve
      - --mcp
      - --stdio
    timeout: 120
    connect_timeout: 60

plugins:
  enabled:
    - simplicio
  disabled: []
MCP_CONFIG
    echo -e "${GREEN}✓${NC} config.yaml criado com MCP server simplicio"
fi

# ── 4. SOUL.md — Identidade Simplicio Agent ────────────────────────────
if [ ! -f "$HERMES_HOME/SOUL.md" ]; then
    echo -e "${CYAN}→${NC} Criando SOUL.md com identidade Simplicio Agent..."
    # Usa o template do default_soul.py (system prompt integrado)
    # O template é inserido no código-fonte e será usado na primeira execução
    echo -e "${GREEN}✓${NC} SOUL.md será criado pelo template padrão na primeira execução"
fi

# ── 5. Plugin simplicio ────────────────────────────────────────────────
PLUGINS_DIR="$SCRIPT_DIR/plugins"
if [ -d "$PLUGINS_DIR/simplicio" ]; then
    echo -e "${CYAN}→${NC} Instalando plugin simplicio..."
    mkdir -p "$HERMES_HOME/plugins"
    # Symlink para que atualizações no source reflitam automaticamente
    ln -sfn "$PLUGINS_DIR/simplicio" "$HERMES_HOME/plugins/simplicio" 2>/dev/null || \
        cp -rn "$PLUGINS_DIR/simplicio" "$HERMES_HOME/plugins/" 2>/dev/null || true
    echo -e "${GREEN}✓${NC} Plugin simplicio instalado em $HERMES_HOME/plugins/simplicio"
fi

# ── 6. Simplicio skill ──────────────────────────────────────────────────
SKILLS_DIR="$HERMES_HOME/skills"
mkdir -p "$SKILLS_DIR"
BUNDLED_SKILL="$SCRIPT_DIR/skills/simplicio"
if [ -d "$BUNDLED_SKILL" ]; then
    cp -rn "$BUNDLED_SKILL" "$SKILLS_DIR/" 2>/dev/null || true
    echo -e "${GREEN}✓${NC} Skill simplicio instalada em $SKILLS_DIR/simplicio"
fi

echo -e "${GREEN}✓${NC} Ecossistema Simplicio instalado!"

# ── 7. Inicializar tudo — fully functional out of the box ──────────────
echo ""
echo -e "${CYAN}→${NC} Inicializando Simplicio Runtime (banco neural, provider, MCP)..."
echo ""

SIMPLICIO_CMD="$BIN_DIR/simplicio"

# 7a. Neural memory database
if [ -f "$HOME/.simplicio/memory/simplicio-memory.sqlite" ]; then
    echo -e "${GREEN}✓${NC} Banco neural já existe ($("$SIMPLICIO_CMD" memory status 2>/dev/null | grep 'memory_items=' | head -1))"
else
    echo -e "${CYAN}→${NC} Inicializando banco neural (SQLite FTS5 + vector)..."
    "$SIMPLICIO_CMD" init --quick --non-interactive 2>/dev/null || \
        "$SIMPLICIO_CMD" onboard --non-interactive 2>/dev/null || \
        echo -e "${YELLOW}⚠${NC} Init automático não disponível — crie provider manualmente com: simplicio init --quick"
    
    # Tenta forçar criação do banco de memória
    "$SIMPLICIO_CMD" memory status 2>/dev/null || true
    if [ -f "$HOME/.simplicio/memory/simplicio-memory.sqlite" ]; then
        echo -e "${GREEN}✓${NC} Banco neural inicializado"
    else
        echo -e "${YELLOW}⚠${NC} Banco neural será criado na primeira execução"
    fi
fi

# 7b. Provider/model onboarding (non-interactive se possível)
if "$SIMPLICIO_CMD" init show &>/dev/null; then
    echo -e "${GREEN}✓${NC} Provider já configurado ($("$SIMPLICIO_CMD" init show 2>/dev/null | head -1))"
else
    echo -e "${CYAN}→${NC} Provider não configurado — configurar via setup wizard após instalação"
    echo -e "${CYAN}→${NC} Ou execute: simplicio init --quick (auto-detecta por env vars)"
fi

# 7c. Registrar MCP clients
echo -e "${CYAN}→${NC} Registrando MCP..."
if "$SIMPLICIO_CMD" mcp list &>/dev/null; then
    "$SIMPLICIO_CMD" mcp register 2>/dev/null || true
    echo -e "${GREEN}✓${NC} MCP registrado em clients disponíveis"
else
    echo -e "${YELLOW}⚠${NC} MCP register não disponível — pule este passo"
fi

# 7c-2. Routing note: not every command has an MCP tool. Read-only status
# checks (cron/gateway/hooks) are real MCP tools now; everything else in
# the long tail (workflow, issue-factory, agent, desktop, plan/decide/
# sprint/learn, doctor/tokio-runtime/health/settings) is an intentional
# CLI fallback, not missing coverage — see
# docs/mcp-low-frequency-bridges.md and mcp_low_freq_bridges.py.
echo -e "${CYAN}→${NC} MCP vs CLI: comandos raros (cron/gateway/workflow/issue-factory/"
echo -e "  agent/desktop/plan/decide/sprint/learn/doctor) seguem "
echo -e "  docs/mcp-low-frequency-bridges.md — cron/gateway/hooks já são MCP,"
echo -e "  o resto usa CLI fallback explícito (nunca falha em silêncio)."

# 7d. Health check
echo ""
echo -e "${CYAN}→${NC} Verificando saúde do Simplicio Runtime..."
"$SIMPLICIO_CMD" doctor 2>/dev/null || \
    echo -e "${YELLOW}⚠${NC} Doctor não disponível (compile simplicio-runtime para obter auto-diagnóstico)"

echo -e "${GREEN}✓${NC} Simplicio Runtime pronto para uso!"

HERMES_SKILLS_DIR="${HERMES_HOME:-$HOME/.hermes}/skills"
mkdir -p "$HERMES_SKILLS_DIR"

echo ""
echo "Syncing bundled skills to ~/.hermes/skills/ ..."
if "$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/tools/skills_sync.py" 2>/dev/null; then
    echo -e "${GREEN}✓${NC} Skills synced"
else
    # Fallback: copy if sync script fails (missing deps, etc.)
    if [ -d "$SCRIPT_DIR/skills" ]; then
        cp -rn "$SCRIPT_DIR/skills/"* "$HERMES_SKILLS_DIR/" 2>/dev/null || true
        echo -e "${GREEN}✓${NC} Skills copied"
    fi
fi

# ============================================================================
# Done
# ============================================================================

echo ""
echo -e "${GREEN}✓ Setup complete!${NC}"
echo ""
echo "Next steps:"
echo ""
if is_termux; then
    echo "  1. Run the setup wizard to configure API keys:"
    echo "     simplicio-agent setup"
    echo ""
    echo "  2. Start chatting:"
    echo "     hermes"
    echo ""
else
    echo "  1. Reload your shell:"
    echo "     source $SHELL_CONFIG"
    echo ""
    echo "  2. Run the setup wizard to configure API keys:"
    echo "     simplicio-agent setup"
    echo ""
    echo "  3. Start chatting:"
    echo "     hermes"
    echo ""
fi
echo "Other commands:"
echo "  simplicio-agent status        # Check configuration"
if is_termux; then
    echo "  simplicio-agent gateway       # Run gateway in foreground"
else
    echo "  simplicio-agent gateway install # Install gateway service (messaging + cron)"
fi
echo "  simplicio-agent cron list     # View scheduled jobs"
echo "  simplicio-agent doctor        # Diagnose issues"
echo "  simplicio version    # Simplicio Runtime version"
echo "  simplicio runtime map --repo . --for-llm markdown  # Orientação do repo"
echo ""

# Ask if they want to run setup wizard now
read -p "Would you like to run the setup wizard now? [Y/n] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
    echo ""
    # Run directly with venv Python (no activation needed)
    "$SCRIPT_DIR/venv/bin/python" -m hermes_cli.main setup
fi
