#!/bin/bash
# ============================================================================
# Simplicio Agent Installer - curl | sh
# ============================================================================
# Instala o Simplicio Agent a partir de binarios compilados publicados no
# GitHub Releases. Detecta SO/arquitetura, baixa o binario, verifica SHA256,
# instala em ~/.local/bin/simplicio e executa a configuracao pos-instalacao.
#
# Uso:
#   curl -fsSL https://simpleti.com.br/simplicio/install.sh | sh
#
# Opcoes:
#   curl -fsSL https://simpleti.com.br/simplicio/install.sh | sh -s -- --version v0.22.0
#   curl -fsSL https://simpleti.com.br/simplicio/install.sh | sh -s -- --dir /custom/path
#   curl -fsSL https://simpleti.com.br/simplicio/install.sh | sh -s -- --no-config
#
# ============================================================================

set -euo pipefail

# ============================================================================
# Configuracao
# ============================================================================

REPO_OWNER="wesleysimplicio"
REPO_NAME="simplicio"
REPO="https://github.com/${REPO_OWNER}/${REPO_NAME}"
API_URL="https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/releases/latest"
DOWNLOAD_BASE="https://github.com/${REPO_OWNER}/${REPO_NAME}/releases/download"

# Fallback: download do codigo via git se binario nao estiver disponivel
FALLBACK_CLONE_URL="${REPO}.git"
FALLBACK_BRANCH="main"

INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/bin}"
DATA_DIR="${DATA_DIR:-$HOME/.simplicio_agent}"
CONFIG_DIR="${CONFIG_DIR:-$HOME/.simplicio}"
BINARY_NAME="simplicio"

# Opcoes
REQUESTED_VERSION=""
SKIP_CONFIG=false
JSON_OUTPUT=false

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

# ============================================================================
# Parse de argumentos
# ============================================================================

while [[ $# -gt 0 ]]; do
    case $1 in
        --version|-v)
            REQUESTED_VERSION="$2"
            shift 2
            ;;
        --dir|--install-dir)
            INSTALL_DIR="$2"
            shift 2
            ;;
        --data-dir)
            DATA_DIR="$2"
            shift 2
            ;;
        --no-config|--skip-config)
            SKIP_CONFIG=true
            shift
            ;;
        --json)
            JSON_OUTPUT=true
            shift
            ;;
        -h|--help)
            echo "Simplicio Agent Installer"
            echo ""
            echo "Uso: curl -fsSL https://simpleti.com.br/simplicio/install.sh | sh"
            echo ""
            echo "Opcoes:"
            echo "  --version, -v TAG   Versao especifica (ex: v0.22.0)"
            echo "  --dir, --install-dir DIR  Diretorio de instalacao (default: ~/.local/bin)"
            echo "  --data-dir DIR       Diretorio de dados (default: ~/.simplicio_agent)"
            echo "  --no-config          Pula configuracao pos-instalacao"
            echo "  --json               Saida em JSON"
            echo "  -h, --help           Mostra esta ajuda"
            exit 0
            ;;
        *)
            echo "Opcao desconhecida: $1"
            echo "Use -h para ajuda."
            exit 1
            ;;
    esac
done

# ============================================================================
# Helpers
# ============================================================================

log_info()  { echo -e "${CYAN}->${NC} $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
log_error() { echo -e "${RED}[X]${NC} $1"; }

cleanup() {
    local tmpdir="${1:-}"
    [ -n "$tmpdir" ] && [ -d "$tmpdir" ] && rm -rf "$tmpdir"
}

print_banner() {
    echo ""
    echo -e "${BLUE}${BOLD}"
    echo "-------------------------------------------------------------"
    echo "       Simplicio Agent Installer"
    echo "-------------------------------------------------------------"
    echo "  Seu agente AI pessoal, auto-melhoravel e open-source."
    echo "-------------------------------------------------------------"
    echo -e "${NC}"
}

have_command() {
    command -v "$1" >/dev/null 2>&1
}

# ============================================================================
# Deteccao de SO / Arquitetura
# ============================================================================

detect_os_arch() {
    local os arch

    case "$(uname -s)" in
        Linux*)  os="linux" ;;
        Darwin*) os="macos" ;;
        CYGWIN*|MINGW*|MSYS*)
            log_error "Windows detectado. Use o instalador PowerShell:"
            log_info "  iex (irm https://simpleti.com.br/simplicio/install.ps1)"
            return 1
            ;;
        *)
            log_error "Sistema operacional nao suportado: $(uname -s)"
            return 1
            ;;
    esac

    case "$(uname -m)" in
        x86_64|amd64)  arch="x86_64" ;;
        aarch64|arm64) arch="aarch64" ;;
        armv7l|armv6l) arch="armv7" ;;
        *)
            log_error "Arquitetura nao suportada: $(uname -m)"
            return 1
            ;;
    esac

    echo "${os}_${arch}"
}

