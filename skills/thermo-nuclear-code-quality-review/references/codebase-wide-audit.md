# Codebase-Wide Audit Workflow

Use when the user says "review all our code" or "apply the review skill to everything."

## Triage Heuristic: File Size

The #1 signal is file size. The skill's rule #1 says:
> Do not let a file be over 1k lines without a very strong reason.

For existing codebases, apply the same rule retroactively.

### Scan command
```bash
find src -name '*.rs' -exec wc -l {} + | sort -rn | head -30
```

### Thresholds for flagging
| Size | Severity | Action |
|---|---|---|
| > 10,000 lines | 🔥 Critical | Must be decomposed immediately |
| 5,000–10,000 | 🚨 High | Strong candidate for extraction |
| 2,000–5,000  | ⚠️ Medium | Flag with suggested decomposition |
| 1,000–2,000  | 📝 Low | Note but lower priority |

## Scan Dimensions (in order)

1. **File sizes** — how many files exceed 1K lines; which are the top offenders
2. **Module naming** — look for `real_NNNN.rs`, `final_*.rs`, or other non-descriptive names. Every module name should tell you what it contains. Numeric suffixes are technical debt.
3. **Dead code** — count `#![allow(dead_code)]` and `#[allow(dead_code)]` instances. Each is a module or function that compiles but may not be wired into any real flow.
4. **Inline functions in main/crate root** — a crate root with 2,000+ inline functions indicates insufficient extraction. Count with:
   ```bash
   grep -c "^fn \|^pub fn \|^async fn \|^pub async fn " main.rs
   ```
5. **Module count** — how many child modules are declared; if the crate root has 600+ `mod` statements but still 2,000+ inline functions, the extraction is incomplete.

## Report Format

Present findings in priority order per the skill's Output Expectations:

1. **Critical**: files > 10K lines — immediate extraction plan needed
2. **High**: files with non-descriptive names, dead code, structural spaghetti
3. **Medium**: files 2-5K lines that should be split
4. **Low**: files 1-2K lines, naming improvements

Each finding should include:
- File path and line count
- Why it's a problem (reference the specific skill rule)
- Concrete remediation suggestion (code judo move or extraction path)

## Tone

Per the skill: "Be direct, serious, and demanding about quality. Do not be rude, but do not soften major maintainability issues into mild suggestions."

Good framing: "The skill says X. This file violates that at severity Y because Z. The fix is to..."

## Example Output Structure

```
🚨 FINDING N (SEVERITY): file.rs — NNN linhas

Status: Violação da regra #N (reason)

Evidence: [specific data point]

What to do: [actionable step]
```
