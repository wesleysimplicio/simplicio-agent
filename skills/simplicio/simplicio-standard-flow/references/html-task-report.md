# HTML Task Report Pattern — "Build + Measure + Report"

## When to use
When the user asks for a **deliverable + measured summary**: tokens, time, tools, reasoning, and/or cost. The pattern covers a single request that produces:
- a working artifact (game, tool, page, script)
- a standalone HTML report with structured tables showing everything spent

## Report structure (proven on 2026-07-08 snake-game)

The canonical report has these sections in order, each backed by tables:

### 1. Summary cards (top row)
- File size / lines / tools called / input tokens / output tokens
- Each card: big number + label

### 2. Metadata
- Model, provider, agent, runtime version, host, pipeline, total time, LOC
- Grid layout (key: value pairs)

### 3. Step-by-step table
Columns: # | Ação | Ferramenta | Duração | Tempo (ms)
One row per major tool call. Includes: skill loading, dir creation, file writes, verification, evidence.

### 4. Technical decisions & rationale table
Columns: Decisão | Alternativa | Por que escolhi assim
~10 rows covering architecture, UX, performance, and trade-off choices.

### 5. Token breakdown (the key measurement section)
Columns: Ferramenta | Chamadas | Input Tokens (est.) | Output Tokens (est.) | Total (est.)
Include a disclaimer box marking UNVERIFIED| when estimation is used (no native token tracker).
Footer row with totals.
Follow with horizontal bar chart showing % distribution by tool category.

### 6. Cost estimation table
Columns: Item | Quantidade | Preço Unit. | Total
Convert tokens → USD using current API pricing. Show total + local currency.

### 7. Evidence chain table
Columns: Tipo | Referência | Status (MEASURED| / UNVERIFIED|)
Sketch which claims have real receipts and which are estimates.

### 8. Feature checklist table
Columns: Funcionalidade | Implementação
Complete list of what the deliverable does.

### 9. Gaps identified in the runtime
Columns: Gap | Impacto | Sugestão
Honest assessment of what the runtime couldn't do that would have made the task cheaper/faster.

## CSS styling constants
- Background: `#0a0a1a` (dark)
- Primary accent: `#00ff88` (green neon)
- Secondary accent: `#00ccff` (cyan)
- Warning: `#ffd700` (gold)
- Error: `#ff4466` (pink)
- Table header: `rgba(0,204,255,0.08)` bg, `#00ccff` text
- Card bg: `rgba(255,255,255,0.03)` border 1px
- Table cell border: `rgba(255,255,255,0.04)`
- Tag badges: colored bg (12% opacity) + same color text

## Tag classes (for status badges in tables)
```css
.tag-green { background: rgba(0,255,136,0.12); color: #00ff88; } /* MEASURED| */
.tag-blue  { background: rgba(0,204,255,0.12); color: #00ccff; } /* tool/MCP */
.tag-yellow { background: rgba(255,215,0,0.12); color: #ffd700; } /* UNVERIFIED| */
.tag-gray  { background: rgba(255,255,255,0.06); color: #888; } /* terminal */
```

## Token estimation heuristic (when no native tracker exists)
- Input: ~1 token per 4 characters (standard for most LLMs)
- Output: ~1 token per 5 characters (JSON/code heavy, slightly denser)
- Always label as UNVERIFIED| and add a warning box explaining the methodology

## Pitfalls
- Do NOT fabricate token counts — if no tracker tool exists, mark UNVERIFIED| and explain
- Do NOT skip the gaps section — it's the action item for runtime evolution
- Keep the report as a single HTML file (no external CSS/JS dependencies) — zero-deploy, open anywhere
- The model's token billing per-1M-tokens might differ from the API provider's actual pricing — check current rates (deepseek-v4-flash: $0.30/1M input, $0.90/1M output as of Jul 2026)