# ============================================================================
# Obter versao mais recente do GitHub
# ============================================================================

get_latest_version() {
    if have_command curl; then
        curl -sSfL "$API_URL" 2>/dev/null | grep '"tag_name"' | cut -d'"' -f4 || true
    elif have_command wget; then
        wget -qO- "$API_URL" 2>/dev/null | grep '"tag_name"' | cut -d'"' -f4 || true
    else
        echo ""
    fi
}

# ============================================================================
# Download de binario
# ============================================================================

download_binary() {
    local version="$1"
    local os_arch="$2"
    local tmpdir="$3"

    local binary_url="${DOWNLOAD_BASE}/${version}/simplicio-${os_arch}"
    local checksum_url="${DOWNLOAD_BASE}/${version}/simplicio-${os_arch}.sha256"

    local binary_path="${tmpdir}/simplicio"
    local checksum_path="${tmpdir}/simplicio.sha256"

    log_info "Baixando Simplicio Agent ${version} (${os_arch})..."

    if have_command curl; then
        log_info "  curl -fsSL \"${binary_url}\""
        if ! curl -fsSL -o "$binary_path" "$binary_url" 2>/dev/null; then
            return 1
        fi
        curl -fsSL -o "$checksum_path" "$checksum_url" 2>/dev/null || true
    elif have_command wget; then
        log_info "  wget -q \"${binary_url}\""
        if ! wget -q -O "$binary_path" "$binary_url" 2>/dev/null; then
            return 1
        fi
        wget -q -O "$checksum_path" "$checksum_url" 2>/dev/null || true
    else
        log_error "Nem curl nem wget encontrados. Instale um deles e tente novamente."
        return 1
    fi

    if [ ! -f "$binary_path" ] || [ ! -s "$binary_path" ]; then
        log_error "Download falhou: arquivo vazio ou nao encontrado."
        return 1
    fi

    if [ -f "$checksum_path" ] && [ -s "$checksum_path" ]; then
        log_info "Verificando checksum SHA256..."
        local expected_checksum
        expected_checksum=$(cut -d' ' -f1 < "$checksum_path" | tr '[:upper:]' '[:lower:]')
        local actual_checksum
        if have_command sha256sum; then
            actual_checksum=$(sha256sum "$binary_path" | cut -d' ' -f1)
        elif have_command shasum; then
            actual_checksum=$(shasum -a 256 "$binary_path" | cut -d' ' -f1)
        elif have_command openssl; then
            actual_checksum=$(openssl dgst -sha256 "$binary_path" | cut -d' ' -f2)
        else
            log_warn "Nenhuma ferramenta SHA256 encontrada. Pulando verificacao."
            chmod +x "$binary_path"
            echo "$binary_path"
            return 0
        fi

        if [ "$actual_checksum" != "$expected_checksum" ]; then
            log_error "Checksum NAO confere!"
            log_error "  Esperado: ${expected_checksum}"
            log_error "  Obtido:   ${actual_checksum}"
            log_warn "O binario pode estar corrompido ou foi adulterado."
            log_info "Tentando fallback via pip..."
            return 2
        fi
        log_ok "Checksum SHA256 verificado com sucesso."
    else
        log_warn "Arquivo SHA256 nao encontrado para ${version}. Pulando verificacao."
        log_warn "AVISO: A integridade do binario nao pde ser verificada."
    fi

    chmod +x "$binary_path"
    echo "$binary_path"
}

# ============================================================================
# Instalacao via pip (fallback)
# ============================================================================

