#!/usr/bin/env bash
#
# import.sh — Mecanismo executável do pipeline Hermes Original → Hermes Turbo → Simplicio Agent
#
# Pipeline (upstream -> downstream):
#
#   NousResearch/hermes-agent (upstream, v0.18.x)
#     │  git merge/cherry-pick + delta-review
#     ▼
#   wesleysimplicio/hermes-turbo-agent (perf mods)
#     │  merge do turbo (TUDO que melhora flui — política #62)
#     ▼
#   wesleysimplicio/simplicio-agent (destino)
#     │  + integração do ecossistema (operators)
#     ▼
#   simplicio-agent = turbo + ecossistema integrado
#
# Issue de referência: #66 (este script)
# Política de import: #19 (F1 inventário) e #62 (governança do pipeline)
# Denylist CLI-only: #56
# Binding do ecossistema: #20 (F2)
#
# Uso:
#   scripts/importer/import.sh <subcomando> [--dry-run|--apply] [opções]
#
# Subcomandos:
#   upstream    Estágio 1 — delta-review de release upstream→turbo
#   turbo       Estágio 2 — merge turbo→simplicio com preservação de autoria
#   ecosystem   Estágio 3 — integração dos operators do ecossistema
#   audit       Exibir histórico de imports registrados
#   gate        Verificar dívida de sync (issues-espelho abertas > N dias)
#   status      Resumo do pipeline: o que foi importado, o que está pendente
#
# Flags comuns:
#   --dry-run   (padrão) apenas reportar, nunca escrever
#   --apply     efetuar mudanças destrutivas
#   --version   especificar versão para import upstream
#   --verbose   saída detalhada
#
# Ambiente:
#   SIMPLICIO_REPO   este repositório (default: git toplevel do script)
#   TURBO_REPO       hermes-turbo-agent (default: ~/Projetos/ai/hermes-turbo-agent)
#   HERMES_UPSTREAM  URL do upstream Hermes (default: https://github.com/NousResearch/hermes-agent.git)
#   ECOSYSTEM_REPOS  paths dos repos do ecossistema para import ecosystem
#
# Exemplos:
#   # Estágio 1 — analisar diff da release v0.19.0 do upstream contra o turbo
#   scripts/importer/import.sh upstream --version v0.19.0
#
#   # Estágio 2 — importar perf deltas do turbo
#   scripts/importer/import.sh turbo
#   scripts/importer/import.sh turbo --apply
#
#   # Estágio 3 — integrar operators do ecossistema
#   scripts/importer/import.sh ecosystem
#   scripts/importer/import.sh ecosystem --apply
#
#   # Auditoria e gate
#   scripts/importer/import.sh audit
#   scripts/importer/import.sh gate
#   scripts/importer/import.sh status

set -euo pipefail

# --------------------------------------------------------------------------
# Paths e ambiente
# --------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIMPLICIO_REPO="$(cd "$SCRIPT_DIR/../.." && pwd)"
ECOSYSTEM_SYNC="$SIMPLICIO_REPO/scripts/sync/ecosystem-sync.sh"
HERMES_IMPORT_DIR="$SIMPLICIO_REPO/docs/hermes-import"

TURBO_REPO="${TURBO_REPO:-$HOME/Projetos/ai/hermes-turbo-agent}"
HERMES_UPSTREAM="${HERMES_UPSTREAM:-https://github.com/NousResearch/hermes-agent.git}"

# --------------------------------------------------------------------------
# Denylist — superfície que NUNCA deve ser importada (#56 CLI-only)
# Caminhos relativos à raiz do repo que são proibidos.
# --------------------------------------------------------------------------
DENYLIST=(
  "desktop/"
  "website/"
  "web/"
  "electron/"
  "app/"
  "src/renderer/"
  "static/"
  "public/"
  "gui/"
  "ui/"
)

# --------------------------------------------------------------------------
# Cores para output
# --------------------------------------------------------------------------
_c_reset=""; _c_info=""; _c_warn=""; _c_err=""; _c_ok=""; _c_skip=""; _c_bold=""
if [ -t 1 ]; then
  _c_reset="\033[0m"; _c_info="\033[36m"; _c_warn="\033[33m"
  _c_err="\033[31m"; _c_ok="\033[32m"; _c_skip="\033[35m"; _c_bold="\033[1m"
fi

log()       { printf "%b[import]%b %s\n"        "$_c_info" "$_c_reset" "$*"; }
log_ok()    { printf "%b[ ok ]%b %s\n"           "$_c_ok"   "$_c_reset" "$*"; }
log_warn()  { printf "%b[warn]%b %s\n"           "$_c_warn" "$_c_reset" "$*" >&2; }
log_err()   { printf "%b[FAIL]%b %s\n"           "$_c_err"  "$_c_reset" "$*" >&2; }
log_skip()  { printf "%b[skip]%b %s\n"           "$_c_skip" "$_c_reset" "$*"; }
log_review(){ printf "%b[HUMAN]%b %s\n"          "$_c_warn" "$_c_reset" "$*"; }
log_section(){ printf "\n%b━━━ %s ━━━%b\n"       "$_c_bold" "$*" "$_c_reset"; }
hr()        { printf -- "----------------------------------------------------------------------\n"; }

