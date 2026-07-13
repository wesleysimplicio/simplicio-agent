---
name: measured-build-report
description: Generate an evidence-backed single-file HTML report (real measured metrics + step-by-step) for any completed build/deliverable. Use when the user asks for a metrics report, build report, "measure it", "relatorio de passo a passo", or wants proof a deliverable works rather than a description.
---

# Measured Build Report

Produce a self-contained HTML report that proves a deliverable with REAL numbers — never estimates. This is the Simplicio evidence discipline (MEASURED|) applied as a deliverable artifact.

## When to use
- User asks: "measure the metrics", "generate a report of the steps", "show me the build report", "relatorio de passo a passo", "prove it works", or any request for evidence about a completed build.
- After completing any build (game, app, script, page) where the user values evidence over prose.

## Steps
1. **Measure, don't estimate.** Run the deterministic probe `scripts/measure_html.py` via `execute_code` or `terminal`, passing the deliverable path and a feature-token map. Capture bytes, lines, parse validity, feature coverage.
   - Example: `python3 scripts/measure_html.py /path/file.html --features '{"Ask name":"nameInput","Top10":"slice(0, maxPlayers)","localStorage":"localStorage"}'`
2. **Fix measurement bugs honestly.** Compute derived values (e.g. grid cells = SIZE/GRID), don't guess. If a heuristic misses (e.g. pause via `e.key === ' '` not the word "Space"), correct the regex and re-run. Report only what you actually measured.
3. **Mark every claim MEASURED|.** No fabricated savings or counts. If you couldn't measure something, say UNVERIFIED| explicitly.
4. **Build the report HTML** (single file, styled, opened in browser). Include:
   - Stat grid: bytes, lines, words, parse errors (=0 target), feature counts, grid size.
   - Requirement coverage table with ✓/✗ derived from token presence in source.
   - Step-by-step build narrative with an evidence string per step (command/constant actually found).
   - Footer: "Generated from real measurements — no numbers fabricated. MEASURED|"
5. **Open it:** `open /path/report.html` (macOS) so the user sees it immediately.

## Pitfalls
- Never use `cat`/`grep`/`ls` for measurement — use `execute_code` (Python) or `search_files`. The probe is re-runnable; hand-typing numbers invites fabrication.
- Derived counts (CSS rules, JS functions) are approximations — label them "approx" so the report stays honest.
- The user wants the step-by-step AND the numbers together. Don't ship one without the other.
- Align with Simplicio claims discipline (`mcp_simplicio_simplicio_claims`): every claim needs an evidence ref.

## Support files
- `scripts/measure_html.py` — deterministic HTML/CSS/JS metric probe (bytes, lines, parse validity, feature tokens). No external deps.
- `references/snake-challenge-example.md` — concrete worked example (this session's snake game numbers).