install_via_pip() {
    log_info "Instalando via pip diretamente do GitHub..."

    if ! have_command python3 && ! have_command python; then
        log_error "Python nao encontrado. Instale Python 3.11+ e tente novamente."
        return 1
    fi

    local python_cmd
    if have_command python3; then
        python_cmd="python3"
    else
        python_cmd="python"
    fi

    local py_version
    py_version=$($python_cmd -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0")
    local py_major
    py_major=$(echo "$py_version" | cut -d. -f1)
    local py_minor
    py_minor=$(echo "$py_version" | cut -d. -f2)

    if [ "$py_major" -lt 3 ] || { [ "$py_major" -eq 3 ] && [ "$py_minor" -lt 11 ]; }; then
        log_error "Python ${py_version} eh muito antigo. Necessario Python 3.11+."
        return 1
    fi

    log_info "Python ${py_version} encontrado."

    if have_command pip3; then
        log_info "pip install git+${REPO}.git"
        pip3 install --user "git+${REPO}.git" 2>&1 || {
            log_warn "pip install falhou. Tentando com --break-system-packages..."
            pip3 install --user --break-system-packages "git+${REPO}.git" 2>&1 || return 1
        }
    else
        log_info "python -m pip install --user git+${REPO}.git"
        $python_cmd -m pip install --user "git+${REPO}.git" 2>&1 || {
            log_warn "pip install falhou. Tentando com --break-system-packages..."
            $python_cmd -m pip install --user --break-system-packages "git+${REPO}.git" 2>&1 || return 1
        }
    fi

    if have_command simplicio; then
        log_ok "Simplicio Agent instalado via pip!"
        return 0
    fi

    if [ -f "$HOME/.local/bin/simplicio" ]; then
        log_ok "Simplicio Agent instalado em ~/.local/bin/simplicio"
        return 0
    fi

    return 1
}

# ============================================================================
# Instalacao via git clone (fallback final)
# ============================================================================

install_via_git() {
    log_info "Instalando via git clone (fallback final)..."

    if ! have_command git; then
        log_error "Git nao encontrado. Instale git e tente novamente."
        return 1
    fi

    local checkout_dir="${DATA_DIR}/source"
    mkdir -p "$checkout_dir"

    if [ -d "${checkout_dir}/.git" ]; then
        log_info "Atualizando repositorio existente em ${checkout_dir}..."
        (cd "$checkout_dir" && git pull origin "$FALLBACK_BRANCH") 2>&1 || true
    else
        log_info "Clonando repositorio..."
        git clone --depth 1 --branch "$FALLBACK_BRANCH" "$FALLBACK_CLONE_URL" "$checkout_dir" 2>&1 || {
            log_error "Falha ao clonar repositorio."
            return 1
        }
    fi

    log_info "Criando entrypoint wrapper em ${INSTALL_DIR}/simplicio..."
    mkdir -p "$INSTALL_DIR"

    cat > "${INSTALL_DIR}/simplicio" << 'WRAPPER'
#!/bin/bash
# Simplicio Agent wrapper - executa a partir do checkout git
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0" 2>/dev/null || echo "$0")")" && pwd)"
CHECKOUT_DIR="$(dirname "$SCRIPT_DIR")/../.simplicio_agent/source"
if [ -d "$CHECKOUT_DIR" ]; then
    cd "$CHECKOUT_DIR"
    exec python3 -m hermes_cli.main "$@"
else
    echo "Simplicio Agent nao encontrado em $CHECKOUT_DIR"
    echo "Reinstale com: curl -fsSL https://simpleti.com.br/simplicio/install.sh | sh"
    exit 1
fi
WRAPPER

    chmod +x "${INSTALL_DIR}/simplicio"

    if have_command pip3; then
        log_info "Instalando dependencias Python..."
        cd "$checkout_dir"
        pip3 install --user -e . 2>&1 || \
        pip3 install --user --break-system-packages -e . 2>&1 || \
        log_warn "Nao foi possivel instalar dependencias automaticamente."
    fi

    log_ok "Simplicio Agent instalado via git clone!"
    return 0
}

# ============================================================================
# Pos-instalacao
# ============================================================================