die() { log_err "$*"; exit 1; }

# --------------------------------------------------------------------------
# Flags globais
# --------------------------------------------------------------------------
APPLY=0
VERBOSE=0
IMPORT_VERSION=""

parse_common_flags() {
  local rest=()
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --apply)     APPLY=1 ;;
      --dry-run)   APPLY=0 ;;
      --verbose)   VERBOSE=1 ;;
      --version)   shift; IMPORT_VERSION="${1:-}"; [ -n "$IMPORT_VERSION" ] || die "--version requer um valor" ;;
      *)           rest+=("$1") ;;
    esac
    shift
  done
  REMAINING_ARGS=("${rest[@]:-}")
}

mode_banner() {
  if [ "$APPLY" -eq 1 ]; then
    log_warn "MODO: --apply (operações destrutivas ATIVADAS)"
  else
    log "MODO: --dry-run (nenhuma alteração será feita; use --apply para efetivar)"
  fi
}

# --------------------------------------------------------------------------
# Utilitários
# --------------------------------------------------------------------------

# Verifica se o ecosystem-sync.sh existe
_ensure_ecosystem_sync() {
  if [ ! -f "$ECOSYSTEM_SYNC" ]; then
    die "ecosystem-sync.sh não encontrado em: $ECOSYSTEM_SYNC"
  fi
}

# Gera nome de arquivo de log de auditoria
_audit_log_path() {
  local prefix="${1:-import}"
  local date_suffix
  date_suffix="$(date +%Y-%m-%d)"
  echo "$HERMES_IMPORT_DIR/${date_suffix}-${prefix}-log.md"
}

# Escreve cabeçalho de log de auditoria
_audit_log_header() {
  local logfile="$1" title="$2" source="$3" target="$4" version="${5:-}"
  mkdir -p "$HERMES_IMPORT_DIR"
  {
    echo "# Import Log — $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
    echo "## $title"
    echo ""
    echo "- **Fonte:** $source"
    echo "- **Destino:** $target"
    [ -n "$version" ] && echo "- **Versão:** $version"
    echo "- **Modo:** $([ "$APPLY" -eq 1 ] && echo 'apply' || echo 'dry-run')"
    echo ""
    echo "## Itens Processados"
    echo ""
    echo "| Categoria | Status | Descrição | Evidência |"
    echo "|---|---|---|---|"
  } > "$logfile"
  log_ok "Log de auditoria iniciado: $logfile"
}

# Escreve entrada no log de auditoria
_audit_log_entry() {
  local logfile="$1" category="$2" status="$3" description="$4" evidence="$5"
  {
    printf "| %s | %s | %s | %s |\n" "$category" "$status" "$description" "$evidence"
  } >> "$logfile"
}

# Finaliza o log de auditoria
_audit_log_footer() {
  local logfile="$1" result="$2"
  {
    echo ""
    echo "## Resultado Final"
    echo ""
    echo "**$result**"
    echo ""
    echo "---"
    echo "_Gerado automaticamente por scripts/importer/import.sh em $(date '+%Y-%m-%d %H:%M:%S')_"
  } >> "$logfile"
  log_ok "Log de auditoria finalizado: $logfile"
}

# Verifica denylist em um diff/lista de arquivos
_check_denylist() {
  local files_list="$1"
  local found=0
  while IFS= read -r file; do
    for denied in "${DENYLIST[@]}"; do
      if [[ "$file" == "$denied"* ]]; then
        log_skip "DENYLIST: $file (superfície proibida #56)"
        found=$((found + 1))
      fi
    done
  done <<< "$files_list"
  echo "$found"
}

# Obtém a data do último commit de um arquivo (epoch)
_git_file_epoch() {
  local repo="$1" path="$2"
  git -C "$repo" log -1 --format=%ct -- "$path" 2>/dev/null || echo "0"
}

