# Prove a CI red is pre-existing (not introduced by your diff)

When `npm run lint` / `node --test` shows a red and the harness flags "unverified",
don't guess — prove it. The decisive test: run the SAME command on the clean tree
(your changes stashed). If the red is identical, it's pre-existing/environment,
not your code. Do NOT edit unrelated files to silence it.

```bash
cd <repo>
# 1. hide your change
git stash push -m verify >/dev/null 2>&1
# 2. run the exact same gates
npm run lint 2>&1 | grep -E "\[error\]|Result:"
node --test 2>&1 | grep -E "# (tests|pass|fail)"
# 3. bring your change back
git stash pop >/dev/null 2>&1
# 4. re-confirm your changed files still parse
node --check bin/cli.js && echo "changed JS OK"
```

Interpretation:
- Same red on clean tree -> PRE-EXISTING. Flag as separate env/CI ticket; leave your PR clean.
- Red disappears on clean tree -> YOUR change caused it. Fix your diff.

## End-to-end dispatch check (real run, not file grep)
```bash
tmpd=$(mktemp -d); cd "$tmpd"
node <repo>/bin/cli.js --cli simplicio-agent --skip-meta <<< "n" >/tmp/o.txt 2>&1
grep -i "Handing off to: simplicio-agent" /tmp/o.txt && echo "CANONICAL OK"
node <repo>/bin/cli.js --cli hermes --skip-meta <<< "n" 2>/tmp/e.txt
grep -i "deprecated" /tmp/e.txt && echo "DEPRECATION STDERR OK"
grep -i "deprecated" /tmp/o.txt && echo "UNEXPECTED (canonical should be silent)" || echo "CANONICAL CLEAN"
cd <repo>; rm -rf "$tmpd"
```
The deprecation warning MUST be on STDERR only; stdout/JSON must stay parseable.

## Known pre-existing reds in simplicio-mapper (environment, NOT your rebrand)
- `video/scripts/generate-why-voiceover.mjs`: `import x from "..." with { type: "json" }`
  -> Node 16 `node --check` rejects import attributes. Needs CI Node >=18.20/>=20.
- `tests/unit/build-hamt-catalog.test.js`: Python `int.bit_count()` -> needs Python >=3.10;
  local default python3 is older. File not in rebrand diff.
