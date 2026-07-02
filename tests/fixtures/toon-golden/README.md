# TOON golden corpus (vendored)

Conformance fixtures for the shared ecosystem spec, `TOON-CONTRACT.md`
(repo root). Vendored verbatim from the canonical host,
[`simplicio-mapper`](https://github.com/wesleysimplicio/simplicio-mapper)
(issue [#149](https://github.com/wesleysimplicio/simplicio-mapper/issues/149),
PR #152, commit `9819f309de7227e6bed30c6df92419eea82b56e6`) — every
`input.json` / `expected.toon` / `input.toon` / `meta.json` file below is a
byte-for-byte copy of that repo's `fixtures/toon-golden/`. `manifest.json`
is the same case index; `TOON-CONTRACT.md` at the repo root is the same
contract text. See that document for the full spec.

This repo places the corpus under `tests/fixtures/toon-golden/` (matching
this repo's own `tests/fixtures/` convention) rather than mapper's
top-level `fixtures/toon-golden/` — everything else (structure, file names,
byte content) is unchanged.

```
manifest.json            case index (id, tags, description) for valid/invalid
valid/<case-id>/input.json     JSON value
valid/<case-id>/expected.toon  canonical TOON encoding (produced by
                                simplicio-mapper's own codec -- the
                                canonical reference implementation)
invalid/<case-id>/input.toon   malformed/truncated TOON text
invalid/<case-id>/meta.json    {"error_class": "...", "reason_contains": "...", "description": "..."}
```

Run the conformance check for this repo's codec (`agent.toon_codec`):

```bash
python3 scripts/toon_contract_runner.py
# or via the unit suite:
scripts/run_tests.sh tests/agent/test_toon_codec.py -k toon_contract
```

A `valid` case passes when:

1. `from_toon(to_toon(input.json)) == input.json` (this repo's own
   round-trip is lossless), and
2. `from_toon(expected.toon) == input.json` (this repo's decoder
   understands the canonical encoding another repo produced).

Byte-identical match between a fresh `to_toon(input.json)` and the
committed `expected.toon` is **not** required here — that is only a
requirement for `simplicio-mapper`'s own codec (see
`scripts/toon_contract_runner.py`'s module docstring for why).

An `invalid` case passes when `from_toon(input.toon)` raises a
`ValueError`-family error (`agent.toon_codec.ToonDecodeError`, never a bare
index/key error — see `TOON-CONTRACT.md` §5) whose message contains
`meta.json`'s `reason_contains` substring.

## Re-vendoring

This repo does not run a live network sync against `simplicio-mapper` (this
repo's test suite is hermetic/offline by convention — see AGENTS.md
"Testing"). To refresh the corpus after an upstream change to
`TOON-CONTRACT.md` or its fixtures, manually diff against
`simplicio-mapper`'s `TOON-CONTRACT.md` and `fixtures/toon-golden/` at a
newer commit and re-copy byte-for-byte, updating the source commit noted
above.