# --------------------------------------------------------------------------
# Estágio 1 — upstream → turbo (delta-review de release)
# --------------------------------------------------------------------------
cmd_upstream() {
  log_section "Estágio 1 — Delta-Review: Upstream → Turbo"

  [ -n "$IMPORT_VERSION" ] || die "Use --version <tag> para especificar a release do upstream (ex: --version v0.19.0)"
  [ -d "$TURBO_REPO/.git" ] || die "Turbo repo não encontrado: $TURBO_REPO (defina TURBO_REPO ou clone hermes-turbo-agent)"

  local logfile
  logfile="$(_audit_log_path "upstream-${IMPORT_VERSION}")"

  mode_banner
  hr
  log "Upstream: $HERMES_UPSTREAM (tag $IMPORT_VERSION)"
  log "Turbo:    $TURBO_REPO"
  hr

  _audit_log_header "$logfile" "Delta-Review Upstream → Turbo — $IMPORT_VERSION" \
    "$HERMES_UPSTREAM ($IMPORT_VERSION)" "$TURBO_REPO" "$IMPORT_VERSION"

  # 1. Registra o remote upstream no turbo (se não existir)
  local existing
  existing="$(git -C "$TURBO_REPO" remote get-url upstream 2>/dev/null || true)"
  if [ -z "$existing" ]; then
    if [ "$APPLY" -eq 1 ]; then
      git -C "$TURBO_REPO" remote add upstream "$HERMES_UPSTREAM"
      log_ok "Remote 'upstream' adicionado em $TURBO_REPO"
    else
      log "Adicionaria remote 'upstream' -> $HERMES_UPSTREAM"
    fi
  else
    log "Remote 'upstream' já existe: $existing"
  fi

  # 2. Fetch da tag de release
  log "Buscando tag $IMPORT_VERSION do upstream..."
  if ! git -C "$TURBO_REPO" fetch --tags upstream 2>/dev/null; then
    log_warn "Falha ao buscar tags do upstream (offline?). Tentando fetch direto..."
    git -C "$TURBO_REPO" fetch upstream 2>/dev/null || log_warn "Falha completa no fetch — continuando com refs locais"
  fi

  if ! git -C "$TURBO_REPO" rev-parse --verify --quiet "refs/tags/$IMPORT_VERSION" >/dev/null 2>&1; then
    log_warn "Tag $IMPORT_VERSION não encontrada no turbo após fetch."
    log_review "Verifique se a tag existe em $HERMES_UPSTREAM ou faça fetch manual:"
    log_review "  git -C $TURBO_REPO fetch upstream '$IMPORT_VERSION'"
    _audit_log_footer "$logfile" "FALHA — Tag $IMPORT_VERSION não encontrada"
    return 1
  fi
  log_ok "Tag $IMPORT_VERSION encontrada no turbo."

  # 3. Diff entre a tag e o HEAD atual do turbo
  local turbo_head
  turbo_head="$(git -C "$TURBO_REPO" rev-parse --abbrev-ref HEAD)"

  local diff_stat
  diff_stat="$(git -C "$TURBO_REPO" diff --stat "HEAD..refs/tags/$IMPORT_VERSION" 2>/dev/null || true)"

  local changed_files
  changed_files="$(git -C "$TURBO_REPO" diff --name-only "HEAD..refs/tags/$IMPORT_VERSION" 2>/dev/null || true)"

  local commit_count
  commit_count="$(git -C "$TURBO_REPO" rev-list --count "HEAD..refs/tags/$IMPORT_VERSION" 2>/dev/null || echo "0")"

  hr
  log "Diff stats: turbo HEAD ($turbo_head) vs tag $IMPORT_VERSION — $commit_count commit(s)"
  echo "$diff_stat" | head -40
  hr

  # 4. Classificação dos deltas
  log "Classificando deltas..."
  echo ""

  _audit_log_entry "$logfile" "---" "---" "---" "---"

  # Áreas quentes para classificação
  local perf_count=0 feature_count=0 deny_count=0 unknown_count=0

  while IFS= read -r file; do
    [ -z "$file" ] && continue
    local classified=0

    # Verifica denylist primeiro
    for denied in "${DENYLIST[@]}"; do
      if [[ "$file" == "$denied"* ]]; then
        log_skip "  [DENY] $file — denylist #56"
        _audit_log_entry "$logfile" "deny" "rejeitado" "$file" "Denylist #56 — superfície CLI-only"
        deny_count=$((deny_count + 1))
        classified=1
        break
      fi
    done
    [ "$classified" -eq 1 ] && continue

    # Classifica por zona quente — performance primeiro
    local matched=0

    # Áreas de performance (exigem A/B obrigatório)
    if  [[ "$file" == *"conversation_loop"* ]] || \
        [[ "$file" == *"tool_executor"* ]] || \
        [[ "$file" == *"tool_dispatch"* ]] || \
        [[ "$file" == *"chat_completion"* ]] || \
        [[ "$file" == *"context_compressor"* ]] || \
        [[ "$file" == *"conversation_compression"* ]] || \
        [[ "$file" == *"_fastjson"* ]] || \
        [[ "$file" == *"_hermes_fast"* ]] || \
        [[ "$file" == *"streaming"* ]] || \
        [[ "$file" == *"rust_ext"* ]] || \
        [[ "$file" == *"async_dag"* ]] || \
        [[ "$file" == *"uvloop"* ]]; then
      log "  [PERF] $file — requer A/B benchmark (#19)"
      _audit_log_entry "$logfile" "perf" "candidato" "$file" "Performance — requer benchmark A/B (#19)"
      perf_count=$((perf_count + 1))
      matched=1
    fi

    [ "$matched" -eq 1 ] && continue

    # Áreas de feature (avaliação manual)
    if  [[ "$file" == *"gateway"* ]] || \
        [[ "$file" == *"provider"* ]] || \
        [[ "$file" == *"adapter"* ]] || \
        [[ "$file" == *"plugin"* ]] || \
        [[ "$file" == *"moa"* ]]; then
      log "  [FEAT] $file — requer avaliação manual"
      _audit_log_entry "$logfile" "feature" "avaliar" "$file" "Nova feature — avaliação manual necessária"
      feature_count=$((feature_count + 1))
      matched=1
    fi

    [ "$matched" -eq 1 ] && continue

    # Arquivo não classificado — código-fonte requer atenção
    if [[ "$file" == *.py ]] || [[ "$file" == *.rs ]] || [[ "$file" == *.sh ]] || [[ "$file" == *.toml ]] || [[ "$file" == *.yaml ]] || [[ "$file" == *.json ]]; then
      log_warn "  [?] $file — não classificado (revisão manual necessária)"
      _audit_log_entry "$logfile" "unknown" "revisar" "$file" "Não classificado automaticamente"
      unknown_count=$((unknown_count + 1))
    else
      log_skip "  [skip] $file — não é código-fonte relevante"
    fi
  done <<< "$changed_files"

  hr
  log "Resumo da classificação:"
  log_ok    "  Performance (A/B obrigatório #19):  $perf_count arquivo(s)"
  log       "  Feature (avaliação manual):         $feature_count arquivo(s)"
  log_skip  "  Rejeitados (denylist #56):          $deny_count arquivo(s)"
  [ "$unknown_count" -gt 0 ] && log_warn "  Não classificados:                 $unknown_count arquivo(s)"
  hr

  if [ "$APPLY" -eq 1 ]; then
    log_review "Candidatos a import encontrados. Para cada item perf:"
    log_review "  1. Crie uma issue-espelho no GitHub com benchmark A/B definido"
    log_review "  2. Implemente o import via: scripts/sync/ecosystem-sync.sh simplicio-pull-perf"
    log_review "  3. Atualize docs/hermes-import/turbo-import-matrix.md"
    log_review "Para features não-perf: avalie manualmente a relevância para simplicio-agent"
  fi

  # Escreve o diff completo no log
  {
    echo ""
    echo "## Diff Completo (HEAD → $IMPORT_VERSION)"
    echo ""
    echo '```'
    echo "$diff_stat"
    echo '```'
    echo ""
    echo "## Detalhamento por Categoria"
    echo ""
    echo "### Performance ($perf_count)"
    echo "Itens que exigem benchmark A/B conforme #19 antes de importar."
    echo ""
    echo "### Feature ($feature_count)"
    echo "Itens que exigem avaliação manual de relevância."
    echo ""
    echo "### Denylist ($deny_count)"
    echo "Superfície web/desktop/electron rejeitada conforme política #56."
    echo ""
    [ "$unknown_count" -gt 0 ] && echo "### Não Classificados ($unknown_count)"
    [ "$unknown_count" -gt 0 ] && echo "Revisão manual necessária para estes itens."
  } >> "$logfile"

  _audit_log_footer "$logfile" "COMPLETO — $perf_count perf, $feature_count feature, $deny_count rejeitados, $unknown_count não classif."

  log_ok "Estágio 1 concluído. Log de auditoria: $logfile"
}