run_post_install() {
    log_info "Executando configuracao pos-instalacao..."

    local post_install_script=""

    for candidate in \
        "${DATA_DIR}/source/scripts/post-install-config.sh" \
        "${HOME}/.simplicio/source/scripts/post-install-config.sh" \
        "$(dirname "$0")/post-install-config.sh" \
        "./post-install-config.sh"; do
        if [ -f "$candidate" ]; then
            post_install_script="$candidate"
            break
        fi
    done

    if [ -z "$post_install_script" ] && have_command curl; then
        local raw_url="https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/main/scripts/post-install-config.sh"
        local tmpfile
        tmpfile=$(mktemp)
        if curl -fsSL -o "$tmpfile" "$raw_url" 2>/dev/null; then
            post_install_script="$tmpfile"
        fi
    fi

    if [ -n "$post_install_script" ] && [ -f "$post_install_script" ]; then
        log_info "Rodando ${post_install_script}..."
        bash "$post_install_script" || log_warn "Post-install retornou codigo nao-zero (ignorado)."
        log_ok "Configuracao pos-instalacao concluida."
    else
        log_warn "Script post-install-config.sh nao encontrado."
        log_info "Criando diretorios basicos manualmente..."
        mkdir -p "$DATA_DIR/skills"
        mkdir -p "$CONFIG_DIR"
        log_info "Diretorios criados:"
        log_info "  ${DATA_DIR}/skills"
        log_info "  ${CONFIG_DIR}"
    fi
}

# ============================================================================
# Adicionar ao PATH
# ============================================================================

ensure_path() {
    local install_dir="$1"

    case ":$PATH:" in
        *":${install_dir}:"*) return 0 ;;
    esac

    local shell_rc=""
    local shell_name
    shell_name="$(basename "${SHELL:-/bin/bash}")"

    case "$shell_name" in
        zsh)  shell_rc="${HOME}/.zshrc" ;;
        bash) shell_rc="${HOME}/.bashrc" ;;
        fish) shell_rc="${HOME}/.config/fish/config.fish" ;;
        *)    shell_rc="${HOME}/.profile" ;;
    esac

    local export_line="export PATH=\"${install_dir}:\$PATH\""

    if [ -f "$shell_rc" ] && grep -qF "$install_dir" "$shell_rc" 2>/dev/null; then
        log_info "PATH ja configurado em ${shell_rc}."
        return 0
    fi

    echo "" >> "$shell_rc"
    echo "# Adicionado pelo instalador do Simplicio Agent" >> "$shell_rc"
    echo "$export_line" >> "$shell_rc"

    log_info "PATH atualizado em ${shell_rc}."
    log_info "Recarregue o shell com: source ${shell_rc}"
}

# ============================================================================
# Verificacao de instalacao
# ============================================================================

verify_installation() {
    local binary_path="$1"

    log_info "Verificando instalacao..."

    if [ ! -f "$binary_path" ]; then
        log_error "Binario nao encontrado em ${binary_path}."
        return 1
    fi

    if [ ! -x "$binary_path" ]; then
        log_error "Binario sem permissao de execucao: ${binary_path}."
        chmod +x "$binary_path" || return 1
    fi

    local version_output
    version_output=$("$binary_path" --version 2>/dev/null || "$binary_path" version 2>/dev/null || echo "")

    if [ -n "$version_output" ]; then
        log_ok "Simplicio Agent ${version_output} instalado com sucesso!"
    else
        log_ok "Simplicio Agent instalado em ${binary_path}."
        log_info "Execute 'simplicio --help' para ver as opcoes disponiveis."
    fi

    return 0
}

print_success_message() {
    local binary_path="$1"

    echo ""
    echo -e "${GREEN}${BOLD}"
    echo "-------------------------------------------------------------"
    echo "    Simplicio Agent instalado com sucesso!"
    echo "-------------------------------------------------------------"
    echo -e "${NC}"
    echo ""
    echo "  Instalacao:"
    echo "   Binario:  ${binary_path}"
    echo "   Dados:    ${DATA_DIR}"
    echo "   Config:   ${CONFIG_DIR}"
    echo ""
    echo "  Comandos:"
    echo "   simplicio              Iniciar o agente"
    echo "   simplicio --help       Ver opcoes disponiveis"
    echo "   simplicio setup        Configurar chaves de API"
    echo ""

    case ":$PATH:" in
        *":${INSTALL_DIR}"*) ;;
        *)
            echo "  Adicione ${INSTALL_DIR} ao seu PATH ou recarregue o shell:"
            local shell_name
            shell_name="$(basename "${SHELL:-/bin/bash}")"
            case "$shell_name" in
                zsh)  echo "   source ~/.zshrc" ;;
                bash) echo "   source ~/.bashrc" ;;
                fish) echo "   source ~/.config/fish/config.fish" ;;
                *)    echo "   export PATH=\"${INSTALL_DIR}:\$PATH\"" ;;
            esac
            echo ""
            ;;
    esac
}

