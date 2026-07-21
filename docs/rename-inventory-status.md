# Rename inventory — issue #187

The repository now has two related, deterministic checks:

```text
python3 -m tools.rename_guard.scanner --root .
python3 -m tools.rename_guard.inventory --root . --check
```

The first command is the regression ratchet. It scans tracked text files and
fails when a token is neither explicitly allowlisted nor covered by the
versioned baseline. The second command builds the
`simplicio.rename-inventory/v1` records and fails when an occurrence lacks a
path-scoped classification, reason, owner or issue.

Each inventory record contains:

- `path`, `line` or archive `resource`, and the matched `token`;
- the source-line `context`, `context_class`, logical `surface`, and artifact
  (`source-tree`, `wheel` or `sdist`);
- `origin` (`source` or `generated`) and `source_of_generation` when the
  allowlist knows it;
- canonical `classification`, `reason`, `owner`, `issue` and `expiry`.

The top-level report includes counts by classification, surface and artifact,
plus the canonical SHA-256 of `tools/rename_guard/baseline.json`.

The allowlist remains compatibility-preserving: it uses path-scoped globs and
records why upstream credits, fixtures, private symbols, HERMES_* contracts,
and deprecated aliases remain. A global `*`/`**` exception, missing owner or
missing reason is rejected. Expired entries are rejected as well.

`tools/rename_guard/classify_baseline.py` and the versioned
`tools/rename_guard/baseline-classification.json` provide the separate
file-level review map for any occurrence still carrying the operational
`baseline` state. The map is intentionally not a rename instruction: public
debt remains owned by the appropriate follow-up surface issue, while legacy
state paths are `MIGRATE_STATE` and generated outputs are `GENERATED_REBUILD`.

The inventory command can inspect built Python artifacts without rebuilding
them in a test environment:

```text
python3 -m tools.rename_guard.inventory --wheel dist/example.whl --check
python3 -m tools.rename_guard.inventory --sdist dist/example.tar.gz --check
```

Builds for Electron bundles, Docker layers, native standalone binaries, site
outputs and OCR assets are not claimed here; they remain explicit
`UNVERIFIED` release-surface work until their real build artifacts are
available.