# --------------------------------------------------------------------------
# Estágio 2 — turbo → simplicio (merge com preservação de autoria)
# --------------------------------------------------------------------------
cmd_turbo() {
  log_section "Estágio 2 — Import Turbo → Simplicio"

  mode_banner
  _ensure_ecosystem_sync

  local logfile
  logfile="$(_audit_log_path "turbo-import")"

  [ -d "$TURBO_REPO" ] || die "Turbo repo não encontrado: $TURBO_REPO (defina TURBO_REPO)"
  [ -d "$TURBO_REPO/.git" ] || die "Turbo repo não é um checkout git: $TURBO_REPO"

  hr
  log "Turbo (fonte):       $TURBO_REPO"
  log "Simplicio (destino): $SIMPLICIO_REPO"
  hr

  # 1. Verifica ordering constraint
  log "Verificando ordering constraint (Turbo deve estar atualizado com upstream)..."
  local behind
  behind="$(git -C "$TURBO_REPO" rev-list --count "HEAD..upstream/main" 2>/dev/null || echo "0")"
  if [ "${behind:-0}" -gt 0 ]; then
    log_warn "Turbo está $behind commit(s) ATRÁS do upstream Hermes."
    log_review "Execute primeiro: scripts/sync/ecosystem-sync.sh turbo-absorb-simplicio-agent --apply"
    log_review "Ou ignore este aviso se já verificou manualmente."
    hr
  else
    log_ok "Ordering constraint OK — Turbo está atualizado com upstream."
  fi

  _audit_log_header "$logfile" "Import Turbo → Simplicio" \
    "$TURBO_REPO (hermes-turbo-agent)" "$SIMPLICIO_REPO (simplicio-agent)"

  # 2. Executa o ecosystem-sync.sh simplicio-pull-perf
  log "Executando ecosystem-sync.sh simplicio-pull-perf..."
  hr

  local sync_args=()
  [ "$APPLY" -eq 1 ] && sync_args+=("--apply") || sync_args+=("--dry-run")

  if [ "$APPLY" -eq 1 ]; then
    set +e
    TURBO_REPO="$TURBO_REPO" SIMPLICIO_REPO="$SIMPLICIO_REPO" \
      bash "$ECOSYSTEM_SYNC" simplicio-pull-perf --apply
    local sync_rc=$?
    set -e

    if [ "$sync_rc" -eq 0 ]; then
      log_ok "simplicio-pull-perf concluído com sucesso."
      _audit_log_entry "$logfile" "perf-delta" "sucesso" "Pull do delta de performance do Turbo" "ecosystem-sync.sh simplicio-pull-perf --apply"
    else
      log_warn "simplicio-pull-perf retornou código $sync_rc (podem haver avisos)."
      _audit_log_entry "$logfile" "perf-delta" "parcial" "Pull do delta de performance — rc=$sync_rc" "Verificar output acima"
    fi
  else
    TURBO_REPO="$TURBO_REPO" SIMPLICIO_REPO="$SIMPLICIO_REPO" \
      bash "$ECOSYSTEM_SYNC" simplicio-pull-perf --dry-run
    _audit_log_entry "$logfile" "perf-delta" "dry-run" "Simulação do pull do delta de performance" "ecosystem-sync.sh simplicio-pull-perf --dry-run"
  fi

  hr

  # 3. Verifica denylist no working directory (se apply)
  if [ "$APPLY" -eq 1 ]; then
    log "Verificando denylist (#56) no working directory..."
    local dirty_files
    dirty_files="$(git -C "$SIMPLICIO_REPO" diff --name-only 2>/dev/null || true)"
    if [ -n "$dirty_files" ]; then
      local denied
      denied="$(_check_denylist "$dirty_files")"
      if [ "$denied" -gt 0 ]; then
        log_err "DENYLIST VIOLATION: $denied arquivo(s) da denylist foram tocados!"
        log_review "Reverta as alterações nos arquivos denylist antes de commit."
        _audit_log_entry "$logfile" "denylist" "VIOLAÇÃO" "$denied arquivo(s) da denylist tocados" "Revisão manual necessária"
      else
        log_ok "Denylist OK — nenhum arquivo proibido foi tocado."
        _audit_log_entry "$logfile" "denylist" "ok" "Nenhum arquivo da denylist tocado" ""
      fi
    fi
  fi

  hr

  # 4. Direção reversa — verifica candidatos a upstream (Simplicio → Turbo → Hermes)
  log "Verificando candidatos a direção reversa (Simplicio → Turbo → Upstream)..."
  local turbo_epoch simp_epoch
  for perf_file in "agent/_hermes_fast.py" "agent/_fastjson.py" "agent/context_compressor.py" "agent/async_dag/__init__.py" "agent/uvloop_utils.py"; do
    if [ -f "$SIMPLICIO_REPO/$perf_file" ]; then
      turbo_epoch="$(_git_file_epoch "$TURBO_REPO" "$perf_file")"
      simp_epoch="$(_git_file_epoch "$SIMPLICIO_REPO" "$perf_file")"
      if [ "${simp_epoch:-0}" -gt "${turbo_epoch:-0}" ]; then
        log_ok "  $perf_file — Simplicio mais novo que Turbo (candidato a upstream reverso)"
        _audit_log_entry "$logfile" "reverse-upstream" "candidato" "$perf_file — Simplicio mais recente" "Pode ser upstreamado para Turbo"
      fi
    fi
  done

  _audit_log_footer "$logfile" "COMPLETO"

  log_ok "Estágio 2 concluído. Log de auditoria: $logfile"
  log_review "Revise as alterações e faça commit com preservação de autoria (AUTHOR_MAP)."
}

