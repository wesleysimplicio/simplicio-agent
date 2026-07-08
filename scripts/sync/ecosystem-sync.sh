#!/usr/bin/env bash
#
# ecosystem-sync.sh — repeatable "ecosystem sync pipeline" orchestrator.
#
# Pipeline (upstream -> downstream):
#
#   Hermes Agent            github.com/NousResearch/hermes-agent   (upstream, canonical)
#     └─> Hermes Turbo Agent  $TURBO_REPO                          (absorbs Hermes, adds perf layer)
#           └─> Simplicio       $SIMPLICIO_REPO (this repo)         (pulls Turbo's PERF DELTA additively)
#
# CRITICAL ORDERING CONSTRAINT
# ----------------------------
# Simplicio is currently NEWER than Turbo (Simplicio v0.18.0 on a recent Hermes
# base; Turbo on an older base). A blind "copy everything from Turbo" would
# REVERT newer Simplicio code. Therefore this tool enforces:
#
#   (a) Turbo must absorb the latest Hermes FIRST (`turbo-absorb-hermes`), and
#       only THEN
#   (b) Simplicio pulls from Turbo — and even then it pulls the PERF DELTA
#       ADDITIVELY, per-file, SKIPPING any file that is newer in Simplicio
#       (`simplicio-pull-perf`). It never wholesale-overwrites newer files.
#
# Every destructive step is guarded behind --apply. Default is --dry-run.
#
# Usage:
#   scripts/sync/ecosystem-sync.sh <subcommand> [--dry-run|--apply] [options]
#
# Subcommands:
#   turbo-absorb-hermes    Fetch NousResearch/hermes-agent upstream into the
#                          Turbo repo, report the merge diff, stop for human
#                          review. --apply performs a non-destructive merge.
#   simplicio-pull-perf    Copy the ADDITIVE perf module set from Turbo into
#                          Simplicio, skipping any file newer in Simplicio, then
#                          run the validation gate.
#   ecosystem-update       Pull relevant updates from other Projetos/ai repos
#                          (parameterizable via ECOSYSTEM_REPOS).
#   asolaria-absorb        Read docs/ASOLARIA_ABSORPTION_PLAN.md and list pending
#                          items with their license class. `--apply --complete
#                          <id>` checks off one item's box after a human has
#                          done the (re)implementation work — it NEVER copies
#                          source files itself: most Asolaria originals carry
#                          no license (all-rights-reserved), so this tool
#                          refuses to automate vendoring. See the
#                          `reimplement-only` vs `mit-safe` gate below.
#   validate               Run the validation gate: python import smoke of the
#                          perf modules + targeted pytest on the ported suites.
#
# Environment (all optional, absolute paths):
#   SIMPLICIO_REPO   this repo root         (default: git toplevel of this script)
#   TURBO_REPO       hermes-turbo-agent     (default: <parent>/hermes-turbo-agent)
#   HERMES_UPSTREAM  upstream git URL       (default: https://github.com/NousResearch/hermes-agent.git)
#   HERMES_UPSTREAM_REMOTE  remote name in Turbo (default: upstream)
#   HERMES_UPSTREAM_BRANCH  upstream branch      (default: main)
#   ECOSYSTEM_REPOS  space/comma list of repo paths for ecosystem-update
#   PYTHON           python interpreter     (default: python3)
#
set -euo pipefail

# --------------------------------------------------------------------------
# Resolve paths
# --------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

_git_toplevel() {
  git -C "$1" rev-parse --show-toplevel 2>/dev/null || true
}

SIMPLICIO_REPO="${SIMPLICIO_REPO:-$(_git_toplevel "$SCRIPT_DIR")}"
if [ -z "${SIMPLICIO_REPO:-}" ]; then
  # Fallback: two levels up from scripts/sync
  SIMPLICIO_REPO="$(cd "$SCRIPT_DIR/../.." && pwd)"
fi

# Turbo repo defaults to a sibling of Simplicio's ecosystem root. We try the
# real Projetos/ai layout first, then a sibling of SIMPLICIO_REPO.
_default_turbo() {
  local candidates=(
    "$(dirname "$SIMPLICIO_REPO")/hermes-turbo-agent"
    "$HOME/Projetos/ai/hermes-turbo-agent"
  )
  local c
  for c in "${candidates[@]}"; do
    if [ -d "$c" ]; then printf '%s\n' "$c"; return 0; fi
  done
  # No existing dir found; return the first candidate as the nominal default.
  printf '%s\n' "${candidates[0]}"
}