# ============================================================================
# Main
# ============================================================================

main() {
    print_banner

    # -- Detectar SO --
    local os_arch
    os_arch=$(detect_os_arch) || exit 1
    log_info "Sistema detectado: ${os_arch}"

    # -- Garantir diretorio de instalacao --
    mkdir -p "$INSTALL_DIR"
    log_info "Diretorio de instalacao: ${INSTALL_DIR}"

    # -- Obter versao --
    local version="$REQUESTED_VERSION"
    if [ -z "$version" ]; then
        log_info "Buscando versao mais recente..."
        version=$(get_latest_version)
        if [ -z "$version" ]; then
            log_warn "Nao foi possivel consultar a versao mais recente."
            log_info "Tentando versao 'latest'..."
            version="latest"
        else
            log_info "Versao mais recente: ${version}"
        fi
    else
        log_info "Versao solicitada: ${version}"
    fi

    # -- Criar diretorio temporario --
    local tmpdir
    tmpdir=$(mktemp -d) || {
        log_error "Falha ao criar diretorio temporario."
        exit 1
    }
    trap 'cleanup "$tmpdir"' EXIT

    # -- Tentar download do binario --
    local binary_path=""
    local install_method="binary"

    if [ "$version" = "latest" ]; then
        for try_version in "v0.22.0" "v0.21.1"; do
            log_info "Tentando ${try_version}..."
            binary_path=$(download_binary "$try_version" "$os_arch" "$tmpdir" 2>/dev/null || echo "")
            [ -n "$binary_path" ] && [ -f "$binary_path" ] && break
        done
    else
        binary_path=$(download_binary "$version" "$os_arch" "$tmpdir" 2>/dev/null || echo "")
    fi

    # -- Fallback: pip --
    if [ -z "$binary_path" ] || [ ! -f "$binary_path" ]; then
        # Product/enterprise installs can forbid pulling the full source tree
        # to the customer's machine. When SIMPLICIO_NO_SOURCE_FALLBACK is set
        # and no compiled binary is available, fail loudly instead of silently
        # falling back to a pip-from-git or git-clone source install.
        if [ -n "${SIMPLICIO_NO_SOURCE_FALLBACK:-}" ]; then
            log_error "Binario compilado nao encontrado para ${os_arch}."
            log_error "SIMPLICIO_NO_SOURCE_FALLBACK esta definido: instalacao"
            log_error "somente por binario. Nenhum codigo-fonte foi baixado."
            log_error "Solicite um binario para sua plataforma."
            exit 1
        fi
        log_warn "Binario compilado nao encontrado para ${os_arch}."
        log_info "Tentando instalacao via pip (Python)..."
        install_method="pip"
        if install_via_pip; then
            binary_path="${HOME}/.local/bin/simplicio"
        else
            log_warn "Instalacao via pip falhou."
            log_info "Tentando instalacao via git clone..."
            install_method="git"
            if install_via_git; then
                binary_path="${INSTALL_DIR}/simplicio"
            else
                log_error "Todas as tentativas de instalacao falharam."
                log_error "Relate o problema em: ${REPO}/issues"
                exit 1
            fi
        fi
    fi

    # -- Garantir que o binario esta no local correto --
    if [ "$install_method" = "binary" ] && [ -f "$binary_path" ]; then
        local final_path="${INSTALL_DIR}/${BINARY_NAME}"
        cp "$binary_path" "$final_path"
        chmod +x "$final_path"
        binary_path="$final_path"
        log_ok "Binario copiado para ${binary_path}"
    fi

    # -- Pos-instalacao --
    if [ "$SKIP_CONFIG" = false ]; then
        run_post_install
    else
        log_info "Configuracao pos-instalacao pulada (--no-config)."
    fi

    # -- PATH --
    ensure_path "$INSTALL_DIR"

    # -- Verificacao --
    if verify_installation "$binary_path"; then
        print_success_message "$binary_path"
    else
        log_error "Verificacao de instalacao falhou."
        exit 1
    fi
}

main

# Se o repositorio agent for privado, tentar baixar binario do runtime
if [ "$REPO_NAME" = "simplicio-agent" ]; then
    FALLBACK_REPO="simplicio"
    echo "[info] $REPO e privado - baixando binario de $FALLBACK_REPO"
    # As URLs de download usarao o runtime, mas o produto e o Agent
fi