# --------------------------------------------------------------------------
# Estágio 3 — integração do ecossistema (operators)
# --------------------------------------------------------------------------
cmd_ecosystem() {
  log_section "Estágio 3 — Integração do Ecossistema (Operators)"

  _ensure_ecosystem_sync

  local logfile
  logfile="$(_audit_log_path "ecosystem-integration")"

  mode_banner
  hr

  # Repositórios do ecossistema
  local default_repos=(
    "$(dirname "$SIMPLICIO_REPO")/simplicio-runtime"
    "$(dirname "$SIMPLICIO_REPO")/simplicio-mapper"
    "$(dirname "$SIMPLICIO_REPO")/simplicio-dev-cli"
    "$(dirname "$SIMPLICIO_REPO")/simplicio-loop"
    "$(dirname "$SIMPLICIO_REPO")/simplicio-prompt"
  )
  local repos_raw="${ECOSYSTEM_REPOS:-}"
  if [ -z "$repos_raw" ]; then
    repos_raw="${default_repos[*]}"
    log "Usando repositórios padrão do ecossistema"
  fi

  _audit_log_header "$logfile" "Integração do Ecossistema" \
    "Múltiplos operadores" "$SIMPLICIO_REPO"

  # 1. Verifica cada operador do ecossistema
  log "Verificando operadores do ecossistema..."
  echo ""
  printf "  %-35s %-15s %-15s %s\n" "Operador" "Status" "Branch" "Schema"
  printf "  %-35s %-15s %-15s %s\n" "--------" "------" "------" "------"

  local operator_count=0 ok_count=0 missing_count=0

  for repo in $repos_raw; do
    operator_count=$((operator_count + 1))
    local name status branch schema_status
    name="$(basename "$repo")"

    if [ ! -d "$repo/.git" ]; then
      status="AUSENTE"
      missing_count=$((missing_count + 1))
      printf "  %b%-35s %b%-15s%b\n" "$_c_err" "$name" "$_c_err" "$status" "$_c_reset"
      _audit_log_entry "$logfile" "operator" "ausente" "$name" "Repositório não encontrado: $repo"
      continue
    fi

    branch="$(git -C "$repo" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")"

    # Verifica se há schema simplicio.*/v1 no repo
    if [ -d "$repo/schemas" ] || [ -f "$repo/simplicio.io-v1.json" ] || grep -rq "simplicio\\.io/v1" "$repo" --include="*.json" --include="*.md" 2>/dev/null; then
      schema_status="OK"
    else
      schema_status="N/A"
    fi

    status="OK"
    ok_count=$((ok_count + 1))
    printf "  %b%-35s %b%-15s%b %-15s %s\n" "$_c_ok" "$name" "$_c_ok" "$status" "$_c_reset" "$branch" "$schema_status"
    _audit_log_entry "$logfile" "operator" "ok" "$name" "branch=$branch, schema=$schema_status"
  done

  hr

  # 2. Executa ecosystem-sync.sh ecosystem-update
  log "Sincronizando repositórios do ecossistema..."
  echo ""
  local sync_args=()
  [ "$APPLY" -eq 1 ] && sync_args+=("--apply") || sync_args+=("--dry-run")

  if [ -n "$repos_raw" ]; then
    ECOSYSTEM_REPOS="$repos_raw" \
      bash "$ECOSYSTEM_SYNC" ecosystem-update "${sync_args[@]}"
  fi

  hr

  # 3. Verifica compatibilidade de contrato (schemas simplicio.*/v1)
  log "Verificando compatibilidade de contrato (schemas simplicio.*/v1)..."
  echo ""

  local expected_schemas=(
    "simplicio.task.v1"
    "simplicio.runtime-resource-map.v1"
    "simplicio.io.v1"
  )

  local runtime_repo
  runtime_repo="$(dirname "$SIMPLICIO_REPO")/simplicio-runtime"
  if [ -d "$runtime_repo" ]; then
    log "Runtime encontrado: $runtime_repo"
    for schema in "${expected_schemas[@]}"; do
      if grep -rq "$schema" "$runtime_repo" --include="*.rs" --include="*.json" --include="*.md" 2>/dev/null; then
        log_ok "  Schema $schema — OK"
        _audit_log_entry "$logfile" "schema" "ok" "$schema" "Encontrado no runtime"
      else
        log_warn "  Schema $schema — NÃO ENCONTRADO no runtime"
        _audit_log_entry "$logfile" "schema" "ausente" "$schema" "Não encontrado no runtime"
      fi
    done
  else
    log_warn "Runtime não encontrado: $runtime_repo (pulei verificação de schemas)"
  fi

  hr

  log "Resumo da integração do ecossistema:"
  log_ok "  Operadores OK:       $ok_count/$operator_count"
  [ "$missing_count" -gt 0 ] && log_warn "  Operadores ausentes: $missing_count"

  _audit_log_footer "$logfile" "COMPLETO — $ok_count/$operator_count operadores OK, $missing_count ausentes"

  log_ok "Estágio 3 concluído. Log de auditoria: $logfile"
}

