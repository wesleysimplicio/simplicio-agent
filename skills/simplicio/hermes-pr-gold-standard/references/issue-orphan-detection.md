# Issue Orphan Detection Pipeline

> Find unaddressed issues → verify they're truly orphaned → scope the fix.
> Validated on NousResearch/hermes-agent, 2026-07-05.

## Pipeline

### Step 1: Find candidate issues

```bash
# Bug + docs issues, newest first
gh api "repos/NousResearch/hermes-agent/issues?state=open&labels=type/bug,type/docs&sort=created&direction=desc&per_page=10" \
  --jq '.[] | select(.pull_request == null) | [.number,.title,.created_at[0:10],.labels[].name] | @tsv'
```

Adjust `labels=` to target other types (`type/enhancement`, `type/refactor`, etc.).
Increase `per_page` from 10 if the pool is small.

### Step 2: Verify no linked PR exists

An issue might look orphaned but already have a linked PR via cross-reference:

```bash
gh api "repos/NousResearch/hermes-agent/issues/<N>/timeline" \
  --jq '[.[] | select(.source and .source.issue and .source.issue.pull_request) | .source.issue.number]'
```

- **Empty array `[]`** → truly orphaned ✅
- **Non-empty** → linked PR exists → skip this issue

The timeline endpoint catches cross-references, not just the GitHub UI "linked PR" field.
PR numbers like `#40390` in a timeline mean someone *mentioned* or *connected* the issue
to that PR — but the PR may still be open, not merged. Check the PR state before
concluding the issue is resolved (`gh pr view <N> --json state`).

### Step 3: Scope the fix

```bash
# Where is the relevant source code?
# 1. Find directories matching the issue topic
find /repo/src -maxdepth 4 -name "*.css" -not -path "*/node_modules/*" | head -20

# 2. Check for separate repos (landing pages, docs sites, etc.)
gh search repos "hermes" --owner NousResearch --json name --limit 20 | jq -r '.[].name'

# 3. Read the relevant file(s) to assess complexity
wc -l <file>
```

### Step 4: Assess fix complexity

| Signal | Effort | Action |
|--------|--------|--------|
| Mechanical (noqa, typo, config list) | Low | Open PR directly |
| Design judgment (colors, layout, UX) | Medium | Requires maintainer input — open PR with before/after |
| Architectural (new feature, API change) | High | Flag for future session, skip if quick-fill needed |

## Concrete Example — Issue #39432

**Signal:** "官网新视觉主题对比度过低" — website contrast too low

**Orphan check:**
```bash
gh api "repos/NousResearch/hermes-agent/issues/39432/timeline" \
  --jq '[.[] | select(.source and .source.issue and .source.issue.pull_request) | .source.issue.number]'
# Result: [] — truly orphaned ✓
```

**Scope check:**
- Repo has `website/` (Docusaurus docs) and `web/` (Electron dashboard)
- Landing page at hermes-agent.nousresearch.com is built from `website/`
- Docusaurus CSS at `website/src/css/custom.css`
- WCAG check: `#8B6508` on white ≈ 3.5:1 (fails AA for body text)
- No separate landing page repo under NousResearch org

**Complexity:** Medium. CSS has WCAG-aware values already, but actual landing page
may be deployed separately (Cloudflare Pages, etc.) outside this repo.

## WCAG Contrast Quick Reference

| Text type | Min contrast (AA) | Min contrast (AAA) |
|-----------|-------------------|-------------------|
| Normal text (<18px) | 4.5:1 | 7:1 |
| Large text (≥18px bold or ≥24px) | 3:1 | 4.5:1 |

Common ratios:
- `#FFD700` on `#FFFFFF` = 1.4:1 ❌
- `#8B6508` on `#FFFFFF` ≈ 3.5:1 ⚠️ (passes large text only)
- `#FFD700` on `#07070d` ≈ 13:1 ✅
