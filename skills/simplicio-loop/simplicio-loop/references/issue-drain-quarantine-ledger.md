# Issue-drain: honest categorizer + quarantine ledger

Condensed from the 2026-07-12 `simplicio-agent` wave (118 open issues). Operationalizes the `simplicio-loop` anti-bulk-close rule (Wesley 2026-07-11): EPICs / roadmap / rename / perf / research-CS / enhancements WITHOUT a reproducible bug AC must NOT be closed by "1 command repros clean" — that is false delivery.

## Step 0 — get the REAL backlog size
`gh issue list --limit 100` silently caps at 100. **Always pass `--limit 200` (or higher).** The 2026-07-12 wave found 118 issues, not the 90/100 a default query implied.

```bash
gh issue list --state open --limit 200 --json number,title,labels,body > /tmp/issues.jsonl
```

## Step 1 — categorize into closeable vs quarantine
A bug-objective issue has: a *specific* failing command/symptom, AC that name the exact repro, and (usually) a `bug`/`regression` label. Everything else (EPIC, Rename, Roadmap, Perf, Research/CS, Core/MCP, Desktop/Ops, enhancement) is **quarantine** until a PR delivers its AC.

Quick categorizer (Python, no LLM):
```python
def cat(t):
    tl=t.lower()
    if '[epic]' in tl: return 'EPIC'
    if 'rename' in tl: return 'RENAME'
    if 'roadmap' in tl or 'unificad' in tl or 'packag' in tl: return 'ROADMAP/PACKAGING'
    if 'perf' in tl: return 'PERF'
    if 'consciousness' in tl or 'physics' in tl or 'cybernetics' in tl or 'asolaria' in tl: return 'RESEARCH/CS'
    if 'core' in tl or 'mcp' in tl: return 'CORE/MCP'
    if 'desktop' in tl or 'ci' in tl or 'update' in tl or 'bundle' in tl or 'ops' in tl: return 'DESKTOP/OPS'
    if '[bug]' in tl or '🐛' in tl: return 'BUG'
    return 'OTHER/ENHANCEMENT'
```

## Step 2 — verify closeable on main, then close with evidence
For each BUG: check if already fixed on `main` (`git log --oneline --all | grep <keyword>`), run the relevant test with the **repo's canonical interpreter** (`/opt/homebrew/bin/python3.11` for simplicio-agent — system `python3` is 3.9 and fails on `int | None` syntax in `utils.py`).

```bash
/opt/homebrew/bin/python3.11 -m pytest tests/tools/test_runtime_manager.py -k banner -q
gh issue comment <N> --body "$EVIDENCE"
gh issue close <N> --comment "..."
```

## Step 3 — quarantine ledger (the honest close for the rest)
Do NOT bulk-close. Create ONE tracking issue listing every quarantined number grouped by category, with a one-line rationale, and leave all of them OPEN. This makes the "partial delivery" explicit and auditable.

```bash
gh issue create --title "[QUARANTINE-LEDGER] N issues without bug-AC — wave YYYY-MM-DD" \
  --body "$(python3 -c '...grouped index...')" --label documentation
```

## Step 4 — live re-query proves state
End the wave with a live count: `gh issue list --state open --limit 200 --json number | python3 -c "import json,sys;print(len(json.load(sys.stdin)))"`. Report closed vs open-tracked honestly (e.g. "2 closed with evidence, 116 open → #252").