TURBO_REPO="${TURBO_REPO:-$(_default_turbo)}"
HERMES_UPSTREAM="${HERMES_UPSTREAM:-https://github.com/NousResearch/hermes-agent.git}"
HERMES_UPSTREAM_REMOTE="${HERMES_UPSTREAM_REMOTE:-upstream}"
HERMES_UPSTREAM_BRANCH="${HERMES_UPSTREAM_BRANCH:-main}"
PYTHON="${PYTHON:-python3}"

# --------------------------------------------------------------------------
# The ADDITIVE perf module set (canonical copy list).
# Documented in CHANGELOG.md [0.18.0]. Paths are relative to a repo root.
# --------------------------------------------------------------------------
PERF_PATHS=(
  "agent/serde"
  "agent/tokens"
  "agent/tracing"
  "agent/net"
  "agent/async_dag"
  "agent/router"
  "agent/telemetry"
  "agent/providers"
  "agent/project_mapper"
  "agent/_fastjson.py"
  "agent/_hermes_fast.py"
  "agent/uvloop_utils.py"
  "agent/simplicio_prompt.py"
  "rust_ext"
  "plugins/token_saver"
)

# Perf modules imported by the validation smoke test.
PERF_IMPORT_MODULES=(
  "agent._fastjson"
  "agent._hermes_fast"
  "agent.uvloop_utils"
  "agent.simplicio_prompt"
  "agent.serde"
  "agent.tokens"
  "agent.tracing"
  "agent.net"
  "agent.async_dag"
  "agent.router"
  "agent.telemetry"
  "agent.providers"
  "agent.project_mapper"
)

# Targeted pytest suites for the ported perf code. Only those that exist are run.
PERF_TEST_PATHS=(
  "tests/agent/serde"
  "tests/agent/tokens"
  "tests/agent/tracing"
  "tests/agent/net"
  "tests/agent/async_dag"
  "tests/agent/telemetry"
  "tests/agent/providers"
  "tests/agent/project_mapper"
  "tests/agent/test_fastjson.py"
  "tests/agent/test_hermes_fast.py"
  "tests/agent/test_uvloop_utils.py"
  "tests/router"
  "tests/plugins/test_token_saver_plugin.py"
)

# --------------------------------------------------------------------------
# Logging helpers
# --------------------------------------------------------------------------
_c_reset=""; _c_info=""; _c_warn=""; _c_err=""; _c_ok=""; _c_skip=""
if [ -t 1 ]; then
  _c_reset="\033[0m"; _c_info="\033[36m"; _c_warn="\033[33m"
  _c_err="\033[31m"; _c_ok="\033[32m"; _c_skip="\033[35m"
fi
log()       { printf "%b[sync]%b %s\n"        "$_c_info" "$_c_reset" "$*"; }
log_ok()    { printf "%b[ ok ]%b %s\n"        "$_c_ok"   "$_c_reset" "$*"; }
log_warn()  { printf "%b[warn]%b %s\n"        "$_c_warn" "$_c_reset" "$*" >&2; }
log_err()   { printf "%b[FAIL]%b %s\n"        "$_c_err"  "$_c_reset" "$*" >&2; }
log_skip()  { printf "%b[skip]%b %s\n"        "$_c_skip" "$_c_reset" "$*"; }
log_review(){ printf "%b[HUMAN]%b %s\n"       "$_c_warn" "$_c_reset" "$*"; }
hr()        { printf -- "----------------------------------------------------------------------\n"; }

die() { log_err "$*"; exit 1; }

# --------------------------------------------------------------------------
# Global flags
# --------------------------------------------------------------------------
APPLY=0

parse_common_flags() {
  local rest=()
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --apply)    APPLY=1 ;;
      --dry-run)  APPLY=0 ;;
      *)          rest+=("$1") ;;
    esac
    shift
  done
  # Re-export remaining args for the subcommand.
  REMAINING_ARGS=("${rest[@]:-}")
}

