#!/usr/bin/env bash
# Run the Hermes Turbo performance integration manifest (issue #220).
#
# Proves PRESENT -> SAME_SOURCE -> BUILT -> INSTALLED -> IMPORTABLE -> CALLED ->
# E2E_PROVEN -> DEFAULT_ON -> BENCHMARKED -> REGRESSION_GATED for each axis.
# Exits non-zero on the first axis that does not hold, so CI / local
# validation cannot silently regress a perf axis.
#
# Requires the package to be installed with the [fast] extra
# (orjson + msgspec + uvloop), which is the shipped production stack.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"

cd "$REPO_ROOT"
exec python3 "$HERE/perf_integration_manifest.py" --repo "$REPO_ROOT" --check "$@"