# --------------------------------------------------------------------------
# Audit — exibir histórico de imports
# --------------------------------------------------------------------------
cmd_audit() {
  log_section "Histórico de Imports"

  if [ ! -d "$HERMES_IMPORT_DIR" ]; then
    log_warn "Nenhum log de import encontrado em $HERMES_IMPORT_DIR"
    log "Crie o diretório com: mkdir -p $HERMES_IMPORT_DIR"
    return 0
  fi

  local logs
  # shellcheck disable=SC2206
  logs=("$HERMES_IMPORT_DIR"/*.md)
  if [ ! -e "${logs[0]}" ]; then
    log_warn "Nenhum log de import encontrado em $HERMES_IMPORT_DIR"
    return 0
  fi

  log "Logs de import em $HERMES_IMPORT_DIR:"
  echo ""

  local logfile
  for logfile in "${logs[@]}"; do
    local name size date
    name="$(basename "$logfile")"
    size="$(wc -l < "$logfile" | tr -d ' ')"
    date="$(date -r "$logfile" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "?")"

    local title
    title="$(head -3 "$logfile" | grep "^#" | head -1 | sed 's/^# //' || echo "$name")"

    printf "  %b•%b %-35s %b[%s]%b %s (%s linhas)\n" \
      "$_c_info" "$_c_reset" "$name" \
      "$_c_skip" "$date" "$_c_reset" \
      "$title" "$size"
  done

  echo ""
  log "Total: ${#logs[@]} log(s) de import"
}

# --------------------------------------------------------------------------
# Gate — verificar dívida de sync (issues-espelho abertas > N dias)
# --------------------------------------------------------------------------
cmd_gate() {
  log_section "Gate de Dívida de Sync"

  local threshold_days="${1:-30}"

  log "Verificando dívida de sync (issues-espelho abertas há > $threshold_days dias)..."
  echo ""

  # Verifica se gh CLI está disponível
  if command -v gh &>/dev/null; then
    log "GitHub CLI disponível — consultando issues abertas..."
    local open_issues
    open_issues="$(gh issue list --repo wesleysimplicio/simplicio-agent --state open --json number,title,createdAt,labels --limit 50 2>/dev/null || true)"

    if [ -n "$open_issues" ] && [ "$open_issues" != "[]" ]; then
      echo "$open_issues" | python3 -c "
import json, sys
from datetime import datetime, timezone

try:
    issues = json.load(sys.stdin)
except json.JSONDecodeError:
    sys.exit(0)

now = datetime.now(timezone.utc)
threshold = ${threshold_days}
found = False

for issue in issues:
    created = datetime.fromisoformat(issue.get('createdAt', '')).replace(tzinfo=timezone.utc)
    days_open = (now - created).days
    labels = [l.get('name', '') for l in issue.get('labels', [])]
    is_import = any(k in l.lower() for k in ['import', 'mirror', 'sync'] for l in labels)

    if days_open > threshold:
        found = True
        flag = '🚩' if is_import else '  '
        print(f\"  {flag} #{issue['number']}: {issue['title']} ({days_open}d, labels: {', '.join(labels) if labels else 'none'})\")

if not found:
    print('  ✓ Nenhuma issue acima do threshold de ${threshold_days} dias.')
" 2>/dev/null || log_warn "Falha ao processar issues do GitHub"
    else
      log_ok "Nenhuma issue em aberto."
    fi
  else
    log_warn "GitHub CLI (gh) não disponível — não é possível verificar issues."
    log_review "Instale gh CLI para verificação automática da dívida de sync."
    log_review "Threshold: $threshold_days dias"
  fi

  echo ""

  # Verifica se há imports sem follow-up
  if [ -d "$HERMES_IMPORT_DIR" ]; then
    local logs_without_action=0
    local logfile
    for logfile in "$HERMES_IMPORT_DIR"/*.md; do
      [ ! -f "$logfile" ] && continue
      if grep -qi "candidato\|pendente\|revisar\|unknown" "$logfile" 2>/dev/null; then
        logs_without_action=$((logs_without_action + 1))
        printf "  ⚠ %s — contém itens pendentes não resolvidos\n" "$(basename "$logfile")"
      fi
    done
    if [ "$logs_without_action" -gt 0 ]; then
      log_warn "$logs_without_action log(s) de import com itens pendentes."
    else
      log_ok "Todos os logs de import estão resolvidos."
    fi
  fi
}

# --------------------------------------------------------------------------
# Status — resumo do pipeline
# --------------------------------------------------------------------------
cmd_status() {
  log_section "Status do Pipeline de Import"

  echo ""
  log "╔══════════════════════════════════════════════════════════════╗"
  log "║  Pipeline: Hermes Original → Hermes Turbo → Simplicio Agent ║"
  log "╚══════════════════════════════════════════════════════════════╝"
  echo ""

  # Estágio 1: upstream
  printf "  %bEstágio 1%b — Upstream → Turbo: " "$_c_bold" "$_c_reset"
  if [ -d "$TURBO_REPO/.git" ]; then
    local behind
    behind="$(git -C "$TURBO_REPO" rev-list --count "HEAD..upstream/main" 2>/dev/null || echo "?")"
    if [ "$behind" = "0" ]; then
      printf "%bATUALIZADO%b\n" "$_c_ok" "$_c_reset"
    elif [ "$behind" = "?" ]; then
      printf "%bSEM UPSTREAM%b (offline ou remote não configurado)\n" "$_c_skip" "$_c_reset"
    else
      printf "%b%d commit(s) atrás%b\n" "$_c_warn" "$behind" "$_c_reset"
    fi
  else
    printf "%bTurbo repo não encontrado%b (%s)\n" "$_c_err" "$_c_reset" "$TURBO_REPO"
  fi

  # Estágio 2: turbo → simplicio
  printf "  %bEstágio 2%b — Turbo → Simplicio: " "$_c_bold" "$_c_reset"
  local perf_files=("agent/_hermes_fast.py" "agent/_fastjson.py" "agent/uvloop_utils.py" "agent/simplicio_prompt.py")
  local perf_count=0
  for f in "${perf_files[@]}"; do
    [ -f "$SIMPLICIO_REPO/$f" ] && perf_count=$((perf_count + 1))
  done
  printf "%b%d/%d módulos perf importados%b\n" "$_c_ok" "$perf_count" "${#perf_files[@]}" "$_c_reset"

  # Estágio 3: ecossistema
  printf "  %bEstágio 3%b — Ecossistema: " "$_c_bold" "$_c_reset"
  local ecosystem_dirs=(
    "$(dirname "$SIMPLICIO_REPO")/simplicio-runtime"
    "$(dirname "$SIMPLICIO_REPO")/simplicio-mapper"
    "$(dirname "$SIMPLICIO_REPO")/simplicio-dev-cli"
    "$(dirname "$SIMPLICIO_REPO")/simplicio-loop"
  )
  local present=0 total=0
  for d in "${ecosystem_dirs[@]}"; do
    total=$((total + 1))
    [ -d "$d" ] && present=$((present + 1))
  done
  printf "%b%d/%d operadores presentes%b\n" "$_c_ok" "$present" "$total" "$_c_reset"

  echo ""

  # Logs de import
  printf "  %bLogs de import:%b " "$_c_bold" "$_c_reset"
  if [ -d "$HERMES_IMPORT_DIR" ]; then
    local log_count
    log_count="$(find "$HERMES_IMPORT_DIR" -name "*.md" -not -name "README.md" 2>/dev/null | wc -l | tr -d ' ')"
    printf "%b%d log(s) em %s%b\n" "$_c_ok" "$log_count" "$HERMES_IMPORT_DIR" "$_c_reset"
  else
    printf "%bNenhum log%b\n" "$_c_skip" "$_c_reset"
  fi

  # Denylist
  printf "  %bDenylist:%b " "$_c_bold" "$_c_reset"
  local denylist_present=0
  for denied in "${DENYLIST[@]}"; do
    [ -d "$SIMPLICIO_REPO/$denied" ] && denylist_present=$((denylist_present + 1))
  done
  if [ "$denylist_present" -eq 0 ]; then
    printf "%bNenhuma violação%b (política #56 respeitada)\n" "$_c_ok" "$_c_reset"
  else
    printf "%b%d diretório(s) proibido(s) presente(s)%b\n" "$_c_err" "$denylist_present" "$_c_reset"
  fi

  echo ""
  hr
  echo ""

  log "Ferramentas disponíveis:"
  if [ -f "$ECOSYSTEM_SYNC" ]; then
    log_ok "  ecosystem-sync.sh ($(wc -l < "$ECOSYSTEM_SYNC") linhas)"
  else
    log_warn "  ecosystem-sync.sh — AUSENTE"
  fi
  log_ok "  import.sh (este script, $(wc -l < "$SCRIPT_DIR/import.sh") linhas)"
  log_ok "  docs/hermes-import/ ($(find "$HERMES_IMPORT_DIR" -name "*.md" 2>/dev/null | wc -l | tr -d ' ') documento(s))"
  echo ""

  log "Próximos passos sugeridos:"
  log "  • scripts/importer/import.sh upstream --version <tag>  — analisar nova release do Hermes"
  log "  • scripts/importer/import.sh turbo --apply            — importar deltas do Turbo"
  log "  • scripts/importer/import.sh ecosystem --apply        — integrar operadores"
  log "  • scripts/importer/import.sh gate                     — verificar dívida de sync"
}

# --------------------------------------------------------------------------
# Help
# --------------------------------------------------------------------------
usage() {
  cat <<EOF
import.sh — Mecanismo executável do pipeline Hermes Original → Hermes Turbo → Simplicio Agent

Uso:
  scripts/importer/import.sh <subcomando> [--dry-run|--apply] [opções]

Subcomandos (Estágios do Pipeline):
  upstream    Estágio 1 — Delta-review de release upstream (Hermes Original) → Turbo
              Necessário: --version <tag> (ex: --version v0.19.0)
              Analisa diff, classifica deltas (perf/feature/denylist), gera log auditável.

  turbo       Estágio 2 — Import Turbo → Simplicio
              Executa o pull do delta de performance via ecosystem-sync.sh,
              verifica denylist (#56), identifica candidatos a upstream reverso.

  ecosystem   Estágio 3 — Integração dos operators do ecossistema
              Verifica operadores (runtime, mapper, dev-cli, loop, prompt),
              sincroniza repos, valida schemas simplicio.*/v1.

Transversais:
  audit       Exibir histórico de todos os imports registrados (docs/hermes-import/)
  gate        Verificar dívida de sync — issues-espelho abertas > threshold (padrão: 30 dias)
  status      Resumo completo do pipeline: o que foi importado e o que está pendente

Flags:
  --dry-run       (padrão) apenas simular, nunca escrever ou alterar
  --apply         efetuar mudanças destrutivas
  --version <tag> especificar versão/tag para import upstream
  --verbose       saída detalhada
  -h, --help      exibir esta ajuda

Ambiente:
  SIMPLICIO_REPO   Path do repositório simplicio-agent (auto-detectado)
  TURBO_REPO       Path do repositório hermes-turbo-agent (default: ~/Projetos/ai/hermes-turbo-agent)
  HERMES_UPSTREAM  URL do upstream Hermes (default: https://github.com/NousResearch/hermes-agent.git)
  ECOSYSTEM_REPOS  Lista de paths de repos do ecossistema para import ecosystem

Exemplos:
  scripts/importer/import.sh upstream --version v0.19.0
  scripts/importer/import.sh turbo --apply
  scripts/importer/import.sh ecosystem
  scripts/importer/import.sh status
  scripts/importer/import.sh gate

Referências:
  Issue #66   — esta issue (criação do importador)
  Issue #19   — F1 inventário (política de import)
  Issue #62   — governança do pipeline
  Issue #56   — denylist CLI-only
  docs/hermes-import/ — logs de auditoria de import
  scripts/sync/ecosystem-sync.sh — orquestrador de sync subjacente
  docs/SYNC_PIPELINE.md — documentação do pipeline de sync
EOF
}

# --------------------------------------------------------------------------
# Dispatch principal
# --------------------------------------------------------------------------
main() {
  local sub="${1:-}"
  [ -n "$sub" ] || { usage; exit 2; }
  shift || true

  case "$sub" in
    -h|--help|help)   usage ;;
    upstream)         parse_common_flags "$@"; cmd_upstream ;;
    turbo)            parse_common_flags "$@"; cmd_turbo ;;
    ecosystem)        parse_common_flags "$@"; cmd_ecosystem ;;
    audit)            cmd_audit "$@" ;;
    gate)             cmd_gate "$@" ;;
    status)           cmd_status ;;
    *)                log_err "Subcomando desconhecido: $sub"; usage; exit 2 ;;
  esac
}

main "$@"