mode_banner() {
  if [ "$APPLY" -eq 1 ]; then
    log_warn "MODE: --apply (destructive steps ENABLED)"
  else
    log "MODE: --dry-run (no changes will be written; use --apply to enact)"
  fi
}

# --------------------------------------------------------------------------
# Subcommand: turbo-absorb-hermes
# --------------------------------------------------------------------------
cmd_turbo_absorb_hermes() {
  hr; log "SUBCOMMAND: turbo-absorb-hermes"
  log "Turbo repo:      $TURBO_REPO"
  log "Hermes upstream: $HERMES_UPSTREAM ($HERMES_UPSTREAM_REMOTE/$HERMES_UPSTREAM_BRANCH)"
  hr

  [ -d "$TURBO_REPO/.git" ] || die "Turbo repo not a git checkout: $TURBO_REPO (set TURBO_REPO)"

  # Ensure the upstream remote exists and points at NousResearch/hermes-agent.
  local existing
  existing="$(git -C "$TURBO_REPO" remote get-url "$HERMES_UPSTREAM_REMOTE" 2>/dev/null || true)"
  if [ -z "$existing" ]; then
    if [ "$APPLY" -eq 1 ]; then
      log "Adding remote '$HERMES_UPSTREAM_REMOTE' -> $HERMES_UPSTREAM"
      git -C "$TURBO_REPO" remote add "$HERMES_UPSTREAM_REMOTE" "$HERMES_UPSTREAM"
    else
      log_skip "Remote '$HERMES_UPSTREAM_REMOTE' missing; would add -> $HERMES_UPSTREAM (--apply)"
    fi
  else
    log "Remote '$HERMES_UPSTREAM_REMOTE' -> $existing"
  fi

  log "Fetching $HERMES_UPSTREAM_REMOTE ..."
  if ! git -C "$TURBO_REPO" fetch --tags "$HERMES_UPSTREAM_REMOTE" 2>/dev/null; then
    log_warn "Fetch from '$HERMES_UPSTREAM_REMOTE' failed (offline or no remote). Continuing with local refs."
  fi

  local upstream_ref="$HERMES_UPSTREAM_REMOTE/$HERMES_UPSTREAM_BRANCH"
  if ! git -C "$TURBO_REPO" rev-parse --verify --quiet "$upstream_ref" >/dev/null; then
    log_warn "Upstream ref '$upstream_ref' not available locally; cannot compute diff summary."
    log_review "Configure the upstream remote/branch and re-run before Turbo can absorb Hermes."
    return 0
  fi

  local head_ref ahead behind
  head_ref="$(git -C "$TURBO_REPO" rev-parse --abbrev-ref HEAD)"
  ahead="$(git -C "$TURBO_REPO" rev-list --count "$upstream_ref..HEAD" 2>/dev/null || echo '?')"
  behind="$(git -C "$TURBO_REPO" rev-list --count "HEAD..$upstream_ref" 2>/dev/null || echo '?')"

  log "Turbo HEAD: $head_ref  (ahead $ahead / behind $behind vs $upstream_ref)"
  hr; log "Diff summary (upstream changes Turbo is missing):"
  git -C "$TURBO_REPO" --no-pager diff --stat "HEAD..$upstream_ref" 2>/dev/null | tail -n 40 || true
  hr

  if [ "$behind" = "0" ]; then
    log_ok "Turbo is up to date with upstream Hermes. Nothing to absorb."
    return 0
  fi

  if [ "$APPLY" -eq 1 ]; then
    log_warn "Performing NON-DESTRUCTIVE merge of $upstream_ref into $head_ref ..."
    if git -C "$TURBO_REPO" merge --no-ff --no-commit "$upstream_ref"; then
      log_ok "Merge staged cleanly. Review 'git -C $TURBO_REPO status' then commit."
      log_review "Merge is staged but NOT committed. A human must review + commit + push Turbo."
    else
      log_warn "Merge produced conflicts (left in the working tree, NOT committed)."
      log_review "Resolve conflicts in $TURBO_REPO, then commit. Aborting further automation."
      return 1
    fi
  else
    log_review "Turbo is BEHIND upstream Hermes by $behind commit(s)."
    log_review "Re-run with --apply to stage a non-destructive merge for human review."
    log_review "ORDERING GUARD: do NOT run 'simplicio-pull-perf' until Turbo has absorbed Hermes."
  fi
}

