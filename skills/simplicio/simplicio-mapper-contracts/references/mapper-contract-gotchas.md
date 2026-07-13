# mapper-contract-gotchas.md

Detailed reproduction recipes for the pitfalls in `simplicio-mapper-contracts`.
Captured during issue #208 (ContextSnapshot/ContextGraph, Passo 1).

## 1. contract.py native validator has NO `const` support

`simplicio_mapper/contract.py`'s subset validator (`_type_matches`,
`_check_required`, `_check_properties`) implements only: type, required,
properties, items, enum, minItems. It does NOT implement `const`. If you write
`"schema": {"const": "simplicio.x/v1"}`, the `const` keyword is silently
ignored and ANY string passes — a false sense of safety.

FIX: use `{"enum": ["simplicio.x/v1"]}`. `enum` IS implemented and rejects
non-listed values.

## 2. Schemas are NOT packaged by default

`contracts/mapper-artifacts/v1/README.md` explicitly states its schemas are
NOT shipped in the wheel. But an AC like issue #208's "clean install consegue
validá-los" OVERRIDES that for a new family.

FIX (pyproject.toml):

```toml
[tool.hatch.build.targets.wheel.force-include]
"contracts/context-snapshot" = "simplicio_mapper/contracts/context-snapshot"

[tool.hatch.build.targets.sdist]
include = [ ..., "contracts/context-snapshot" ]
```

Then in `contract.py` `load_schema`, for the new family resolve from
`os.path.join(os.path.dirname(os.path.abspath(__file__)), "contracts",
"<family>", CONTRACT_VERSION, "schemas")`, falling back to the repo source
dir (`../../contracts/<family>/...`) when the package dir is absent (checkout).

Verify: `python3 -m build --wheel`, then
`python3 -c "import zipfile; z=zipfile.ZipFile('dist/*.whl'); print([n for n in z.namelist() if 'context-snapshot' in n])"`.

## 3. Python tests must be unittest.TestCase subclasses

`python3 -m unittest discover -s tests/python -p test_x.py` finds ONLY classes
subclassing `unittest.TestCase`. Bare `def test_...()` functions return
"Ran 0 tests" with no error — a silent no-op.

FIX: wrap every test in `class XxxTest(unittest.TestCase):` and run with
`python3 -m unittest discover -s tests/python` (or `-m pytest tests/python`).

## 4. ruff E702 on command tuples in _args.py

Adding `"snapshot",` to the `commands` tuple then leaving `)` on a separate
line triggers E702 (multiple statements). ruff formatter collapses tuples to a
2-column layout.

FIX: after editing `simplicio_mapper/cli/_args.py`, run
`python3 -m ruff format simplicio_mapper/cli/_args.py` then `ruff check`.

## 5. Content-addressed snapshot_id

Canonical serialization for the hash:
- Exclude volatile fields from the body: `snapshot_id`, `generated_at`,
  `producer`, `schema_version`.
- `body_str = json.dumps(body, sort_keys=True, separators=(",", ":"),
  ensure_ascii=False)`
- `snapshot_id = "sha256:" + sha256(body_str.encode("utf-8")).hexdigest()`
  (use `_native.sha256_hex` if present, else `hashlib`).

Determinism test: same inputs -> same id; one changed byte in a source
artifact -> different id. Recompute via `snapshot_id_of(payload)` and assert
equals `payload["snapshot_id"]`.

## 6. Prove a repo failure is pre-existing (not your regression)

When the full suite shows failures unrelated to your files:
```bash
git diff main...HEAD --name-only | grep -E "video/scripts|build-hamt|\.mjs|test_cli"
# if the failing file does NOT appear -> pre-existing, outside your diff
```
Optional airtight proof: copy the `main` version of the test file and run the
specific failing test against it — if it fails identically, it's environmental.
(For issue #208, `test_background_index_reports_pid_and_log` and
`test_scan_async_returns_before_deep_completes` fail identically on pristine
`main`; they are async/timing env issues, not regressions.)

Also run the test module that imports what you touched as a regression guard:
- edited `contract.py` -> run `tests.python.test_contract` (24 tests, must be OK).
- edited `cli/__init__.py`/`_args.py` -> run `tests.python.test_cli`.