# --------------------------------------------------------------------------
# Subcommand: simplicio-pull-perf  (additive, newer-file-safe)
# --------------------------------------------------------------------------
# File-level newer check: a Turbo file is copied only when the Simplicio target
# is missing OR the Turbo file is strictly newer (by git commit time when both
# are tracked, else by mtime). Never overwrites a newer Simplicio file.
_git_commit_epoch() {
  # $1 repo, $2 path — last commit epoch for a tracked path, empty if untracked.
  git -C "$1" log -1 --format=%ct -- "$2" 2>/dev/null || true
}

_file_epoch() {
  # $1 abs path — prefer git commit time, fall back to mtime.
  local repo="$1" rel="$2" abs="$3" e
  e="$(_git_commit_epoch "$repo" "$rel")"
  if [ -n "$e" ]; then printf '%s\n' "$e"; return; fi
  if [ -e "$abs" ]; then
    # Portable mtime (BSD stat then GNU stat).
    stat -f %m "$abs" 2>/dev/null || stat -c %Y "$abs" 2>/dev/null || echo 0
  else
    echo 0
  fi
}

COPIED=0; SKIPPED_NEWER=0; SKIPPED_SAME=0; MISSING_SRC=0; WOULD_COPY=0

_sync_one_file() {
  # $1 rel path (file). Copies from TURBO_REPO to SIMPLICIO_REPO if additive-safe.
  local rel="$1"
  local src="$TURBO_REPO/$rel" dst="$SIMPLICIO_REPO/$rel"

  if [ ! -e "$src" ]; then
    log_skip "no such file in Turbo: $rel"
    MISSING_SRC=$((MISSING_SRC+1))
    return
  fi

  if [ ! -e "$dst" ]; then
    if [ "$APPLY" -eq 1 ]; then
      mkdir -p "$(dirname "$dst")"; cp -p "$src" "$dst"
      log_ok "copied (new): $rel"; COPIED=$((COPIED+1))
    else
      log "would copy (new): $rel"; WOULD_COPY=$((WOULD_COPY+1))
    fi
    return
  fi

  # Both exist: compare content first.
  if cmp -s "$src" "$dst"; then
    log_skip "identical, skip: $rel"; SKIPPED_SAME=$((SKIPPED_SAME+1)); return
  fi

  local src_epoch dst_epoch
  src_epoch="$(_file_epoch "$TURBO_REPO" "$rel" "$src")"
  dst_epoch="$(_file_epoch "$SIMPLICIO_REPO" "$rel" "$dst")"

  if [ "${dst_epoch:-0}" -ge "${src_epoch:-0}" ]; then
    log_skip "SKIPPED-because-newer-in-Simplicio: $rel (simplicio=$dst_epoch >= turbo=$src_epoch)"
    SKIPPED_NEWER=$((SKIPPED_NEWER+1))
    log_review "differs but Simplicio is newer/equal -> NOT overwritten: $rel"
    return
  fi

  # Turbo is strictly newer -> additive update allowed.
  if [ "$APPLY" -eq 1 ]; then
    cp -p "$src" "$dst"
    log_ok "updated (turbo newer): $rel"; COPIED=$((COPIED+1))
  else
    log "would update (turbo newer): $rel (turbo=$src_epoch > simplicio=$dst_epoch)"
    WOULD_COPY=$((WOULD_COPY+1))
  fi
}

_sync_path() {
  # $1 rel path (file or dir).
  local rel="$1"
  local src="$TURBO_REPO/$rel"
  if [ -d "$src" ]; then
    # Walk files under the dir.
    local f relf
    while IFS= read -r f; do
      relf="${f#"$TURBO_REPO"/}"
      _sync_one_file "$relf"
    done < <(find "$src" -type f ! -name '*.pyc' ! -path '*/__pycache__/*' 2>/dev/null)
  else
    _sync_one_file "$rel"
  fi
}

cmd_simplicio_pull_perf() {
  hr; log "SUBCOMMAND: simplicio-pull-perf (additive perf delta, newer-file-safe)"
  log "Turbo (source):     $TURBO_REPO"
  log "Simplicio (target): $SIMPLICIO_REPO"
  hr

  [ -d "$TURBO_REPO" ] || die "Turbo repo not found: $TURBO_REPO (set TURBO_REPO)"
  [ -d "$SIMPLICIO_REPO" ] || die "Simplicio repo not found: $SIMPLICIO_REPO"

  # ORDERING GUARD: warn (dry-run) / block (apply) if Turbo is behind upstream.
  _ordering_guard || {
    if [ "$APPLY" -eq 1 ]; then
      die "Ordering guard tripped: Turbo has NOT absorbed the latest Hermes. Run 'turbo-absorb-simplicio-agent --apply' first."
    fi
  }

  local rel
  for rel in "${PERF_PATHS[@]}"; do
    _sync_path "$rel"
  done

  hr
  log "Copy summary:"
  log_ok    "  copied/updated:            $COPIED"
  log        "  would-copy (dry-run):      $WOULD_COPY"
  log_skip  "  skipped (newer/equal):     $SKIPPED_NEWER"
  log_skip  "  skipped (identical):       $SKIPPED_SAME"
  [ "$MISSING_SRC" -gt 0 ] && log_warn "  missing in Turbo:          $MISSING_SRC"
  hr

  # Run the validation gate after any copy attempt.
  cmd_validate
}

# Ordering guard: returns 0 if Turbo is at/ahead of upstream (safe to pull),
# non-zero if Turbo is behind (must absorb Hermes first). Non-fatal on offline.
_ordering_guard() {
  if [ ! -d "$TURBO_REPO/.git" ]; then
    log_warn "Cannot verify ordering: Turbo is not a git checkout. Proceeding with caution."
    return 0
  fi
  local upstream_ref="$HERMES_UPSTREAM_REMOTE/$HERMES_UPSTREAM_BRANCH"
  git -C "$TURBO_REPO" fetch "$HERMES_UPSTREAM_REMOTE" >/dev/null 2>&1 || true
  if ! git -C "$TURBO_REPO" rev-parse --verify --quiet "$upstream_ref" >/dev/null; then
    log_warn "Ordering guard: upstream ref '$upstream_ref' unknown (offline?). Cannot confirm Turbo absorbed Hermes."
    return 0
  fi
  local behind
  behind="$(git -C "$TURBO_REPO" rev-list --count "HEAD..$upstream_ref" 2>/dev/null || echo 0)"
  if [ "${behind:-0}" -gt 0 ]; then
    log_warn "Ordering guard: Turbo is BEHIND upstream Hermes by $behind commit(s)."
    log_review "Turbo must absorb Hermes FIRST. Run: $0 turbo-absorb-simplicio-agent --apply"
    return 1
  fi
  log_ok "Ordering guard: Turbo is at/ahead of upstream Hermes. Safe to pull perf delta."
  return 0
}

# --------------------------------------------------------------------------
# Subcommand: ecosystem-update
# --------------------------------------------------------------------------
cmd_ecosystem_update() {
  hr; log "SUBCOMMAND: ecosystem-update"
  hr

  local repos_raw="${ECOSYSTEM_REPOS:-}"
  if [ -z "$repos_raw" ] && [ "${#REMAINING_ARGS[@]}" -gt 0 ]; then
    repos_raw="${REMAINING_ARGS[*]}"
  fi
  if [ -z "$repos_raw" ]; then
    # Sensible defaults from the Projetos/ai ecosystem.
    local root; root="$(dirname "$SIMPLICIO_REPO")"
    repos_raw="$root/simplicio-runtime $root/simplicio-mapper $root/simplicio-dev-cli $root/simplicio-loop"
    log "No ECOSYSTEM_REPOS set; using ecosystem defaults under $root"
  fi

  # Normalise commas to spaces.
  repos_raw="${repos_raw//,/ }"
  local r
  for r in $repos_raw; do
    if [ ! -d "$r/.git" ]; then
      log_skip "not a git checkout, skip: $r"
      continue
    fi
    local branch; branch="$(git -C "$r" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
    log "Repo: $r (branch $branch)"
    git -C "$r" fetch --all --tags >/dev/null 2>&1 || log_warn "  fetch failed for $r (offline?)"
    local behind; behind="$(git -C "$r" rev-list --count "HEAD..@{upstream}" 2>/dev/null || echo '?')"
    log "  behind upstream: $behind"
    if [ "$APPLY" -eq 1 ] && [ "$behind" != "?" ] && [ "${behind:-0}" -gt 0 ]; then
      log_warn "  pulling (fast-forward only) ..."
      if git -C "$r" pull --ff-only >/dev/null 2>&1; then
        log_ok "  updated $r"
      else
        log_review "  non-fast-forward for $r; human must reconcile."
      fi
    else
      [ "${behind:-0}" != "0" ] && log_review "  updates available for $r; re-run with --apply to fast-forward."
    fi
  done
}

# --------------------------------------------------------------------------
# Subcommand: asolaria-absorb
# --------------------------------------------------------------------------
# Canonical Asolaria absorption items (docs/ASOLARIA_ABSORPTION_PLAN.md,
# "Status tracking" section — this table and that section must stay in
# sync). Pipe-delimited: id|prio|license_class|title
#
#   license_class:
#     mit-safe          — source is MIT-licensed; vendoring with attribution
#                          is legally fine (still a human, reviewed step —
#                          this script never copies bytes on its own).
#     reimplement-only   — source carries NO LICENSE / NOASSERTION (or is
#                          copyleft-incompatible). All-rights-reserved by
#                          default: the *pattern* may be reimplemented from
#                          the public README/spec, the code must never be
#                          copy-pasted. `--complete` refuses these without
#                          an explicit --confirm-reimplemented.
# --------------------------------------------------------------------------
ASOLARIA_ITEMS=(
  "1|P0|reimplement-only|FEDENV single-parent dispatcher (omni-dispatcher / omnicoder)"
  "2|P0|reimplement-only|SkillOpt v2 rollout scoring (Harness-edit)"
  "3|P0|mit-safe|Cross-vendor memory handoff (ai-memory)"
  "4|P1|reimplement-only|200ns revolver PID emitter"
  "5|P1|reimplement-only|Real whiteroom scorer/store"
  "6|P1|reimplement-only|Depth-N gate conformance vectors"
  "7|P2|reimplement-only|Host-8 server-crate patterns (study only)"
  "8|P2|mit-safe|Critical-path DAG scheduler (scala-critical-path-planner)"
  "9|P2|reimplement-only|Doc-extraction flow (reference only)"
)

_asolaria_item_lookup() {
  # $1 id -> prints "prio|license_class|title" on stdout, returns 1 if unknown.
  local id="$1" entry eid eprio elicense etitle
  for entry in "${ASOLARIA_ITEMS[@]}"; do
    IFS='|' read -r eid eprio elicense etitle <<<"$entry"
    if [ "$eid" = "$id" ]; then
      printf '%s|%s|%s\n' "$eprio" "$elicense" "$etitle"
      return 0
    fi
  done
  return 1
}

_asolaria_complete_item() {
  # $1 plan path, $2 item id, $3 confirm_reimpl (0/1). Flips that item's
  # checkbox in the plan from "- [ ] N." to "- [x] N.". Never touches any
  # file outside SIMPLICIO_REPO and never copies source from anywhere.
  local plan="$1" id="$2" confirm_reimpl="$3"
  local info prio license title

  if ! info="$(_asolaria_item_lookup "$id")"; then
    die "Unknown Asolaria item id: $id (see docs/ASOLARIA_ABSORPTION_PLAN.md 'Status tracking')"
  fi
  IFS='|' read -r prio license title <<<"$info"
  log "Item #$id [$prio/$license]: $title"

  if grep -qE "^- \[[xX]\] ${id}\. " "$plan"; then
    log_ok "Item #$id is already marked complete."
    return 0
  fi
  if ! grep -qE "^- \[ \] ${id}\. " "$plan"; then
    die "No pending checkbox found for item #$id in $plan (unexpected format?)"
  fi

  if [ "$license" = "reimplement-only" ] && [ "$confirm_reimpl" -ne 1 ]; then
    log_err "License class is 'reimplement-only' (NO LICENSE / NOASSERTION source)."
    log_review "This item can only be completed after a human has reimplemented it from"
    log_review "the public spec/README — copy-pasting the source is not permitted."
    log_review "Re-run once that review has actually happened:"
    log_review "  $0 asolaria-absorb --apply --complete $id --confirm-reimplemented"
    return 1
  fi

  if [ "$APPLY" -ne 1 ]; then
    log "would mark item #$id complete (dry-run; re-run with --apply)"
    return 0
  fi

  local line_num
  line_num="$(grep -nE "^- \[ \] ${id}\. " "$plan" | head -1 | cut -d: -f1)"
  sed -i.bak "${line_num}s/^- \[ \] /- [x] /" "$plan"
  rm -f "${plan}.bak"
  log_ok "Marked item #$id complete in $plan"
  log_review "Commit docs/ASOLARIA_ABSORPTION_PLAN.md together with the actual absorption change it tracks (or in the same PR)."
  cmd_validate
}

cmd_asolaria_absorb() {
  hr; log "SUBCOMMAND: asolaria-absorb"
  hr
  local plan="$SIMPLICIO_REPO/docs/ASOLARIA_ABSORPTION_PLAN.md"
  if [ ! -f "$plan" ]; then
    log_warn "Plan not found: $plan"
    log_review "Produce docs/ASOLARIA_ABSORPTION_PLAN.md (Asolaria / JesseBrown1980 items) first."
    return 0
  fi

  # Parse --complete <id> / --confirm-reimplemented out of this subcommand's
  # own args (parse_common_flags already stripped --apply/--dry-run into the
  # global REMAINING_ARGS, same convention as cmd_ecosystem_update).
  local complete_id="" confirm_reimpl=0
  local _args=("${REMAINING_ARGS[@]:-}") a
  local i=0
  while [ "$i" -lt "${#_args[@]}" ]; do
    a="${_args[$i]}"
    case "$a" in
      --complete) i=$((i+1)); complete_id="${_args[$i]:-}" ;;
      --confirm-reimplemented) confirm_reimpl=1 ;;
    esac
    i=$((i+1))
  done

  if [ -n "$complete_id" ]; then
    _asolaria_complete_item "$plan" "$complete_id" "$confirm_reimpl"
    return $?
  fi

  log "Reading plan: $plan"
  hr
  local pending=0 done_count=0 line state id title info prio license
  while IFS= read -r line; do
    if [[ "$line" =~ ^-\ \[([xX\ ])\]\ ([0-9]+)\.\ (.*)$ ]]; then
      state="${BASH_REMATCH[1]}"
      id="${BASH_REMATCH[2]}"
      title="$(printf '%s' "${BASH_REMATCH[3]}" | sed -E 's/^P[0-9]+[[:space:]]*·[[:space:]]*//')"
      if info="$(_asolaria_item_lookup "$id")"; then
        IFS='|' read -r prio license _ <<<"$info"
      else
        prio="?"; license="unknown (not in ASOLARIA_ITEMS)"
      fi
      if [ "$state" = " " ]; then
        pending=$((pending+1))
        log "  PENDING  #$id [$prio/$license] $title"
      else
        done_count=$((done_count+1))
        log_ok "  DONE     #$id [$prio/$license] $title"
      fi
    fi
  done < "$plan"

  hr
  log "Status: $done_count absorbed, $pending pending"
  if [ "$pending" -gt 0 ]; then
    log_review "Mark an item complete with: $0 asolaria-absorb --apply --complete <id>"
    log_review "reimplement-only items additionally require --confirm-reimplemented (never auto-copied — see docs/ASOLARIA_ABSORPTION_PLAN.md)."
  fi
  hr
}

# --------------------------------------------------------------------------
# Subcommand: validate (the gate)
# --------------------------------------------------------------------------
cmd_validate() {
  hr; log "SUBCOMMAND: validate (perf import smoke + targeted pytest)"
  log "Repo: $SIMPLICIO_REPO"
  hr
  local rc=0

  # 1) Import smoke of the perf modules.
  log "1/2 python import smoke of perf modules ..."
  local mods="${PERF_IMPORT_MODULES[*]}"
  if ( cd "$SIMPLICIO_REPO" && "$PYTHON" - "$mods" <<'PY'
import importlib, sys
mods = sys.argv[1].split()
failed = []
for m in mods:
    try:
        importlib.import_module(m)
        print(f"  import ok: {m}")
    except Exception as e:  # noqa: BLE001
        failed.append((m, repr(e)))
        print(f"  IMPORT FAIL: {m}: {e!r}")
if failed:
    print(f"\n{len(failed)} import(s) failed")
    sys.exit(1)
print("\nall perf-module imports ok")
PY
  ); then
    log_ok "import smoke passed"
  else
    log_err "import smoke FAILED"
    rc=1
  fi

  # 2) Targeted pytest on the ported perf suites (only those that exist).
  log "2/2 targeted pytest on ported perf suites ..."
  local present=()
  local t
  for t in "${PERF_TEST_PATHS[@]}"; do
    [ -e "$SIMPLICIO_REPO/$t" ] && present+=("$t")
  done

  if [ "${#present[@]}" -eq 0 ]; then
    log_warn "No perf test suites found; skipping pytest step."
  elif ! ( cd "$SIMPLICIO_REPO" && "$PYTHON" -c 'import pytest' >/dev/null 2>&1 ); then
    log_warn "pytest not importable in this environment; skipping pytest step."
    log_review "Install dev deps (pip install -e '.[dev]') to run the perf test gate."
  else
    log "Running: pytest -q ${present[*]}"
    if ( cd "$SIMPLICIO_REPO" && "$PYTHON" -m pytest -q "${present[@]}" ); then
      log_ok "perf pytest suites passed"
    else
      log_err "perf pytest suites FAILED (regression)"
      rc=1
    fi
  fi

  hr
  if [ "$rc" -eq 0 ]; then
    log_ok "VALIDATE: PASS"
  else
    log_err "VALIDATE: FAIL"
  fi
  return "$rc"
}

# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------
usage() {
  cat <<EOF
ecosystem-sync.sh — Hermes -> Turbo -> Simplicio sync pipeline

Usage:
  $0 <subcommand> [--dry-run|--apply] [options]

Subcommands:
  turbo-absorb-hermes    Turbo fetches NousResearch/hermes-agent, reports the
                         merge diff, stops for human review (--apply stages a
                         non-destructive merge).
  simplicio-pull-perf    Copy the ADDITIVE perf module set from Turbo into
                         Simplicio, skipping any file newer in Simplicio, then
                         run the validation gate.
  ecosystem-update       Pull relevant updates from other Projetos/ai repos
                         (ECOSYSTEM_REPOS or positional paths).
  asolaria-absorb        List pending items from docs/ASOLARIA_ABSORPTION_PLAN.md
                         with their license class. `--apply --complete <id>`
                         [--confirm-reimplemented] checks off one item after a
                         human has done the (re)implementation — never copies
                         source files itself.
  validate               Perf import smoke + targeted pytest gate.

Flags:
  --dry-run   (default) report only; never write or merge.
  --apply     enact destructive steps (copy files / stage merge / fast-forward).

Env: SIMPLICIO_REPO, TURBO_REPO, HERMES_UPSTREAM, HERMES_UPSTREAM_REMOTE,
     HERMES_UPSTREAM_BRANCH, ECOSYSTEM_REPOS, PYTHON

Ordering constraint: Simplicio is NEWER than Turbo. Turbo must absorb Hermes
FIRST; then Simplicio pulls the perf DELTA additively (never wholesale).
EOF
}

main() {
  local sub="${1:-}"
  [ -n "$sub" ] || { usage; exit 2; }
  shift || true

  parse_common_flags "$@"
  set -- "${REMAINING_ARGS[@]:-}"

  case "$sub" in
    turbo-absorb-hermes)  mode_banner; cmd_turbo_absorb_hermes ;;
    simplicio-pull-perf)  mode_banner; cmd_simplicio_pull_perf ;;
    ecosystem-update)     mode_banner; cmd_ecosystem_update ;;
    asolaria-absorb)      mode_banner; cmd_asolaria_absorb ;;
    validate)             cmd_validate ;;
    -h|--help|help)       usage ;;
    *)                    log_err "unknown subcommand: $sub"; usage; exit 2 ;;
  esac
}

main "$@"
